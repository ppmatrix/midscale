"""Event type constants and base event dataclass.

All event types used across the platform are defined here.
The string constants are defined in app.core.constants for a single
source of truth; this module re-exports them for backward compatibility.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from app.core.constants import (
    EVENT_PEER_SYNCED,
    EVENT_PEER_ADDED,
    EVENT_PEER_REMOVED,
    EVENT_DEVICE_ONLINE,
    EVENT_DEVICE_OFFLINE,
    EVENT_DEVICE_ENROLLED,
    EVENT_DEVICE_REVOKED,
    EVENT_DEVICE_HEARTBEAT,
    EVENT_DNS_UPDATED,
    EVENT_NETWORK_CREATED,
    EVENT_NETWORK_CHANGED,
    EVENT_NETWORK_DELETED,
    EVENT_CONFIG_CHANGED,
    EVENT_ENDPOINT_REPORTED,
    EVENT_ENDPOINT_STALE,
    EVENT_ROUTE_CHANGED,
    EVENT_ACL_CHANGED,
    EVENT_CHANNEL_PREFIX,
)

# Re-export constants for backward compatibility
__all__ = [
    "EVENT_PEER_SYNCED",
    "EVENT_PEER_ADDED",
    "EVENT_PEER_REMOVED",
    "EVENT_DEVICE_ONLINE",
    "EVENT_DEVICE_OFFLINE",
    "EVENT_DEVICE_ENROLLED",
    "EVENT_DEVICE_REVOKED",
    "EVENT_DEVICE_HEARTBEAT",
    "EVENT_DNS_UPDATED",
    "EVENT_NETWORK_CREATED",
    "EVENT_NETWORK_CHANGED",
    "EVENT_NETWORK_DELETED",
    "EVENT_CONFIG_CHANGED",
    "EVENT_ENDPOINT_REPORTED",
    "EVENT_ENDPOINT_STALE",
    "EVENT_ENDPOINT_PROBE",
    "EVENT_ROUTE_CHANGED",
    "EVENT_ACL_CHANGED",
    "Event",
    "ConfigChangedPayload",
    "event_channel",
    "wildcard_channel",
]

CONFIG_CHANGED = EVENT_CONFIG_CHANGED  # most commonly used alias


def event_channel(event_type: str) -> str:
    return f"{EVENT_CHANNEL_PREFIX}:{event_type}"


def wildcard_channel() -> str:
    return f"{EVENT_CHANNEL_PREFIX}:*"


@dataclass
class Event:
    """Base event with type, data payload, unique id, and timestamp."""

    event_type: str
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "type": self.event_type,
            "created_at": self.created_at,
            "data": self.data,
        }

    def channel(self) -> str:
        return event_channel(self.event_type)


@dataclass
class ConfigChangedPayload:
    """Typed payload for config.changed events."""

    device_id: Optional[str] = None
    network_id: str = ""
    revision: Optional[str] = None
    hash: Optional[str] = None
    reason: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "network_id": self.network_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
        if self.device_id:
            d["device_id"] = self.device_id
        if self.revision:
            d["revision"] = self.revision
        if self.hash:
            d["hash"] = self.hash
        return d
