"""Audit logging service.

Provides async-safe audit event logging with structured schema.
All audit events are immutable append-only records.

Usage:
    from app.services.audit import audit_logger

    await audit_logger.log(
        actor_id=str(user.id),
        actor_type="user",
        action="device.create",
        target_type="device",
        target_id=str(device.id),
        details={"device_name": device.name, "network_id": str(network.id)},
        ip_address=request.client.host,
    )
"""

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.services.metrics import AUDIT_EVENTS

logger = structlog.get_logger(__name__)


class AuditLogger:
    """Async-safe audit event logger.

    Each log() call creates an AuditLog entry in the database.
    The method is fire-and-forget — it does not raise on failure.
    """

    async def log(
        self,
        session: AsyncSession,
        action: str,
        actor_id: Optional[str] = None,
        actor_type: str = "system",
        target_type: str = "none",
        target_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        entry = AuditLog(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc),
        )
        session.add(entry)
        AUDIT_EVENTS.labels(action=action).inc()
        logger.info(
            "audit event",
            action=action,
            actor_type=actor_type,
            target_type=target_type,
            target_id=target_id,
        )


audit_logger = AuditLogger()
