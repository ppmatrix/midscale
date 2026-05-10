from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class DaemonState:
    registered: bool = False
    enrolled: bool = False
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    network_id: Optional[str] = None
    interface_name: str = "midscale0"
    last_handshake: Optional[datetime] = None
    last_config_fetch: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    last_endpoint_report: Optional[datetime] = None
    current_endpoint: Optional[str] = None
    reconfigure_count: int = 0
    error_count: int = 0
    last_config_hash: Optional[str] = None
    last_config_revision: Optional[str] = None


@dataclass
class RegistrationResult:
    success: bool
    device_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class EnrollResult:
    success: bool
    device_id: Optional[str] = None
    device_token: Optional[str] = None
    network_id: Optional[str] = None
    ip_address: Optional[str] = None
    config_v2: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class ConfigPullResult:
    success: bool
    config_ini: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ConfigV2PullResult:
    success: bool
    interface: Optional[dict[str, Any]] = None
    peers: Optional[list[dict[str, Any]]] = None
    routes: Optional[list[str]] = None
    exit_node: Optional[str] = None
    revision: Optional[str] = None
    hash: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None


@dataclass
class HeartbeatResult:
    success: bool
    error: Optional[str] = None


@dataclass
class EndpointReportResult:
    success: bool
    error: Optional[str] = None


@dataclass
class ProbeReportResult:
    success: bool
    error: Optional[str] = None


@dataclass
class RouteAdvertiseResult:
    success: bool
    error: Optional[str] = None


@dataclass
class RelaySessionResult:
    success: bool
    session_id: Optional[str] = None
    relay_token: Optional[str] = None
    relay_region: Optional[str] = None
    relay_node: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PeerState:
    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    endpoint: Optional[str] = None
    latest_handshake: Optional[datetime] = None
    transfer_rx: int = 0
    transfer_tx: int = 0


@dataclass
class InterfaceState:
    name: str
    public_key: Optional[str] = None
    listen_port: int = 51820
    peers: list[PeerState] = field(default_factory=list)


@dataclass
class DesiredPeer:
    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    endpoint: Optional[str] = None
    endpoint_port: Optional[int] = None
    persistent_keepalive: Optional[int] = None
    relay_required: bool = False
    relay_candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DesiredConfig:
    private_key: str
    address: str
    subnet: str
    listen_port: Optional[int] = None
    dns_servers: Optional[list[str]] = None
    peers: list[DesiredPeer] = field(default_factory=list)
    mtu: Optional[int] = None
