"""Daemon service — API surface for the future midscaled client agent.

This module handles daemon-specific operations: heartbeat, endpoint
reporting, and registration. The daemon (midscaled) will be a separate
Linux binary that manages the local WireGuard interface and communicates
with the Midscale control plane via these endpoints.

Architecture:
    midscaled --HTTPS--> Midscale API
        |                       |
        |-- register ---------->| (pre-auth key)
        |-- get config -------->| (device config INI)
        |-- heartbeat --------->| (online status)
        |-- endpoint report --->| (public IP:port)
        |                       |
        |<- WebSocket events ---| (real-time updates)

Registration Flow:
    1. User creates pre-auth key in Midscale UI
    2. Admin provisions device with pre-auth key (e.g., cloud-init)
    3. midscaled starts, registers with pre-auth key
    4. Server allocates IP, generates keys, returns device info
    5. midscaled pulls config and brings up WireGuard interface

Reconciliation Loop (in daemon):
    while True:
        - Pull latest config from API
        - Compare local WireGuard state vs desired
        - Apply diff (add/remove peers, update keys)
        - Report heartbeat
        - Report endpoint (if changed)
        - sleep(interval)

Security Model:
    - Private keys stay client-side after initial generation
    - Server stores encrypted private key (current model)
    - Future: ECDH-based enrollment (key never leaves device)
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.endpoint import DeviceEndpoint

logger = structlog.get_logger(__name__)


async def process_heartbeat(
    session: AsyncSession,
    device_id,
    public_key: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> dict:
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    now = datetime.now(timezone.utc)
    changed = False

    device.last_seen_at = now

    if public_key and public_key != device.public_key:
        device.public_key = public_key
        changed = True

    if ip_address and ip_address != device.ip_address:
        device.ip_address = ip_address
        changed = True

    if changed:
        device.updated_at = now

    await session.flush()

    return {
        "status": "ok",
        "device_id": str(device.id),
        "last_heartbeat": now.isoformat(),
        "config_url": f"/api/v1/devices/{device.id}/config",
    }


async def report_endpoint(
    session: AsyncSession,
    device_id,
    endpoint: str,
    source: str = "handshake",
    port: int = 51820,
    local_ip: Optional[str] = None,
    public_ip: Optional[str] = None,
    priority: int = 100,
) -> dict:
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    now = datetime.now(timezone.utc)

    ep = DeviceEndpoint(
        device_id=device_id,
        endpoint=endpoint,
        source=source,
        port=port,
        local_ip=local_ip,
        public_ip=public_ip,
        priority=priority,
        last_seen=now,
    )
    session.add(ep)
    await session.flush()

    logger.info(
        "endpoint reported",
        device_id=str(device_id),
        device_name=device.name,
        endpoint=endpoint,
        source=source,
        local_ip=local_ip,
        public_ip=public_ip,
        priority=priority,
    )

    return {
        "status": "ok",
        "endpoint_id": str(ep.id),
        "recorded_at": now.isoformat(),
    }


async def stale_endpoint_cleanup(
    session: AsyncSession,
    max_age_minutes: int = 30,
) -> int:
    """Mark endpoints with last_seen older than max_age_minutes as inactive.

    Returns the number of endpoints cleaned up.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    result = await session.execute(
        select(DeviceEndpoint).where(
            DeviceEndpoint.is_active,
            DeviceEndpoint.last_seen < cutoff,
        )
    )
    cleaned = 0
    for ep in result.scalars().all():
        ep.is_active = False
        cleaned += 1
    if cleaned:
        await session.flush()
        logger.info("cleaned stale endpoints", count=cleaned, cutoff=cutoff.isoformat())
    return cleaned
