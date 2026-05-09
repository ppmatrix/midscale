import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subnet: str = Field(
        ..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$"
    )
    description: Optional[str] = None
    interface_name: Optional[str] = Field(
        default=None, max_length=15, pattern=r"^[a-zA-Z0-9_\-]+$"
    )


class NetworkUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    interface_name: Optional[str] = Field(
        default=None, max_length=15, pattern=r"^[a-zA-Z0-9_\-]+$"
    )
    topology: Optional[str] = Field(
        default=None, max_length=10, pattern=r"^(star|mesh|hybrid)?$"
    )


class NetworkResponse(BaseModel):
    id: uuid.UUID
    name: str
    subnet: str
    description: Optional[str]
    interface_name: Optional[str]
    topology: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
