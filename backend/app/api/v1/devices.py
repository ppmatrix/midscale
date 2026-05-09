import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user, get_current_device, get_current_device_by_id
from app.models.user import User
from app.models.device import Device
from app.models.network import Network
from app.models.preauth_key import PreAuthKey
from app.schemas.device import (
    DeviceUpdate,
    DeviceResponse,
    DeviceConfigResponse,
    DeviceRegisterRequest,
    EnrollRequest,
    EnrollResponse,
    TokenRotationResponse,
    DeviceConfigV2Response,
    EnrollByKeyRequest,
    EnrollByKeyResponse,
    HeartbeatRequest,
    EndpointReport,
)
from app.services.metrics import DEVICE_ENROLLMENT
from app.services.ipam import allocate_ip
from app.services.wireguard import save_device_keys, get_device_config, build_config_v2
from app.services.daemon import process_heartbeat, report_endpoint
from app.services.audit import audit_logger
from app.core.security import hash_password, decode_token, generate_device_token
from app.config import settings
from app.services.event_types import Event, CONFIG_CHANGED

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceResponse])
async def list_all_devices(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    result = await session.execute(
        select(Device)
        .where(Device.user_id == current_user.id)
        .order_by(Device.created_at)
    )
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: uuid.UUID,
    req: DeviceUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if req.name is not None:
        device.name = req.name
    if req.dns_enabled is not None:
        device.dns_enabled = req.dns_enabled
    if req.is_active is not None:
        device.is_active = req.is_active
    if req.tags is not None:
        device.tags = req.tags
    if req.enrollment_status is not None:
        device.enrollment_status = req.enrollment_status
    if req.exit_node_id is not None:
        device.exit_node_id = req.exit_node_id
    await session.flush()
    await audit_logger.log(
        session=session,
        action="device.update",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="device",
        target_id=str(device_id),
        details={"name": req.name, "is_active": req.is_active, "tags": req.tags},
        ip_address=request.client.host if request.client else None,
    )
    return device


@router.post("/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: uuid.UUID,
    req: HeartbeatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_device: Annotated[Device, Depends(get_current_device_by_id)],
):
    return await process_heartbeat(
        session, device_id, req.public_key, req.ip_address
    )


@router.post("/{device_id}/endpoint")
async def device_report_endpoint(
    device_id: uuid.UUID,
    req: EndpointReport,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_device: Annotated[Device, Depends(get_current_device_by_id)],
):
    result = await report_endpoint(
        session, device_id, req.endpoint, req.source, req.port,
        local_ip=req.local_ip, public_ip=req.public_ip,
    )

    await _publish_config_change(
        session, current_device, "endpoint.updated"
    )

    return result



@router.post("/{device_id}/enroll", response_model=EnrollResponse)
async def enroll_device(
    device_id: uuid.UUID,
    req: EnrollRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not device.is_node_owned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device is not configured for node-owned keys",
        )
    if device.enrollment_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Device enrollment status is '{device.enrollment_status}', expected 'pending'",
        )

    device.public_key = req.public_key
    if req.ip_address:
        device.ip_address = req.ip_address
    device_token, prefix, hashed_secret = generate_device_token()
    device.device_token_hash = hashed_secret
    device.device_token_prefix = prefix
    device.enrollment_status = "active"
    device.enrolled_at = datetime.now(timezone.utc)
    await session.flush()
    await audit_logger.log(
        session=session,
        action="device.enroll",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="device",
        target_id=str(device_id),
        details={"public_key": req.public_key[:16] + "..."},
        ip_address=request.client.host if request.client else None,
    )
    return EnrollResponse(
        device_id=device.id,
        device_token=device_token,
        status="active",
    )


@router.get("/{device_id}/config", response_model=DeviceConfigResponse)
async def get_device_config_endpoint(
    device_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    config = await get_device_config(session, device_id)
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one()
    return DeviceConfigResponse(
        config=config,
        filename=f"midscale-{device.name}.conf",
    )


@router.post("/{device_id}/rotate-token", response_model=TokenRotationResponse)
async def rotate_device_token(
    device_id: uuid.UUID,
    request: Request,
    current_device: Annotated[Device, Depends(get_current_device)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    if current_device.id != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device token can only be rotated by the device itself",
        )
    if current_device.enrollment_status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rotate token for device with status '{current_device.enrollment_status}'",
        )
    from app.core.security import generate_device_token as _gen_token
    from app.core.security import hash_password as _hash_pw
    import secrets as _secrets
    if current_device.device_token_prefix:
        new_secret = _secrets.token_urlsafe(36)
        new_token = f"midscale_device_{current_device.device_token_prefix}_{new_secret}"
        current_device.device_token_hash = _hash_pw(new_secret)
    else:
        new_token, prefix, hashed = _gen_token()
        current_device.device_token_hash = hashed
        current_device.device_token_prefix = prefix
    await session.flush()
    return TokenRotationResponse(device_token=new_token)


@router.post("/{device_id}/revoke", status_code=204)
async def revoke_device(
    device_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status

    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device.enrollment_status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device is already revoked",
        )

    device.enrollment_status = "revoked"
    device.is_active = False
    device.revoked_at = datetime.now(timezone.utc)
    await session.flush()

    await _publish_config_change(
        session, device, "device.revoked"
    )

    await audit_logger.log(
        session=session,
        action="device.revoke",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="device",
        target_id=str(device_id),
        details={"enrollment_status": "revoked"},
        ip_address=request.client.host if request.client else None,
    )


@router.get("/{device_id}/config-v2", response_model=DeviceConfigV2Response)
async def get_device_config_v2(
    device_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    user: Optional[User] = None
    device_auth: Optional[Device] = None

    payload = decode_token(credentials)
    if payload and payload.get("type") == "access":
        uid_str = payload.get("sub")
        if uid_str:
            try:
                uid = uuid.UUID(uid_str)
                u_result = await session.execute(
                    select(User).where(User.id == uid, User.is_active)
                )
                user = u_result.scalar_one_or_none()
            except ValueError:
                pass

    if not user:
        from app.api.deps import _lookup_device_by_token
        device_auth = await _lookup_device_by_token(session, credentials)

    if not user and not device_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
        )
    if device_auth and device_auth.id != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device token does not match requested device",
        )
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if not device.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device is not active",
        )
    if not device.ip_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device has no IP address assigned",
        )
    if device.enrollment_status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Device enrollment status is '{device.enrollment_status}', expected 'active'",
        )

    return await build_config_v2(session, device)


@router.post("/enroll", response_model=EnrollByKeyResponse, status_code=201)
async def enroll_by_key(
    req: EnrollByKeyRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    key_result = await session.execute(
        select(PreAuthKey).where(PreAuthKey.key == req.preauth_key)
    )
    preauth = key_result.scalar_one_or_none()
    if not preauth:
        DEVICE_ENROLLMENT.labels(result="invalid_key").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid pre-auth key",
        )
    if preauth.expires_at < datetime.now(timezone.utc):
        DEVICE_ENROLLMENT.labels(result="expired_key").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pre-auth key has expired",
        )
    if not preauth.reusable and preauth.used_by and len(preauth.used_by) > 0:
        DEVICE_ENROLLMENT.labels(result="used_key").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pre-auth key has already been used",
        )

    net_result = await session.execute(
        select(Network).where(Network.id == preauth.network_id)
    )
    network = net_result.scalar_one()
    ip = await allocate_ip(session, preauth.network_id, network.subnet)
    now = datetime.now(timezone.utc)

    device_token, prefix, hashed_secret = generate_device_token()
    device = Device(
        name=req.name,
        user_id=None,
        network_id=preauth.network_id,
        ip_address=ip,
        public_key=req.public_key,
        is_node_owned=True,
        device_token_hash=hashed_secret,
        device_token_prefix=prefix,
        enrollment_status="active",
        enrolled_at=now,
        last_seen_at=now,
        tags=[],
    )
    session.add(device)
    await session.flush()

    if not preauth.reusable:
        await session.delete(preauth)
    else:
        used_by = list(preauth.used_by or [])
        used_by.append(str(device.id))
        preauth.used_by = used_by
    await session.flush()

    config_v2 = await build_config_v2(session, device)
    DEVICE_ENROLLMENT.labels(result="success").inc()

    await audit_logger.log(
        session=session,
        action="device.enroll_by_key",
        actor_id=str(device.id),
        actor_type="device",
        target_type="device",
        target_id=str(device.id),
        details={
            "name": req.name,
            "network_id": str(preauth.network_id),
            "ip": ip,
            "hostname": req.hostname,
        },
        ip_address=request.client.host if request.client else None,
    )

    return EnrollByKeyResponse(
        device_id=device.id,
        device_token=device_token,
        network_id=preauth.network_id,
        ip_address=ip,
        config_v2=config_v2,
    )


@router.post("/register", response_model=DeviceResponse, status_code=201)
async def register_device(
    req: DeviceRegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    key_result = await session.execute(
        select(PreAuthKey).where(PreAuthKey.key == req.key)
    )
    preauth = key_result.scalar_one_or_none()
    if not preauth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid pre-auth key",
        )
    if preauth.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pre-auth key has expired",
        )
    net_result = await session.execute(
        select(Network).where(Network.id == preauth.network_id)
    )
    network = net_result.scalar_one()
    ip = await allocate_ip(session, preauth.network_id, network.subnet)
    device = Device(
        name=req.name,
        user_id=None,
        network_id=preauth.network_id,
        ip_address=ip,
    )
    session.add(device)
    await session.flush()
    await save_device_keys(session, device)
    if not preauth.reusable:
        await session.delete(preauth)
    else:
        used_by = list(preauth.used_by or [])
        used_by.append(str(device.id))
        preauth.used_by = used_by
    await session.flush()
    await audit_logger.log(
        session=session,
        action="device.register",
        actor_id=str(device.id),
        actor_type="device",
        target_type="device",
        target_id=str(device.id),
        details={"name": req.name, "network_id": str(preauth.network_id), "ip": ip},
        ip_address=request.client.host if request.client else None,
    )
    return device


async def _publish_config_change(
    session: AsyncSession, device: Device, reason: str
) -> None:
    """Publish a config.changed event for the device's network peers."""
    try:
        from app.main import get_event_bus, get_ws_manager
        event_bus = get_event_bus()
        ws_manager = get_ws_manager()
        if not event_bus:
            return

        config = await build_config_v2(session, device)
        event = Event(
            event_type=CONFIG_CHANGED,
            data={
                "device_id": str(device.id),
                "network_id": str(device.network_id),
                "revision": config.revision,
                "hash": config.hash,
                "reason": reason,
            },
        )
        await event_bus.publish(event)

        if ws_manager:
            net_result = await session.execute(
                select(Device).where(
                    Device.network_id == device.network_id,
                    Device.is_active,
                    Device.id != device.id,
                )
            )
            peers = net_result.scalars().all()
            for peer in peers:
                await ws_manager.send_to_device(
                    str(peer.id),
                    {
                        "type": "config.changed",
                        "device_id": str(peer.id),
                        "network_id": str(device.network_id),
                        "revision": config.revision,
                        "reason": reason,
                    },
                )
    except Exception:
        pass
