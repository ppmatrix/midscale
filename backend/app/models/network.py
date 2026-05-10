import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subnet: Mapped[str] = mapped_column(String(18), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    interface_name: Mapped[Optional[str]] = mapped_column(
        String(15), nullable=True, default=None
    )
    topology: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, default=None
    )
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    owner = relationship("User", foreign_keys=[owner_id])
    devices = relationship(
        "Device", back_populates="network", cascade="all, delete-orphan"
    )
    acl_rules = relationship(
        "ACLRule", back_populates="network", cascade="all, delete-orphan"
    )
    dns_entries = relationship(
        "DNSEntry", back_populates="network", cascade="all, delete-orphan"
    )
    preauth_keys = relationship(
        "PreAuthKey", back_populates="network", cascade="all, delete-orphan"
    )
