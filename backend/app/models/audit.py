import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """Immutable audit event log.

    Tracks all significant actions in the system for security auditing
    and operational forensics. Entries are append-only — no updates or
    deletions.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user"
    )
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="none"
    )
    target_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, default=dict
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
