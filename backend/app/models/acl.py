import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ACLRule(Base):
    __tablename__ = "acl_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id"), nullable=False
    )
    src_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dst_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    action: Mapped[str] = mapped_column(String(10), default="allow")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    network = relationship("Network", back_populates="acl_rules")
