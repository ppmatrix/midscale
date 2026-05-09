import asyncio
import json
from typing import Optional

import httpx
import structlog

from daemon.config import DaemonConfig
from daemon.models import (
    ConfigPullResult,
    ConfigV2PullResult,
    EndpointReportResult,
    EnrollResult,
    HeartbeatResult,
    ProbeReportResult,
    RegistrationResult,
    RouteAdvertiseResult,
)

logger = structlog.get_logger(__name__)


class MidscaleAPIClient:
    """HTTP client for the Midscale control plane API.

    Handles device registration, config pulling, heartbeat, and
    endpoint reporting. Implements retry with exponential backoff.
    """

    def __init__(self, config: DaemonConfig):
        self._config = config
        self._base_url = config.server_url.rstrip("/")
        self._device_token: Optional[str] = None
        self._device_id: Optional[str] = None
        self._client = httpx.AsyncClient(
            verify=config.tls_verify,
            timeout=config.request_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def set_device_auth(self, device_id: str, token: str) -> None:
        self._device_id = device_id
        self._device_token = token

    @property
    def device_id(self) -> Optional[str]:
        return self._device_id

    @property
    def device_token(self) -> Optional[str]:
        return self._device_token

    def _auth_headers(self) -> dict[str, str]:
        if self._device_token:
            return {"Authorization": f"Bearer {self._device_token}"}
        return {}

    async def enroll(
        self, preauth_key: str, device_name: str, public_key: str
    ) -> EnrollResult:
        logger.info("enrolling device", name=device_name)
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/devices/enroll",
                json={
                    "preauth_key": preauth_key,
                    "name": device_name,
                    "public_key": public_key,
                },
                timeout=self._config.request_timeout_seconds,
            )
            if resp.status_code == 201:
                data = resp.json()
                device_id = data.get("device_id")
                device_token = data.get("device_token")
                network_id = data.get("network_id")
                ip_address = data.get("ip_address")
                config_v2 = data.get("config_v2")
                self.set_device_auth(device_id, device_token)
                logger.info(
                    "device enrolled",
                    device_id=device_id,
                    ip_address=ip_address,
                )
                return EnrollResult(
                    success=True,
                    device_id=device_id,
                    device_token=device_token,
                    network_id=network_id,
                    ip_address=ip_address,
                    config_v2=config_v2,
                )
            else:
                detail = self._extract_error(resp)
                logger.error("enrollment failed", detail=detail)
                return EnrollResult(success=False, error=detail)
        except httpx.RequestError as e:
            logger.error("enrollment request failed", error=str(e))
            return EnrollResult(success=False, error=str(e))

    async def pull_config_v2(self) -> ConfigV2PullResult:
        if not self._device_id or not self._device_token:
            return ConfigV2PullResult(
                success=False, error="not enrolled"
            )
        try:
            resp = await self._client.get(
                f"{self._base_url}/api/v1/devices/{self._device_id}/config-v2",
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info("config-v2 pulled from server")
                return ConfigV2PullResult(
                    success=True,
                    interface=data.get("interface"),
                    peers=data.get("peers"),
                    routes=data.get("routes"),
                    exit_node=data.get("exit_node"),
                    revision=data.get("revision"),
                    hash=data.get("hash"),
                    version=data.get("version"),
                )
            else:
                detail = self._extract_error(resp)
                logger.error("config-v2 pull failed", detail=detail)
                return ConfigV2PullResult(success=False, error=detail)
        except httpx.RequestError as e:
            logger.error("config-v2 pull request failed", error=str(e))
            return ConfigV2PullResult(success=False, error=str(e))

    async def register(
        self, preauth_key: str, device_name: str
    ) -> RegistrationResult:
        logger.info("registering device", name=device_name)
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/devices/register",
                json={"key": preauth_key, "name": device_name},
                timeout=self._config.request_timeout_seconds,
            )
            if resp.status_code == 201:
                data = resp.json()
                device_id = data.get("id")
                logger.info(
                    "device registered",
                    device_id=device_id,
                    ip_address=data.get("ip_address"),
                )
                return RegistrationResult(
                    success=True, device_id=device_id
                )
            else:
                detail = self._extract_error(resp)
                logger.error("registration failed", detail=detail)
                return RegistrationResult(
                    success=False, error=detail
                )
        except httpx.RequestError as e:
            logger.error("registration request failed", error=str(e))
            return RegistrationResult(success=False, error=str(e))

    async def pull_config(self) -> ConfigPullResult:
        if not self._device_id:
            return ConfigPullResult(
                success=False, error="not registered"
            )
        try:
            resp = await self._client.get(
                f"{self._base_url}/api/v1/devices/{self._device_id}/config",
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info("config pulled from server")
                return ConfigPullResult(
                    success=True,
                    config_ini=data.get("config"),
                    filename=data.get("filename"),
                )
            else:
                detail = self._extract_error(resp)
                logger.error("config pull failed", detail=detail)
                return ConfigPullResult(success=False, error=detail)
        except httpx.RequestError as e:
            logger.error("config pull request failed", error=str(e))
            return ConfigPullResult(success=False, error=str(e))

    async def send_heartbeat(
        self, public_key: Optional[str] = None, ip_address: Optional[str] = None
    ) -> HeartbeatResult:
        if not self._device_id:
            return HeartbeatResult(success=False, error="not registered")
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/devices/{self._device_id}/heartbeat",
                json={
                    "public_key": public_key,
                    "ip_address": ip_address,
                },
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                return HeartbeatResult(success=True)
            else:
                detail = self._extract_error(resp)
                return HeartbeatResult(success=False, error=detail)
        except httpx.RequestError as e:
            return HeartbeatResult(success=False, error=str(e))

    async def report_endpoint(
        self, endpoint: str, source: str = "handshake", port: int = 51820,
        local_ip: Optional[str] = None,
        public_ip: Optional[str] = None,
    ) -> EndpointReportResult:
        if not self._device_id:
            return EndpointReportResult(
                success=False, error="not registered"
            )
        body = {"endpoint": endpoint, "source": source, "port": port}
        if local_ip is not None:
            body["local_ip"] = local_ip
        if public_ip is not None:
            body["public_ip"] = public_ip
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/devices/{self._device_id}/endpoint",
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                return EndpointReportResult(success=True)
            else:
                detail = self._extract_error(resp)
                return EndpointReportResult(success=False, error=detail)
        except httpx.RequestError as e:
            return EndpointReportResult(success=False, error=str(e))

    async def report_probe_result(
        self,
        peer_device_id: str,
        endpoint: str,
        reachable: bool,
        port: int = 51820,
        latency_ms: Optional[float] = None,
        local_ip: Optional[str] = None,
        public_ip: Optional[str] = None,
    ) -> ProbeReportResult:
        if not self._device_id:
            return ProbeReportResult(success=False, error="not enrolled")
        body = {
            "peer_device_id": peer_device_id,
            "endpoint": endpoint,
            "reachable": reachable,
            "port": port,
            "source": "probe",
        }
        if latency_ms is not None:
            body["latency_ms"] = latency_ms
        if local_ip is not None:
            body["local_ip"] = local_ip
        if public_ip is not None:
            body["public_ip"] = public_ip
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/devices/{self._device_id}/probe-result",
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                return ProbeReportResult(success=True)
            else:
                detail = self._extract_error(resp)
                return ProbeReportResult(success=False, error=detail)
        except httpx.RequestError as e:
            return ProbeReportResult(success=False, error=str(e))

    async def advertise_route(self, prefix: str) -> RouteAdvertiseResult:
        if not self._device_id:
            return RouteAdvertiseResult(success=False, error="not registered")
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/routes/devices/{self._device_id}/advertise",
                json={"prefix": prefix, "is_exit_node": False},
                headers=self._auth_headers(),
            )
            if resp.status_code in (200, 201):
                return RouteAdvertiseResult(success=True)
            detail = self._extract_error(resp)
            return RouteAdvertiseResult(success=False, error=detail)
        except httpx.RequestError as e:
            return RouteAdvertiseResult(success=False, error=str(e))

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self._base_url}/health", timeout=5
            )
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    async def connect_websocket(self) -> Optional["WebSocketClient"]:
        """Connect to the daemon WebSocket endpoint and return a client."""
        if not self._device_token or not self._device_id:
            logger.error("cannot connect websocket: not enrolled")
            return None
        try:
            from daemon.ws_client import DaemonWebSocketClient
            ws = DaemonWebSocketClient(
                server_url=self._base_url,
                device_token=self._device_token,
                device_id=self._device_id,
            )
            await ws.connect()
            return ws
        except Exception as e:
            logger.error("websocket connection failed", error=str(e))
            return None

    def _extract_error(self, resp: httpx.Response) -> str:
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = body.get("detail", body)
                if isinstance(detail, list):
                    return "; ".join(
                        e.get("msg", str(e)) for e in detail
                    )
                return str(detail)
            return str(body)
        except (json.JSONDecodeError, ValueError):
            return resp.text[:200]
