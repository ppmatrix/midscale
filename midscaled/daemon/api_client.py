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
    RelaySessionResult,
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

    async def request_nat_punch(
        self,
        target_device_id: str,
        initiator_endpoint: str,
        initiator_port: int = 51820,
        initiator_local_ip: Optional[str] = None,
        initiator_public_ip: Optional[str] = None,
    ) -> Optional[dict]:
        if not self._device_id:
            logger.error("cannot punch: not enrolled")
            return None
        body = {
            "target_device_id": target_device_id,
            "initiator_endpoint": initiator_endpoint,
            "initiator_port": initiator_port,
        }
        if initiator_local_ip:
            body["initiator_local_ip"] = initiator_local_ip
        if initiator_public_ip:
            body["initiator_public_ip"] = initiator_public_ip
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/nat/punch",
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 201:
                return resp.json()
            logger.warning("nat punch request failed", status=resp.status_code)
            return None
        except httpx.RequestError as e:
            logger.error("nat punch request error", error=str(e))
            return None

    async def report_nat_punch_result(
        self,
        session_id: str,
        success: bool,
        selected_endpoint: Optional[str] = None,
        selected_port: Optional[int] = None,
        latency_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> bool:
        if not self._device_id:
            return False
        body = {
            "session_id": session_id,
            "success": success,
        }
        if selected_endpoint:
            body["selected_endpoint"] = selected_endpoint
        if selected_port:
            body["selected_port"] = selected_port
        if latency_ms is not None:
            body["latency_ms"] = latency_ms
        if error:
            body["error"] = error
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/nat/{session_id}/result",
                json=body,
                headers=self._auth_headers(),
            )
            return resp.status_code == 200
        except httpx.RequestError as e:
            logger.error("nat punch result report error", error=str(e))
            return False

    async def report_nat_connectivity_validation(
        self,
        session_id: str,
        target_endpoint: str,
        target_port: int,
        reachable: bool,
        latency_ms: Optional[int] = None,
    ) -> Optional[dict]:
        if not self._device_id:
            return None
        body = {
            "session_id": session_id,
            "target_endpoint": target_endpoint,
            "target_port": target_port,
            "reachable": reachable,
        }
        if latency_ms is not None:
            body["latency_ms"] = latency_ms
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/nat/{session_id}/validate",
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except httpx.RequestError as e:
            logger.error("nat connectivity validation error", error=str(e))
            return None

    async def request_relay_session(
        self,
        target_device_id: str,
        relay_region: str = "default",
    ) -> RelaySessionResult:
        if not self._device_id:
            return RelaySessionResult(success=False, error="not enrolled")
        body = {
            "target_device_id": target_device_id,
            "relay_region": relay_region,
        }
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/relay/sessions",
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 201:
                data = resp.json()
                return RelaySessionResult(
                    success=True,
                    session_id=data.get("id"),
                    relay_token=data.get("relay_token"),
                    relay_region=data.get("relay_region"),
                    relay_node=data.get("relay_node"),
                )
            detail = self._extract_error(resp)
            return RelaySessionResult(success=False, error=detail)
        except httpx.RequestError as e:
            return RelaySessionResult(success=False, error=str(e))

    async def connect_relay_session(
        self, session_id: str
    ) -> RelaySessionResult:
        if not self._device_id:
            return RelaySessionResult(success=False, error="not enrolled")
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/relay/connect",
                json={"session_id": session_id},
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                return RelaySessionResult(
                    success=True,
                    session_id=data.get("session_id"),
                    relay_token=data.get("relay_token"),
                    relay_region=data.get("relay_region"),
                    relay_node=data.get("relay_node"),
                )
            detail = self._extract_error(resp)
            return RelaySessionResult(success=False, error=detail)
        except httpx.RequestError as e:
            return RelaySessionResult(success=False, error=str(e))

    async def request_relay_session_update(
        self,
        relay_session_id: str,
        bytes_tx: int = 0,
        bytes_rx: int = 0,
    ) -> bool:
        if not self._device_id:
            return False
        body = {
            "session_id": relay_session_id,
            "bytes_tx": bytes_tx,
            "bytes_rx": bytes_rx,
        }
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/relay/{relay_session_id}/stats",
                json=body,
                headers=self._auth_headers(),
            )
            return resp.status_code == 200
        except httpx.RequestError:
            return False

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
