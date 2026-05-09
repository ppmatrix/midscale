import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dns_enabled: bool = True
    tags: list[str] = []


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    dns_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    tags: Optional[list[str]] = None
    enrollment_status: Optional[str] = None
    exit_node_id: Optional[uuid.UUID] = None


class DeviceResponse(BaseModel):
    id: uuid.UUID
    name: str
    user_id: Optional[uuid.UUID] = None
    network_id: uuid.UUID
    public_key: Optional[str]
    ip_address: Optional[str]
    dns_enabled: bool
    is_active: bool
    is_node_owned: bool = False
    enrollment_status: str = "active"
    enrolled_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    tags: list[str] = []
    last_handshake: Optional[datetime]
    exit_node_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeviceConfigResponse(BaseModel):
    config: str
    filename: str


class DeviceRegisterRequest(BaseModel):
    key: str
    name: str = Field(min_length=1, max_length=255)


class NodeDeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dns_enabled: bool = True
    tags: list[str] = []


class EnrollRequest(BaseModel):
    public_key: str = Field(min_length=1)
    ip_address: Optional[str] = None


class EnrollResponse(BaseModel):
    device_id: uuid.UUID
    device_token: str
    status: str = "active"


class TokenRotationResponse(BaseModel):
    device_token: str


class EndpointCandidate(BaseModel):
    endpoint: str
    port: int = 51820
    source: str = "reported"
    priority: int = 100
    last_seen_at: Optional[str] = None
    local_ip: Optional[str] = None
    public_ip: Optional[str] = None


class PeerInfo(BaseModel):
    public_key: str
    allowed_ips: list[str] = []
    endpoint: Optional[str] = None
    endpoint_port: Optional[int] = None
    persistent_keepalive: Optional[int] = None
    endpoint_candidates: list[EndpointCandidate] = []
    relay_fallback: bool = False


class DeviceConfigV2Response(BaseModel):
    interface: dict = Field(
        default_factory=lambda: {"address": "", "dns": None, "mtu": None}
    )
    peers: list[PeerInfo] = []
    routes: list[str] = []
    exit_node: Optional[str] = None
    version: str = "2"
    config_version: str = "2"
    schema_version: str = "1"
    min_daemon_version: Optional[str] = None
    revision: str = ""
    generated_at: str = ""
    hash: str = ""


class EnrollByKeyRequest(BaseModel):
    preauth_key: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    public_key: str = Field(min_length=1)
    machine_info: Optional[str] = None
    hostname: Optional[str] = None
    advertised_routes: list[str] = []


class EnrollByKeyResponse(BaseModel):
    device_id: uuid.UUID
    device_token: str
    network_id: uuid.UUID
    ip_address: str
    config_v2: DeviceConfigV2Response


class HeartbeatRequest(BaseModel):
    public_key: Optional[str] = None
    ip_address: Optional[str] = None


class EndpointReport(BaseModel):
    endpoint: str
    source: str = "reported"
    port: int = 51820
    local_ip: Optional[str] = None
    public_ip: Optional[str] = None
