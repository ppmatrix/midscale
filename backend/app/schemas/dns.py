import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DNSEntryCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=255)
    address: str = Field(
        ..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    )


class DNSEntryResponse(BaseModel):
    id: uuid.UUID
    network_id: uuid.UUID
    domain: str
    address: str
    created_at: datetime

    model_config = {"from_attributes": True}
