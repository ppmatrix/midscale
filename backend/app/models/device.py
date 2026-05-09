import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id"), nullable=False
    )
    public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    private_key_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    dns_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_node_owned: Mapped[bool] = mapped_column(Boolean, default=False)
    device_token_hash: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    device_token_prefix: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, index=True
    )
    enrollment_status: Mapped[str] = mapped_column(
        String(20), default="active"
    )
    enrolled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    last_handshake: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exit_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="devices")
    network = relationship("Network", back_populates="devices")
