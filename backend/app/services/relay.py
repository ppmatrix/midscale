"""Relay session coordination service.

Manages DERP-style relay sessions for devices that cannot establish
direct peer-to-peer connectivity after NAT traversal attempts.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.relay_session import RelaySession
from app.services.event_bus import EventBus
from app.services.event_types import Event
from app.core.constants import (
    EVENT_RELAY_REQUESTED,
    EVENT_RELAY_CONNECTED,
    EVENT_RELAY_FAILED,
    EVENT_RELAY_EXPIRED,
    EVENT_RELAY_STATS_UPDATED,
    EVENT_CONFIG_CHANGED,
)
from app.services.metrics import (
    RELAY_SESSIONS_TOTAL,
    RELAY_CONNECTIONS_ACTIVE,
    RELAY_FALLBACK_TOTAL,
)

RELAY_DEFAULT_REGION = "default"
RELAY_DEFAULT_NODE = "relay0"
RELAY_SESSION_TIMEOUT_HOURS = 24
RELAY_TOKEN_BYTES = 32


async def create_relay_session(
    session: AsyncSession,
    initiator_device_id: uuid.UUID,
    target_device_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
    relay_region: str = RELAY_DEFAULT_REGION,
    relay_node: str = RELAY_DEFAULT_NODE,
) -> RelaySession:
    relay_token = secrets.token_urlsafe(RELAY_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=RELAY_SESSION_TIMEOUT_HOURS)

    relay_session = RelaySession(
        id=uuid.uuid4(),
        initiator_device_id=initiator_device_id,
        target_device_id=target_device_id,
        relay_region=relay_region,
        relay_node=relay_node,
        relay_token=relay_token,
        state="pending",
        expires_at=expires_at,
    )
    session.add(relay_session)
    await session.commit()
    await session.refresh(relay_session)

    RELAY_SESSIONS_TOTAL.labels(state="pending").inc()

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_RELAY_REQUESTED,
                data={
                    "session_id": str(relay_session.id),
                    "initiator_device_id": str(initiator_device_id),
                    "target_device_id": str(target_device_id),
                    "relay_region": relay_region,
                    "relay_node": relay_node,
                },
            )
        )

    return relay_session


async def activate_relay_session(
    session: AsyncSession,
    relay_session_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
) -> Optional[RelaySession]:
    result = await session.execute(
        select(RelaySession).where(
            RelaySession.id == relay_session_id,
            RelaySession.state == "pending",
        )
    )
    relay_session = result.scalar_one_or_none()
    if not relay_session:
        return None

    relay_session.state = "active"
    relay_session.connected_at = datetime.now(timezone.utc)
    relay_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(relay_session)

    RELAY_CONNECTIONS_ACTIVE.inc()
    RELAY_SESSIONS_TOTAL.labels(state="active").inc()

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_RELAY_CONNECTED,
                data={
                    "session_id": str(relay_session.id),
                    "initiator_device_id": str(relay_session.initiator_device_id),
                    "target_device_id": str(relay_session.target_device_id),
                    "relay_node": relay_session.relay_node,
                },
            )
        )

    return relay_session


async def expire_relay_session(
    session: AsyncSession,
    relay_session_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
) -> Optional[RelaySession]:
    result = await session.execute(
        select(RelaySession).where(RelaySession.id == relay_session_id)
    )
    relay_session = result.scalar_one_or_none()
    if not relay_session:
        return None

    was_active = relay_session.state == "active"
    relay_session.state = "expired"
    relay_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(relay_session)

    if was_active:
        RELAY_CONNECTIONS_ACTIVE.dec()

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_RELAY_EXPIRED,
                data={
                    "session_id": str(relay_session.id),
                    "initiator_device_id": str(relay_session.initiator_device_id),
                    "target_device_id": str(relay_session.target_device_id),
                },
            )
        )

    return relay_session


async def fail_relay_session(
    session: AsyncSession,
    relay_session_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
) -> Optional[RelaySession]:
    result = await session.execute(
        select(RelaySession).where(RelaySession.id == relay_session_id)
    )
    relay_session = result.scalar_one_or_none()
    if not relay_session:
        return None

    was_active = relay_session.state == "active"
    relay_session.state = "failed"
    relay_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(relay_session)

    if was_active:
        RELAY_CONNECTIONS_ACTIVE.dec()

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_RELAY_FAILED,
                data={
                    "session_id": str(relay_session.id),
                    "initiator_device_id": str(relay_session.initiator_device_id),
                    "target_device_id": str(relay_session.target_device_id),
                },
            )
        )

    return relay_session


async def get_best_relay_candidate(
    session: AsyncSession,
    device_id: uuid.UUID,
) -> Optional[dict]:
    """Get the best active relay node for a device.

    Currently returns a static default relay candidate.
    Future: multi-region relay selection with latency-based routing.
    """
    from app.config import settings

    relay_host = getattr(settings, "relay_host", "127.0.0.1")
    relay_port = getattr(settings, "relay_port", 8765)

    return {
        "relay_node": RELAY_DEFAULT_NODE,
        "relay_region": RELAY_DEFAULT_REGION,
        "relay_endpoint": f"{relay_host}:{relay_port}",
        "priority": 50,
        "preferred": True,
    }


async def update_relay_stats(
    session: AsyncSession,
    relay_session_id: uuid.UUID,
    bytes_tx: int = 0,
    bytes_rx: int = 0,
    event_bus: Optional[EventBus] = None,
) -> Optional[RelaySession]:
    result = await session.execute(
        select(RelaySession).where(RelaySession.id == relay_session_id)
    )
    relay_session = result.scalar_one_or_none()
    if not relay_session:
        return None

    relay_session.bytes_tx = (relay_session.bytes_tx or 0) + bytes_tx
    relay_session.bytes_rx = (relay_session.bytes_rx or 0) + bytes_rx
    relay_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(relay_session)

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_RELAY_STATS_UPDATED,
                data={
                    "session_id": str(relay_session.id),
                    "bytes_tx": relay_session.bytes_tx,
                    "bytes_rx": relay_session.bytes_rx,
                },
            )
        )

    return relay_session


async def cleanup_expired_relays(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(RelaySession).where(
            RelaySession.state.in_(["pending", "active"]),
            RelaySession.expires_at <= now,
        )
    )
    stale = list(result.scalars().all())
    active_count = sum(1 for s in stale if s.state == "active")
    for s in stale:
        s.state = "expired"
        s.updated_at = now
    await session.commit()
    if active_count:
        RELAY_CONNECTIONS_ACTIVE.dec(active_count)
    if stale:
        RELAY_SESSIONS_TOTAL.labels(state="expired").inc(len(stale))
    return len(stale)


async def get_relay_session_by_id(
    session: AsyncSession, relay_session_id: uuid.UUID
) -> Optional[RelaySession]:
    result = await session.execute(
        select(RelaySession).where(RelaySession.id == relay_session_id)
    )
    return result.scalar_one_or_none()


async def auto_create_relay_fallback(
    session: AsyncSession,
    initiator_device_id: uuid.UUID,
    target_device_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
) -> Optional[RelaySession]:
    """Auto-create a relay session after NAT punch failure.

    Publishes relay fallback event and increments fallback metric.
    """
    relay_session = await create_relay_session(
        session=session,
        initiator_device_id=initiator_device_id,
        target_device_id=target_device_id,
        event_bus=event_bus,
    )

    RELAY_FALLBACK_TOTAL.inc()

    return relay_session
