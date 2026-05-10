import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class RelayCandidate(BaseModel):
    relay_node: str
    relay_region: str
    relay_endpoint: str
    priority: int = 100
    preferred: bool = False
    latency_ms: Optional[int] = None


class RelaySessionRequest(BaseModel):
    target_device_id: str
    relay_region: str = "default"


class RelaySessionResponse(BaseModel):
    id: uuid.UUID
    initiator_device_id: uuid.UUID
    target_device_id: uuid.UUID
    relay_region: str
    relay_node: str
    relay_token: str
    state: str
    bytes_tx: int = 0
    bytes_rx: int = 0
    connected_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RelayConnectRequest(BaseModel):
    session_id: str


class RelayConnectResponse(BaseModel):
    status: str
    session_id: str
    relay_endpoint: str
    relay_token: str
    relay_node: str
    relay_region: str


class RelayHeartbeat(BaseModel):
    session_id: str
    state: Optional[str] = None


class RelayStatsUpdate(BaseModel):
    session_id: str
    bytes_tx: int = 0
    bytes_rx: int = 0
