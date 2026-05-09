import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DeviceEndpoint(Base):
    """Tracks known endpoints for WireGuard peers.

    In a mesh network, devices need to know each other's public endpoints
    to establish direct peer-to-peer connections. This model stores
    endpoint observations from various sources:
    - local: discovered from local network interface
    - reported: reported by the device itself
    - observed: observed by the server via handshake
    - stun: discovered via STUN server (future)
    - derp: relayed via DERP relay (future)

    Each device can have multiple endpoint candidates with different
    priorities. The highest-priority active endpoint is used in config
    generation for mesh and hybrid topologies.
    """

    __tablename__ = "device_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="reported"
    )
    port: Mapped[int] = mapped_column(Integer, default=51820)
    local_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    public_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
