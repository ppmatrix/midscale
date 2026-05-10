"""NAT traversal coordination API.

Coordinates hole punching sessions between peers for direct
peer-to-peer WireGuard connectivity establishment.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.device import Device
from app.api.deps import get_current_device
from app.schemas.nat import (
    NATSessionResponse,
    PunchRequest,
    PunchResult,
    ConnectivityValidationRequest,
    ConnectivityValidationResponse,
)
from app.services.nat import (
    create_nat_session,
    start_punch,
    build_candidate_pairs,
    record_punch_result,
    validate_connectivity,
    get_session_by_id,
)

router = APIRouter(prefix="/nat", tags=["nat"])


def _get_event_bus():
    from app.main import get_event_bus
    return get_event_bus()


@router.post("/punch", response_model=dict, status_code=201)
async def request_punch(
    body: PunchRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    target_device_id = uuid.UUID(body.target_device_id)
    event_bus = _get_event_bus()

    if current_device.id == target_device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot punch to self",
        )

    nat_session = await create_nat_session(
        session=session,
        initiator_device_id=current_device.id,
        target_device_id=target_device_id,
        event_bus=event_bus,
        extra_metadata={
            "initiator_endpoint": body.initiator_endpoint,
            "initiator_port": body.initiator_port,
        },
    )

    started = await start_punch(
        session=session,
        nat_session_id=nat_session.id,
        event_bus=event_bus,
    )
    if not started:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="session expired or already active",
        )

    candidates = await build_candidate_pairs(
        session=session,
        initiator_device_id=current_device.id,
        target_device_id=target_device_id,
    )

    return {
        "session_id": str(nat_session.id),
        "state": nat_session.state,
        "candidates": candidates,
        "target_device_id": str(target_device_id),
    }


@router.post("/{session_id}/result", response_model=dict)
async def report_punch_result(
    session_id: str,
    body: PunchResult,
    current_device: Annotated[Device, Depends(get_current_device)],
    db_session: Annotated[AsyncSession, Depends(get_session)],
):
    event_bus = _get_event_bus()
    nat_session_id = uuid.UUID(session_id)

    result = await record_punch_result(
        session=db_session,
        nat_session_id=nat_session_id,
        success=body.success,
        selected_endpoint=body.selected_endpoint,
        selected_port=body.selected_port,
        latency_ms=body.latency_ms,
        error=body.error,
        event_bus=event_bus,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NAT session not found",
        )

    return {
        "session_id": session_id,
        "state": result.state,
        "connectivity_established": result.connectivity_established,
    }


@router.post("/{session_id}/validate", response_model=ConnectivityValidationResponse)
async def report_connectivity_validation(
    session_id: str,
    body: ConnectivityValidationRequest,
    current_device: Annotated[Device, Depends(get_current_device)],
    db_session: Annotated[AsyncSession, Depends(get_session)],
):
    event_bus = _get_event_bus()
    nat_session_id = uuid.UUID(session_id)

    result = await validate_connectivity(
        session=db_session,
        nat_session_id=nat_session_id,
        target_endpoint=body.target_endpoint,
        target_port=body.target_port,
        reachable=body.reachable,
        latency_ms=body.latency_ms,
        event_bus=event_bus,
    )
    return ConnectivityValidationResponse(
        status=result["status"],
        session_id=result["session_id"],
        direct_path_promoted=result["direct_path_promoted"],
        score=result["score"],
        preferred=result["preferred"],
    )


@router.get("/{session_id}", response_model=NATSessionResponse)
async def get_session(
    session_id: str,
    current_device: Annotated[Device, Depends(get_current_device)],
    db_session: Annotated[AsyncSession, Depends(get_session)],
):
    nat_session_id = uuid.UUID(session_id)
    nat_session = await get_session_by_id(db_session, nat_session_id)
    if not nat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NAT session not found",
        )
    if (
        current_device.id != nat_session.initiator_device_id
        and current_device.id != nat_session.target_device_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not a participant in this session",
        )
    return nat_session
