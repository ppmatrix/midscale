import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AuditLogQuery(BaseModel):
    actor_id: Optional[str] = None
    action: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_id: Optional[str]
    actor_type: str
    action: str
    target_type: str
    target_id: Optional[str]
    details: Optional[dict[str, Any]]
    ip_address: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    total: int
    skip: int
    limit: int
