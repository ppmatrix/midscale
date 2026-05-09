import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PreAuthKey(Base):
    __tablename__ = "preauth_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id"), nullable=False
    )
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    used_by: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)

    network = relationship("Network", back_populates="preauth_keys")
