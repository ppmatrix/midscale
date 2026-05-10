import ipaddress
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user, require_network_owner, filter_owned_networks
from app.models.user import User
from app.models.network import Network
from app.models.device import Device
from app.schemas.network import NetworkCreate, NetworkUpdate, NetworkResponse
from app.schemas.device import DeviceCreate, NodeDeviceCreate, DeviceResponse
from app.schemas.preauth_key import PreAuthKeyCreate, PreAuthKeyResponse
from app.models.preauth_key import PreAuthKey
from app.services.ipam import allocate_ip
from app.services.wireguard import save_device_keys, generate_keypair
from app.core.security import encrypt_private_key
from app.services.audit import audit_logger

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("", response_model=list[NetworkResponse])
async def list_networks(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await filter_owned_networks(session, current_user)


@router.post("", response_model=NetworkResponse, status_code=201)
async def create_network(
    req: NetworkCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    network = Network(
        name=req.name,
        subnet=req.subnet,
        description=req.description,
        interface_name=req.interface_name,
        owner_id=current_user.id,
    )
    session.add(network)
    await session.flush()

    server_ip = str(list(ipaddress.IPv4Network(req.subnet, strict=False).hosts())[0])
    private_key, public_key = await generate_keypair()
    server_device = Device(
        name="__midscale_server__",
        user_id=current_user.id,
        network_id=network.id,
        ip_address=server_ip,
        public_key=public_key,
        private_key_enc=encrypt_private_key(private_key),
        is_node_owned=False,
        enrollment_status="active",
        tags=[],
    )
    session.add(server_device)
    await session.flush()

    await audit_logger.log(
        session=session,
        action="network.create",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="network",
        target_id=str(network.id),
        details={"name": req.name, "subnet": req.subnet},
        ip_address=request.client.host if request.client else None,
    )
    return network


@router.get("/{network_id}", response_model=NetworkResponse)
async def get_network(
    network_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await require_network_owner(session, network_id, current_user)


@router.put("/{network_id}", response_model=NetworkResponse)
async def update_network(
    network_id: uuid.UUID,
    req: NetworkUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    network = await require_network_owner(session, network_id, current_user)
    if req.name is not None:
        network.name = req.name
    if req.description is not None:
        network.description = req.description
    if req.interface_name is not None:
        network.interface_name = req.interface_name
    if req.topology is not None:
        network.topology = req.topology if req.topology else None
    await session.flush()
    await audit_logger.log(
        session=session,
        action="network.update",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="network",
        target_id=str(network_id),
        details={"name": req.name, "description": req.description},
        ip_address=request.client.host if request.client else None,
    )
    return network


@router.delete("/{network_id}", status_code=204)
async def delete_network(
    network_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    network = await require_network_owner(session, network_id, current_user)
    await audit_logger.log(
        session=session,
        action="network.delete",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="network",
        target_id=str(network_id),
        details={"name": network.name},
        ip_address=request.client.host if request.client else None,
    )
    await session.delete(network)
    await session.flush()


@router.get("/{network_id}/devices", response_model=list[DeviceResponse])
async def list_devices(
    network_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(Device)
        .where(Device.network_id == network_id)
        .order_by(Device.created_at)
    )
    return result.scalars().all()


@router.post("/{network_id}/devices", response_model=DeviceResponse, status_code=201)
async def create_device(
    network_id: uuid.UUID,
    req: DeviceCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    network = await require_network_owner(session, network_id, current_user)
    ip = await allocate_ip(session, network_id, network.subnet)
    device = Device(
        name=req.name,
        user_id=current_user.id,
        network_id=network_id,
        ip_address=ip,
        dns_enabled=req.dns_enabled,
        tags=req.tags,
    )
    session.add(device)
    await session.flush()
    await save_device_keys(session, device)
    await audit_logger.log(
        session=session,
        action="device.create",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="device",
        target_id=str(device.id),
        details={"name": req.name, "network_id": str(network_id), "ip": ip},
        ip_address=request.client.host if request.client else None,
    )
    return device


@router.post(
    "/{network_id}/node-devices",
    response_model=DeviceResponse,
    status_code=201,
)
async def create_node_device(
    network_id: uuid.UUID,
    req: NodeDeviceCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    network = await require_network_owner(session, network_id, current_user)
    ip = await allocate_ip(session, network_id, network.subnet)
    device = Device(
        name=req.name,
        user_id=current_user.id,
        network_id=network_id,
        ip_address=ip,
        dns_enabled=req.dns_enabled,
        tags=req.tags,
        is_node_owned=True,
        enrollment_status="pending",
    )
    session.add(device)
    await session.flush()
    await audit_logger.log(
        session=session,
        action="device.create_node_owned",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="device",
        target_id=str(device.id),
        details={"name": req.name, "network_id": str(network_id), "ip": ip},
        ip_address=request.client.host if request.client else None,
    )
    return device


@router.get("/{network_id}/preauth-keys", response_model=list[PreAuthKeyResponse])
async def list_preauth_keys(
    network_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(PreAuthKey)
        .where(PreAuthKey.network_id == network_id)
        .order_by(PreAuthKey.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/{network_id}/preauth-keys",
    response_model=PreAuthKeyResponse,
    status_code=201,
)
async def create_preauth_key(
    network_id: uuid.UUID,
    req: PreAuthKeyCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    import secrets
    from datetime import datetime, timedelta, timezone
    await require_network_owner(session, network_id, current_user)
    key = PreAuthKey(
        key=f"midscale_{secrets.token_urlsafe(32)}",
        network_id=network_id,
        reusable=req.reusable,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=req.expires_in_hours),
    )
    session.add(key)
    await session.flush()
    await audit_logger.log(
        session=session,
        action="preauth_key.create",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="preauth_key",
        target_id=str(key.id),
        details={"network_id": str(network_id), "reusable": req.reusable, "expires_in_hours": req.expires_in_hours},
        ip_address=request.client.host if request.client else None,
    )
    return key


@router.delete("/{network_id}/preauth-keys/{key_id}", status_code=204)
async def delete_preauth_key(
    network_id: uuid.UUID,
    key_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(PreAuthKey).where(
            PreAuthKey.id == key_id, PreAuthKey.network_id == network_id
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    await audit_logger.log(
        session=session,
        action="preauth_key.delete",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="preauth_key",
        target_id=str(key_id),
        details={"network_id": str(network_id)},
        ip_address=request.client.host if request.client else None,
    )
    await session.delete(key)
    await session.flush()
