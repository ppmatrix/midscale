import asyncio
from typing import Optional

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig
from daemon.models import DaemonState
from daemon.stun_client import query_stun_server, query_stun_servers

logger = structlog.get_logger(__name__)


def _get_local_ip() -> Optional[str]:
    """Detect the local (private) IP address via UDP socket trick."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None


class EndpointMonitor:
    """Detects endpoint changes and reports them to the control plane.

    Uses two discovery methods:
    1. STUN (RFC 5389) — queries the configured STUN server(s) to
       discover the device's public IP:port as seen from the internet.
    2. Local socket — detects the private IP via a UDP connect trick
       (fallback when STUN is unavailable).

    Reports discovered endpoints with appropriate source tags so the
    control plane can use them for direct peer-to-peer connections in
    mesh/hybrid topologies.
    """

    def __init__(
        self,
        config: DaemonConfig,
        api_client: MidscaleAPIClient,
    ):
        self._config = config
        self._api = api_client
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stun_servers: list[tuple[str, int]] = []

    def _parse_stun_servers(self) -> list[tuple[str, int]]:
        servers = []
        for entry in self._config.stun_servers:
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                host, port_str = entry.rsplit(":", 1)
                try:
                    port = int(port_str)
                except ValueError:
                    port = 3478
                servers.append((host, port))
            else:
                servers.append((entry, 3478))
        if not servers:
            from urllib.parse import urlparse
            server_url = self._config.server_url
            parsed = urlparse(server_url)
            host = parsed.hostname or "localhost"
            servers.append((host, 3478))
        return servers

    async def start(self, state: DaemonState) -> None:
        if self._running:
            return
        self._running = True
        self._stun_servers = self._parse_stun_servers()
        logger.info(
            "endpoint monitor started",
            interval_seconds=self._config.endpoint_check_interval_seconds,
            stun_servers=self._stun_servers,
        )
        self._task = asyncio.create_task(
            self._run_loop(state)
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("endpoint monitor stopped")

    async def _detect_endpoint_stun(self) -> Optional[tuple[str, str, str]]:
        """Try STUN discovery first.

        Returns
        -------
        tuple[str, str, str] or None
            (endpoint_str, public_ip, local_ip) or None.
        """
        if not self._config.stun_enabled or not self._stun_servers:
            return None

        local_ip = _get_local_ip()
        result = await query_stun_servers(
            self._stun_servers,
            timeout=self._config.stun_timeout,
        )
        if result:
            endpoint = f"{result.public_ip}:{self._config.wg_port}"
            logger.info(
                "stun endpoint discovered",
                public_ip=result.public_ip,
                public_port=result.public_port,
                local_ip=local_ip,
                server=result.server,
                rtt_ms=result.rtt_ms,
            )
            return endpoint, result.public_ip, local_ip or result.public_ip
        return None

    async def _detect_endpoint_local(self) -> Optional[tuple[str, str, str]]:
        """Fallback: detect local IP via socket trick.

        Returns
        -------
        tuple[str, str, str] or None
            (endpoint_str, public_ip, local_ip) or None.
        """
        local_ip = _get_local_ip()
        if local_ip:
            endpoint = f"{local_ip}:{self._config.wg_port}"
            logger.info(
                "local endpoint detected",
                local_ip=local_ip,
            )
            return endpoint, local_ip, local_ip
        return None

    async def _detect_endpoint(self) -> Optional[tuple[str, str, str, str]]:
        """Detect endpoint, trying STUN first then local fallback.

        Returns
        -------
        tuple[str, str, str, str] or None
            (endpoint_str, source_tag, public_ip, local_ip) or None.
        """
        stun = await self._detect_endpoint_stun()
        if stun:
            ep, pub_ip, loc_ip = stun
            return ep, "stun", pub_ip, loc_ip

        local = await self._detect_endpoint_local()
        if local:
            ep, pub_ip, loc_ip = local
            return ep, "local", pub_ip, loc_ip

        return None

    async def _run_loop(self, state: DaemonState) -> None:
        await asyncio.sleep(2)
        while self._running:
            try:
                detected = await self._detect_endpoint()
                if detected:
                    endpoint, source, public_ip, local_ip = detected
                    if endpoint != state.current_endpoint:
                        result = await self._api.report_endpoint(
                            endpoint=endpoint,
                            source=source,
                            port=self._config.wg_port,
                            local_ip=local_ip,
                            public_ip=public_ip,
                        )
                        if result.success:
                            state.current_endpoint = endpoint
                            state.last_endpoint_report = (
                                __import__("datetime")
                                .datetime.now(__import__("datetime").timezone.utc)
                            )
                            logger.info(
                                "endpoint updated",
                                endpoint=endpoint,
                                source=source,
                                public_ip=public_ip,
                                local_ip=local_ip,
                            )
                        else:
                            logger.warning(
                                "endpoint report failed",
                                error=result.error,
                            )
            except Exception as e:
                logger.error("endpoint detection error", error=str(e))

            await asyncio.sleep(
                self._config.endpoint_check_interval_seconds
            )
