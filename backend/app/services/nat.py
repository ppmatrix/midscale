"""NAT traversal coordination service.

Manages hole punching sessions between peers, coordinates candidate
exchange, and promotes direct paths when connectivity is validated.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.endpoint import DeviceEndpoint
from app.models.nat_session import NATSession
from app.services.endpoint_scoring import compute_endpoint_score, select_best_endpoint
from app.services.event_bus import EventBus
from app.services.event_types import Event
from app.core.constants import (
    EVENT_NAT_PUNCH_REQUESTED,
    EVENT_NAT_PUNCH_STARTED,
    EVENT_NAT_PUNCH_SUCCEEDED,
    EVENT_NAT_PUNCH_FAILED,
    EVENT_NAT_CONNECTIVITY_VALIDATED,
    EVENT_CONFIG_CHANGED,
)
from app.services.metrics import (
    NAT_PUNCH_TOTAL,
    NAT_CONNECTIVITY_TOTAL,
    NAT_SESSION_ACTIVE,
    NAT_PUNCH_DURATION,
)
from app.services.relay import auto_create_relay_fallback
from app.core.constants import EVENT_RELAY_FALLBACK

SESSION_TIMEOUT_MINUTES = 5
CLEANUP_INTERVAL_SECONDS = 120
STALE_ENDPOINT_CUTOFF_MINUTES = 30


async def create_nat_session(
    session: AsyncSession,
    initiator_device_id: uuid.UUID,
    target_device_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
    extra_metadata: Optional[dict] = None,
) -> NATSession:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    nat_session = NATSession(
        id=uuid.uuid4(),
        initiator_device_id=initiator_device_id,
        target_device_id=target_device_id,
        state="pending",
        connectivity_established=False,
        extra_metadata=extra_metadata or {},
        expires_at=expires_at,
    )
    session.add(nat_session)
    await session.commit()
    await session.refresh(nat_session)

    NAT_SESSION_ACTIVE.inc()

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_NAT_PUNCH_REQUESTED,
                data={
                    "session_id": str(nat_session.id),
                    "initiator_device_id": str(initiator_device_id),
                    "target_device_id": str(target_device_id),
                },
            )
        )

    return nat_session


async def start_punch(
    session: AsyncSession,
    nat_session_id: uuid.UUID,
    event_bus: Optional[EventBus] = None,
) -> Optional[NATSession]:
    result = await session.execute(
        select(NATSession).where(
            NATSession.id == nat_session_id,
            NATSession.state == "pending",
            NATSession.expires_at > datetime.now(timezone.utc),
        )
    )
    nat_session = result.scalar_one_or_none()
    if not nat_session:
        return None

    nat_session.state = "coordinating"
    nat_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(nat_session)

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_NAT_PUNCH_STARTED,
                data={
                    "session_id": str(nat_session.id),
                    "initiator_device_id": str(nat_session.initiator_device_id),
                    "target_device_id": str(nat_session.target_device_id),
                },
            )
        )

    return nat_session


async def get_active_endpoints_by_device(
    session: AsyncSession, device_id: uuid.UUID
) -> list[DeviceEndpoint]:
    result = await session.execute(
        select(DeviceEndpoint).where(
            DeviceEndpoint.device_id == device_id,
            DeviceEndpoint.is_active == True,  # noqa: E712
        ).order_by(DeviceEndpoint.score.desc())
    )
    return list(result.scalars().all())


async def build_candidate_pairs(
    session: AsyncSession,
    initiator_device_id: uuid.UUID,
    target_device_id: uuid.UUID,
) -> list[dict[str, Any]]:
    initiator_endpoints = await get_active_endpoints_by_device(session, initiator_device_id)
    target_endpoints = await get_active_endpoints_by_device(session, target_device_id)

    pairs = []
    for ie in initiator_endpoints:
        for te in target_endpoints:
            pairs.append({
                "initiator": {
                    "endpoint": ie.endpoint,
                    "port": ie.port,
                    "source": ie.source,
                    "local_ip": ie.local_ip,
                    "public_ip": ie.public_ip,
                    "priority": ie.priority,
                },
                "target": {
                    "endpoint": te.endpoint,
                    "port": te.port,
                    "source": te.source,
                    "local_ip": te.local_ip,
                    "public_ip": te.public_ip,
                    "priority": te.priority,
                },
                "pair_key": f"{ie.endpoint}:{ie.port}->{te.endpoint}:{te.port}",
            })
    return pairs


async def record_punch_result(
    session: AsyncSession,
    nat_session_id: uuid.UUID,
    success: bool,
    selected_endpoint: Optional[str] = None,
    selected_port: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error: Optional[str] = None,
    event_bus: Optional[EventBus] = None,
) -> Optional[NATSession]:
    result = await session.execute(
        select(NATSession).where(NATSession.id == nat_session_id)
    )
    nat_session = result.scalar_one_or_none()
    if not nat_session:
        return None

    if success:
        nat_session.state = "connected"
        nat_session.connectivity_established = True
        nat_session.selected_candidate = {
            "endpoint": selected_endpoint,
            "port": selected_port,
            "latency_ms": latency_ms,
        }
        NAT_PUNCH_TOTAL.labels(result="success").inc()

        if event_bus:
            await event_bus.publish(
                Event(
                    event_type=EVENT_NAT_PUNCH_SUCCEEDED,
                    data={
                        "session_id": str(nat_session.id),
                        "initiator_device_id": str(nat_session.initiator_device_id),
                        "target_device_id": str(nat_session.target_device_id),
                        "selected_endpoint": selected_endpoint,
                        "selected_port": selected_port,
                        "latency_ms": latency_ms,
                    },
                )
            )

        if selected_endpoint and selected_port:
            await _promote_endpoint(
                session=session,
                device_id=nat_session.target_device_id,
                endpoint=selected_endpoint,
                port=selected_port,
                latency_ms=latency_ms,
            )

            await _publish_config_changed(
                session=session,
                nat_session=nat_session,
                event_bus=event_bus,
            )
    else:
        nat_session.state = "failed"
        if nat_session.extra_metadata is None:
            nat_session.extra_metadata = {}
        nat_session.extra_metadata["error"] = error
        nat_session.extra_metadata["failure_count"] = nat_session.extra_metadata.get("failure_count", 0) + 1
        NAT_PUNCH_TOTAL.labels(result="failed").inc()

        if event_bus:
            await event_bus.publish(
                Event(
                    event_type=EVENT_NAT_PUNCH_FAILED,
                    data={
                        "session_id": str(nat_session.id),
                        "initiator_device_id": str(nat_session.initiator_device_id),
                        "target_device_id": str(nat_session.target_device_id),
                        "error": error,
                    },
                )
            )

        if nat_session.extra_metadata.get("failure_count", 0) >= 2:
            relay_session = await auto_create_relay_fallback(
                session=session,
                initiator_device_id=nat_session.initiator_device_id,
                target_device_id=nat_session.target_device_id,
                event_bus=event_bus,
            )
            if relay_session and event_bus:
                from app.services.relay_server import get_relay_server
                relay_server = get_relay_server()
                if relay_server:
                    relay_server.add_valid_token(
                        relay_session.relay_token, str(relay_session.id)
                    )
                await event_bus.publish(
                    Event(
                        event_type=EVENT_RELAY_FALLBACK,
                        data={
                            "nat_session_id": str(nat_session.id),
                            "relay_session_id": str(relay_session.id),
                            "initiator_device_id": str(nat_session.initiator_device_id),
                            "target_device_id": str(nat_session.target_device_id),
                        },
                    )
                )

    nat_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(nat_session)
    return nat_session


async def validate_connectivity(
    session: AsyncSession,
    nat_session_id: uuid.UUID,
    target_endpoint: str,
    target_port: int,
    reachable: bool,
    latency_ms: Optional[int] = None,
    event_bus: Optional[EventBus] = None,
) -> dict[str, Any]:
    result = await session.execute(
        select(NATSession).where(NATSession.id == nat_session_id)
    )
    nat_session = result.scalar_one_or_none()

    direct_path_promoted = False
    score = 0
    preferred = False

    if not nat_session:
        NAT_CONNECTIVITY_TOTAL.labels(result="failed").inc()
        return {
            "status": "session_not_found",
            "session_id": str(nat_session_id),
            "direct_path_promoted": False,
            "score": 0,
            "preferred": False,
        }

    if reachable:
        nat_session.connectivity_established = True
        nat_session.selected_candidate = {
            "endpoint": target_endpoint,
            "port": target_port,
            "latency_ms": latency_ms,
        }
        if nat_session.state != "connected":
            nat_session.state = "connected"
        direct_path_promoted = True

        promoted = await _promote_endpoint(
            session=session,
            device_id=nat_session.target_device_id,
            endpoint=target_endpoint,
            port=target_port,
            latency_ms=latency_ms,
        )
        score = promoted.get("score", 0)
        preferred = promoted.get("preferred", False)

        await _publish_config_changed(
            session=session,
            nat_session=nat_session,
            event_bus=event_bus,
        )

        NAT_CONNECTIVITY_TOTAL.labels(result="success").inc()
    else:
        NAT_CONNECTIVITY_TOTAL.labels(result="failed").inc()

    nat_session.updated_at = datetime.now(timezone.utc)
    await session.commit()

    if event_bus:
        await event_bus.publish(
            Event(
                event_type=EVENT_NAT_CONNECTIVITY_VALIDATED,
                data={
                    "session_id": str(nat_session.id),
                    "initiator_device_id": str(nat_session.initiator_device_id),
                    "target_device_id": str(nat_session.target_device_id),
                    "reachable": reachable,
                    "target_endpoint": target_endpoint,
                    "target_port": target_port,
                    "latency_ms": latency_ms,
                    "direct_path_promoted": direct_path_promoted,
                },
            )
        )

    return {
        "status": "connected" if reachable else "failed",
        "session_id": str(nat_session_id),
        "direct_path_promoted": direct_path_promoted,
        "score": score,
        "preferred": preferred,
    }


async def _promote_endpoint(
    session: AsyncSession,
    device_id: uuid.UUID,
    endpoint: str,
    port: int,
    latency_ms: Optional[int] = None,
) -> dict[str, Any]:
    result = await session.execute(
        select(DeviceEndpoint).where(
            DeviceEndpoint.device_id == device_id,
            DeviceEndpoint.endpoint == endpoint,
            DeviceEndpoint.port == port,
            DeviceEndpoint.is_active == True,  # noqa: E712
        )
    )
    ep = result.scalar_one_or_none()

    if not ep:
        return {"score": 0, "preferred": False}

    ep.success_count = (ep.success_count or 0) + 1
    ep.reachable = True
    if latency_ms is not None:
        ep.latency_ms = latency_ms
    if ep.score == 0:
        ep.score = compute_endpoint_score(
            reachable=True,
            latency_ms=latency_ms,
            success_count=ep.success_count,
            failure_count=ep.failure_count or 0,
            priority=ep.priority,
        )
    else:
        ep.score = min(ep.score + 30, 200)

    ep.last_probe_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(ep)

    from app.services.metrics import ENDPOINT_SCORE_UPDATES
    ENDPOINT_SCORE_UPDATES.inc()

    ep_list = await get_active_endpoints_by_device(session, device_id)
    best = select_best_endpoint(ep_list) if ep_list else None
    preferred = best is not None and best.id == ep.id

    if preferred:
        for other in ep_list:
            if other.id != ep.id:
                other.is_active = False
        await session.commit()

    return {"score": ep.score, "preferred": preferred}


async def _publish_config_changed(
    session: AsyncSession,
    nat_session: NATSession,
    event_bus: Optional[EventBus] = None,
) -> None:
    if not event_bus:
        return

    from app.services.wireguard import build_config_v2
    from sqlalchemy import select
    from app.models.device import Device

    for device_id in (nat_session.initiator_device_id, nat_session.target_device_id):
        dev_result = await session.execute(
            select(Device).where(Device.id == device_id)
        )
        device = dev_result.scalar_one_or_none()
        if not device:
            continue

        try:
            config = await build_config_v2(session, device)
            from app.services.event_types import ConfigChangedPayload
            payload = ConfigChangedPayload(
                device_id=str(device_id),
                network_id=str(device.network_id),
                revision=config.get("revision", ""),
                hash=config.get("hash", ""),
                reason=f"nat_punch_successful:{nat_session.id}",
            )
            await event_bus.publish(
                Event(
                    event_type=EVENT_CONFIG_CHANGED,
                    data=payload.to_dict(),
                )
            )
        except Exception:
            pass


async def expire_stale_sessions(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(NATSession).where(
            NATSession.state.in_(["pending", "coordinating", "punching"]),
            NATSession.expires_at <= now,
        )
    )
    stale = list(result.scalars().all())
    for s in stale:
        s.state = "expired"
        s.updated_at = now
    await session.commit()
    if stale:
        NAT_SESSION_ACTIVE.dec(len(stale))
    return len(stale)


async def get_session_by_id(
    session: AsyncSession, nat_session_id: uuid.UUID
) -> Optional[NATSession]:
    result = await session.execute(
        select(NATSession).where(NATSession.id == nat_session_id)
    )
    return result.scalar_one_or_none()
