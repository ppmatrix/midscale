"""Relay session coordination API.

Manages DERP-style relay sessions for devices that cannot establish
direct peer-to-peer connectivity after NAT traversal attempts.
"""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.device import Device
from app.api.deps import get_current_device
from app.schemas.relay import (
    RelayCandidate,
    RelaySessionRequest,
    RelaySessionResponse,
    RelayConnectRequest,
    RelayConnectResponse,
    RelayHeartbeat,
    RelayStatsUpdate,
)
from app.services.relay import (
    create_relay_session,
    activate_relay_session,
    expire_relay_session,
    fail_relay_session,
    get_best_relay_candidate,
    update_relay_stats,
    get_relay_session_by_id,
)
from app.services.relay_server import get_relay_server

router = APIRouter(prefix="/relay", tags=["relay"])


def _get_event_bus():
    from app.main import get_event_bus
    return get_event_bus()


@router.get("/candidates", response_model=list[RelayCandidate])
async def get_relay_candidates(
    current_device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Get available relay candidates for the current device."""
    candidate = await get_best_relay_candidate(session, current_device.id)
    if not candidate:
        return []
    return [RelayCandidate(
        relay_node=candidate["relay_node"],
        relay_region=candidate["relay_region"],
        relay_endpoint=candidate["relay_endpoint"],
        priority=candidate["priority"],
        preferred=candidate["preferred"],
    )]


@router.post("/sessions", response_model=RelaySessionResponse, status_code=201)
async def request_relay_session(
    body: RelaySessionRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Request a new relay session to a target device."""
    target_device_id = uuid.UUID(body.target_device_id)
    event_bus = _get_event_bus()

    if current_device.id == target_device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot create relay session to self",
        )

    relay_session = await create_relay_session(
        session=session,
        initiator_device_id=current_device.id,
        target_device_id=target_device_id,
        event_bus=event_bus,
        relay_region=body.relay_region,
    )

    relay_server = get_relay_server()
    if relay_server:
        relay_server.add_valid_token(
            relay_session.relay_token, str(relay_session.id)
        )

    return relay_session


@router.post("/connect", response_model=RelayConnectResponse)
async def connect_relay_session(
    body: RelayConnectRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Connect to an established relay session."""
    event_bus = _get_event_bus()
    relay_session_id = uuid.UUID(body.session_id)

    relay_session = await activate_relay_session(
        session=session,
        relay_session_id=relay_session_id,
        event_bus=event_bus,
    )
    if not relay_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="relay session not found or not pending",
        )

    return RelayConnectResponse(
        status="connected",
        session_id=str(relay_session.id),
        relay_endpoint=f"{relay_session.relay_node}:8765",
        relay_token=relay_session.relay_token,
        relay_node=relay_session.relay_node,
        relay_region=relay_session.relay_region,
    )


@router.get("/sessions/{session_id}", response_model=RelaySessionResponse)
async def get_relay_session(
    session_id: str,
    current_device: Annotated[Device, Depends(get_current_device)],
    db_session: Annotated[AsyncSession, Depends(get_session)],
):
    """Get relay session details."""
    relay_session_id = uuid.UUID(session_id)
    relay_session = await get_relay_session_by_id(db_session, relay_session_id)
    if not relay_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="relay session not found",
        )
    if (
        current_device.id != relay_session.initiator_device_id
        and current_device.id != relay_session.target_device_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not a participant in this session",
        )
    return relay_session


@router.post("/{session_id}/heartbeat", response_model=dict)
async def heartbeat_relay_session(
    session_id: str,
    body: RelayHeartbeat,
    current_device: Annotated[Device, Depends(get_current_device)],
    db_session: Annotated[AsyncSession, Depends(get_session)],
):
    """Send heartbeat for a relay session."""
    relay_session_id = uuid.UUID(session_id)
    event_bus = _get_event_bus()

    relay_session = await get_relay_session_by_id(db_session, relay_session_id)
    if not relay_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="relay session not found",
        )
    if (
        current_device.id != relay_session.initiator_device_id
        and current_device.id != relay_session.target_device_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not a participant in this session",
        )

    relay_server = get_relay_server()
    if relay_server:
        relay_server.update_heartbeat(str(current_device.id), {})

    return {
        "status": "ok",
        "session_id": session_id,
    }


@router.post("/{session_id}/stats", response_model=dict)
async def update_relay_stats_endpoint(
    session_id: str,
    body: RelayStatsUpdate,
    current_device: Annotated[Device, Depends(get_current_device)],
    db_session: Annotated[AsyncSession, Depends(get_session)],
):
    """Update relay session transfer statistics."""
    relay_session_id = uuid.UUID(session_id)
    event_bus = _get_event_bus()

    relay_session = await update_relay_stats(
        session=db_session,
        relay_session_id=relay_session_id,
        bytes_tx=body.bytes_tx,
        bytes_rx=body.bytes_rx,
        event_bus=event_bus,
    )
    if not relay_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="relay session not found",
        )

    return {
        "status": "ok",
        "session_id": session_id,
        "bytes_tx": relay_session.bytes_tx,
        "bytes_rx": relay_session.bytes_rx,
    }
