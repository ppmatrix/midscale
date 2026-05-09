import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ACLRuleCreate(BaseModel):
    src_tags: list[str]
    dst_tags: list[str]
    action: str = "allow"
    priority: int = 100


class ACLRuleUpdate(BaseModel):
    src_tags: Optional[list[str]] = None
    dst_tags: Optional[list[str]] = None
    action: Optional[str] = None
    priority: Optional[int] = None


class ACLRuleResponse(BaseModel):
    id: uuid.UUID
    network_id: uuid.UUID
    src_tags: list[str]
    dst_tags: list[str]
    action: str
    priority: int
    created_at: datetime

    model_config = {"from_attributes": True}
