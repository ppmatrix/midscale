"""Peer connectivity probing engine.

Performs lightweight UDP connectivity checks against peer endpoint
candidates to measure latency and verify reachability. Results are
reported to the Midscale control plane for candidate scoring.

This is NOT full hole punching. This is pre-punch discovery: the
daemon sends probe packets and records whether peers are reachable
and how fast they respond.
"""

import asyncio
import random
import socket
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig

logger = structlog.get_logger(__name__)


@dataclass
class ProbeTarget:
    """An endpoint candidate to probe."""

    peer_device_id: str
    public_key: str
    endpoint: str
    port: int = 51820


@dataclass
class ProbeResult:
    """Result of probing a single endpoint."""

    peer_device_id: str
    endpoint: str
    port: int
    reachable: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class PeerProber:
    """Periodic peer connectivity probing engine.

    Probes endpoint candidates received from config-v2 and reports
    results to the control plane for candidate scoring and preferred
    endpoint selection.
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
        self._targets: list[ProbeTarget] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "peer prober started",
            interval_seconds=self._config.probe_interval_seconds,
            timeout=self._config.probe_timeout,
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
        logger.info("peer prober stopped")

    def update_targets(self, targets: list[ProbeTarget]) -> None:
        """Update the list of endpoints to probe (called after config refresh)."""
        self._targets = targets
        logger.debug("probe targets updated", count=len(targets))

    async def _probe_endpoint(
        self, target: ProbeTarget
    ) -> ProbeResult:
        """Probe a single endpoint with a lightweight UDP ping.

        Sends a small random UDP packet to the target endpoint and
        waits for an ICMP port unreachable or any response to measure
        round-trip time.
        """
        start = time.monotonic()
        family = socket.AF_INET
        if ":" in target.endpoint:
            family = socket.AF_INET6

        try:
            loop = asyncio.get_running_loop()
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.settimeout(self._config.probe_timeout)
            sock.connect((target.endpoint, target.port))

            probe_data = random.randbytes(16)
            await loop.sock_sendall(sock, probe_data)

            try:
                await loop.sock_recv(sock, 1024)
                elapsed = (time.monotonic() - start) * 1000
                sock.close()
                return ProbeResult(
                    peer_device_id=target.peer_device_id,
                    endpoint=target.endpoint,
                    port=target.port,
                    reachable=True,
                    latency_ms=round(elapsed, 1),
                )
            except (socket.timeout, TimeoutError, OSError):
                elapsed = (time.monotonic() - start) * 1000
                sock.close()
                return ProbeResult(
                    peer_device_id=target.peer_device_id,
                    endpoint=target.endpoint,
                    port=target.port,
                    reachable=False,
                    latency_ms=round(elapsed, 1),
                    error="timeout",
                )
        except Exception as e:
            logger.debug(
                "probe error",
                peer=target.peer_device_id,
                endpoint=target.endpoint,
                error=str(e),
            )
            return ProbeResult(
                peer_device_id=target.peer_device_id,
                endpoint=target.endpoint,
                port=target.port,
                reachable=False,
                error=str(e),
            )

    async def _run_probe_cycle(self) -> None:
        """Probe all known targets and report results."""
        if not self._targets:
            return
        logger.debug("starting probe cycle", targets=len(self._targets))
        for target in self._targets:
            if not self._running:
                break
            result = await self._probe_endpoint(target)
            if result.reachable:
                logger.info(
                    "peer reachable",
                    peer=result.peer_device_id,
                    endpoint=result.endpoint,
                    latency_ms=result.latency_ms,
                )
            if self._running:
                await self._api.report_probe_result(
                    peer_device_id=result.peer_device_id,
                    endpoint=result.endpoint,
                    reachable=result.reachable,
                    port=result.port,
                    latency_ms=result.latency_ms,
                )

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            if self._config.probe_enabled:
                try:
                    await self._run_probe_cycle()
                except Exception as e:
                    logger.error("probe cycle error", error=str(e))
            await asyncio.sleep(self._config.probe_interval_seconds)
