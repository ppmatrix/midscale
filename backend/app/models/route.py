import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AdvertisedRoute(Base):
    """Advertised subnet or exit-node route.

    Devices can advertise routes to LAN subnets (e.g. 192.168.1.0/24)
    that other devices in the network can reach through them. Routes
    require explicit admin approval before becoming active.

    Exit node routes (0.0.0.0/0, ::/0) use the same model with
    ``is_exit_node=True`` and are subject to the same approval flow.
    """

    __tablename__ = "advertised_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id"), nullable=False, index=True
    )
    prefix: Mapped[str] = mapped_column(
        String(43), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    approved: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    is_exit_node: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    device = relationship("Device")
    network = relationship("Network")
