import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PreAuthKeyCreate(BaseModel):
    reusable: bool = False
    expires_in_hours: int = Field(default=24, ge=1, le=8760)


class PreAuthKeyResponse(BaseModel):
    id: uuid.UUID
    key: str
    network_id: uuid.UUID
    reusable: bool
    expires_at: datetime
    created_at: datetime
    used_by: list[str] = []

    model_config = {"from_attributes": True}
