import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class PunchCandidate(BaseModel):
    endpoint: str
    port: int = 51820
    source: str = "reported"
    local_ip: Optional[str] = None
    public_ip: Optional[str] = None
    priority: int = 100


class PunchRequest(BaseModel):
    target_device_id: str
    initiator_endpoint: str
    initiator_port: int = 51820
    initiator_local_ip: Optional[str] = None
    initiator_public_ip: Optional[str] = None


class PunchResult(BaseModel):
    session_id: str
    success: bool
    selected_endpoint: Optional[str] = None
    selected_port: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


class ConnectivityValidationRequest(BaseModel):
    session_id: str
    target_endpoint: str
    target_port: int = 51820
    reachable: bool
    latency_ms: Optional[int] = None


class ConnectivityValidationResponse(BaseModel):
    status: str
    session_id: str
    direct_path_promoted: bool = False
    score: int = 0
    preferred: bool = False


class NATSessionResponse(BaseModel):
    id: uuid.UUID
    initiator_device_id: uuid.UUID
    target_device_id: uuid.UUID
    state: str
    selected_candidate: Optional[dict[str, Any]] = None
    connectivity_established: bool = False
    extra_metadata: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}
