import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RouteAdvertiseRequest(BaseModel):
    prefix: str = Field(
        ..., pattern=r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}|::/0)$"
    )
    is_exit_node: bool = False


class RouteApproveRequest(BaseModel):
    approved: bool = True
    enabled: bool = True


class RouteUpdateRequest(BaseModel):
    enabled: Optional[bool] = None


class RouteResponse(BaseModel):
    id: uuid.UUID
    device_id: uuid.UUID
    network_id: uuid.UUID
    prefix: str
    enabled: bool
    approved: bool
    is_exit_node: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExitNodeSelectRequest(BaseModel):
    exit_node_id: Optional[uuid.UUID] = None
