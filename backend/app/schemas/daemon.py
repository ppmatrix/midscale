"""Schemas for daemon WebSocket and event push."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DaemonWsEvent(BaseModel):
    type: str
    device_id: str
    network_id: str
    revision: str = ""
    reason: str = ""
    timestamp: str = ""


class ConfigChangedEvent(BaseModel):
    type: str = "config.changed"
    device_id: str
    network_id: str
    revision: str
    reason: str
    generated_at: str = ""
