"""Subnet route and exit node advertisement API.

Devices can advertise routes to LAN subnets. Exit nodes are a special
case of route advertisement with ``is_exit_node=True`` and prefix
0.0.0.0/0.

All routes require explicit admin approval before becoming active.
Approved routes are included in peer AllowedIPs during config generation.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user, get_current_device_by_id, require_network_owner
from app.models.user import User
from app.models.device import Device
from app.models.network import Network
from app.models.route import AdvertisedRoute
from app.schemas.route import (
    RouteAdvertiseRequest,
    RouteApproveRequest,
    RouteUpdateRequest,
    RouteResponse,
    ExitNodeSelectRequest,
)
from app.services.audit import audit_logger
from app.services.metrics import ROUTES_TOTAL, ROUTES_APPROVED, EXIT_NODES_TOTAL
from app.services import route_validation

router = APIRouter(prefix="/routes", tags=["routes"])


async def _overlaps_with_existing(
    session: AsyncSession,
    network_id: uuid.UUID,
    device_id: uuid.UUID,
    prefix: str,
    exclude_id: uuid.UUID | None = None,
) -> list[AdvertisedRoute]:
    """Check if ``prefix`` overlaps any existing approved route."""
    query = select(AdvertisedRoute).where(
        AdvertisedRoute.network_id == network_id,
        AdvertisedRoute.prefix == prefix,
    )
    if exclude_id is not None:
        query = query.where(AdvertisedRoute.id != exclude_id)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/networks/{network_id}", response_model=list[RouteResponse])
async def list_routes(
    network_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(AdvertisedRoute)
        .where(AdvertisedRoute.network_id == network_id)
        .order_by(AdvertisedRoute.created_at.desc())
    )
    return result.scalars().all()


@router.get("/devices/{device_id}", response_model=list[RouteResponse])
async def list_device_routes(
    device_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    dev_result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = dev_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await require_network_owner(session, device.network_id, current_user)
    result = await session.execute(
        select(AdvertisedRoute)
        .where(AdvertisedRoute.device_id == device_id)
        .order_by(AdvertisedRoute.created_at.desc())
    )
    return result.scalars().all()


@router.post("/networks/{network_id}/advertise", response_model=RouteResponse, status_code=201)
async def advertise_route(
    network_id: uuid.UUID,
    req: RouteAdvertiseRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status

    network = await require_network_owner(session, network_id, current_user)

    dev_result = await session.execute(
        select(Device).where(
            Device.user_id == current_user.id,
            Device.network_id == network_id,
        )
    )
    devices = dev_result.scalars().all()
    if not devices:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have no devices in this network")

    device_id = devices[0].id

    route_validation.check_safe_prefix(req.prefix, req.is_exit_node)

    overlaps = await _overlaps_with_existing(session, network_id, device_id, req.prefix)
    if overlaps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Route {req.prefix} already advertised by another device",
        )

    route = AdvertisedRoute(
        device_id=device_id,
        network_id=network_id,
        prefix=req.prefix,
        is_exit_node=req.is_exit_node,
    )
    session.add(route)
    await session.flush()

    ROUTES_TOTAL.inc()
    if req.is_exit_node:
        EXIT_NODES_TOTAL.inc()

    await audit_logger.log(
        session=session,
        action="route.advertise",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="route",
        target_id=str(route.id),
        details={
            "device_id": str(device_id),
            "network_id": str(network_id),
            "prefix": req.prefix,
            "is_exit_node": req.is_exit_node,
        },
        ip_address=request.client.host if request.client else None,
    )
    return route


@router.post("/{route_id}/approve", response_model=RouteResponse)
async def approve_route(
    route_id: uuid.UUID,
    req: RouteApproveRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status

    result = await session.execute(
        select(AdvertisedRoute).where(AdvertisedRoute.id == route_id)
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    await require_network_owner(session, route.network_id, current_user)

    was_approved = route.approved
    route.approved = req.approved
    route.enabled = req.enabled
    route.updated_at = datetime.now(timezone.utc)
    await session.flush()

    if req.approved and not was_approved:
        ROUTES_APPROVED.inc()

    await audit_logger.log(
        session=session,
        action="route.approve",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="route",
        target_id=str(route_id),
        details={
            "approved": req.approved,
            "enabled": req.enabled,
            "prefix": route.prefix,
            "is_exit_node": route.is_exit_node,
        },
        ip_address=request.client.host if request.client else None,
    )
    return route


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: uuid.UUID,
    req: RouteUpdateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status

    result = await session.execute(
        select(AdvertisedRoute).where(AdvertisedRoute.id == route_id)
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    await require_network_owner(session, route.network_id, current_user)

    if req.enabled is not None:
        route.enabled = req.enabled
    route.updated_at = datetime.now(timezone.utc)
    await session.flush()

    await audit_logger.log(
        session=session,
        action="route.update",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="route",
        target_id=str(route_id),
        details={"enabled": req.enabled, "prefix": route.prefix},
        ip_address=request.client.host if request.client else None,
    )
    return route


@router.delete("/{route_id}", status_code=204)
async def delete_route(
    route_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status

    result = await session.execute(
        select(AdvertisedRoute).where(AdvertisedRoute.id == route_id)
    )
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    await require_network_owner(session, route.network_id, current_user)

    await audit_logger.log(
        session=session,
        action="route.delete",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="route",
        target_id=str(route_id),
        details={"prefix": route.prefix, "is_exit_node": route.is_exit_node},
        ip_address=request.client.host if request.client else None,
    )

    if route.is_exit_node:
        EXIT_NODES_TOTAL.dec()
    ROUTES_TOTAL.dec()

    await session.delete(route)
    await session.flush()


@router.post("/devices/{device_id}/exit-node", response_model=RouteResponse)
async def select_exit_node(
    device_id: uuid.UUID,
    req: ExitNodeSelectRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Select or deselect an exit node for a device."""
    from fastapi import HTTPException, status, Body

    result = await session.execute(
        select(Device).where(
            Device.id == device_id,
            Device.user_id == current_user.id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    if req.exit_node_id is not None:
        exit_result = await session.execute(
            select(AdvertisedRoute).where(
                AdvertisedRoute.device_id == req.exit_node_id,
                AdvertisedRoute.is_exit_node,
                AdvertisedRoute.approved,
                AdvertisedRoute.enabled,
                AdvertisedRoute.network_id == device.network_id,
            )
        )
        exit_route = exit_result.scalar_one_or_none()
        if not exit_route:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified device is not an approved exit node in this network",
            )

    device.exit_node_id = req.exit_node_id
    device.updated_at = datetime.now(timezone.utc)
    await session.flush()

    await audit_logger.log(
        session=session,
        action="device.exit_node_select",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="device",
        target_id=str(device_id),
        details={"exit_node_id": str(req.exit_node_id) if req.exit_node_id else None},
        ip_address=request.client.host if request.client else None,
    )

    result = await session.execute(
        select(AdvertisedRoute).where(
            AdvertisedRoute.device_id == device_id,
            AdvertisedRoute.prefix == "0.0.0.0/0",
        )
    )
    route = result.scalar_one_or_none()
    return route


@router.post("/devices/{device_id}/advertise", response_model=RouteResponse, status_code=201)
async def device_advertise_route(
    device_id: uuid.UUID,
    req: RouteAdvertiseRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_device: Annotated[Device, Depends(get_current_device_by_id)],
):
    """Device-authenticated route advertisement.

    Called by the midscaled daemon to advertise local subnet routes.
    Requires device token authentication.
    """
    from fastapi import HTTPException, status
    from sqlalchemy import select

    result = await session.execute(
        select(Device).where(Device.id == device_id, Device.is_active)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found or inactive")

    route_validation.check_safe_prefix(req.prefix, req.is_exit_node)

    overlaps = await _overlaps_with_existing(session, device.network_id, device_id, req.prefix)
    if overlaps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Route {req.prefix} already advertised by another device",
        )

    route = AdvertisedRoute(
        device_id=device_id,
        network_id=device.network_id,
        prefix=req.prefix,
        is_exit_node=req.is_exit_node,
    )
    session.add(route)
    await session.flush()

    ROUTES_TOTAL.inc()
    if req.is_exit_node:
        EXIT_NODES_TOTAL.inc()

    logger = __import__("structlog").get_logger(__name__)
    logger.info("device advertised route", device_id=str(device_id), prefix=req.prefix)
    return route
