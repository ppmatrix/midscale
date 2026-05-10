import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.core.security import decode_token, verify_password
from app.models.user import User
from app.models.device import Device
from app.models.network import Network
from app.services.metrics import DAEMON_AUTH_FAILURES

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return current_user


_TOKEN_PREFIX = "midscale_device_"


async def get_current_device(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Device:
    """Authenticate a device by its bearer token.

    Uses prefix-based lookup for new-format tokens
    (``midscale_device_<prefix>_<secret>``) and falls back to full scan
    for legacy tokens that lack a prefix.
    """
    token = credentials.credentials
    device = await _lookup_device_by_token(session, token)
    if device is None:
        DAEMON_AUTH_FAILURES.labels(reason="invalid_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
        )
    return device


async def get_current_device_by_id(
    device_id: uuid.UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Device:
    """Authenticate a device and verify the device_id in the path matches
    the token's device. Used by daemon-facing endpoints like heartbeat."""
    token = credentials.credentials
    device = await _lookup_device_by_token(session, token)
    if device is None:
        DAEMON_AUTH_FAILURES.labels(reason="invalid_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
        )
    if device.id != device_id:
        DAEMON_AUTH_FAILURES.labels(reason="device_id_mismatch").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device token does not match requested device",
        )
    return device


async def _lookup_device_by_token(
    session: AsyncSession, token: str
) -> Device | None:
    if token.startswith(_TOKEN_PREFIX):
        # Token format: midscale_device_<8-char-prefix>_<secret>
        # Must extract by position because base64url can contain underscores.
        rest = token[len(_TOKEN_PREFIX):]
        if len(rest) > 9 and rest[8] == "_":
            raw_prefix = rest[:8]
            secret = rest[9:]
            result = await session.execute(
                select(Device).where(
                    Device.device_token_prefix == raw_prefix,
                    Device.is_active,
                )
            )
            device = result.scalar_one_or_none()
            if device and device.device_token_hash:
                if verify_password(secret, device.device_token_hash):
                    return _check_device_status(device)
                DAEMON_AUTH_FAILURES.labels(reason="bad_secret").inc()

    result = await session.execute(
        select(Device).where(Device.is_active)
    )
    for device in result.scalars().all():
        if device.device_token_hash and verify_password(
            token, device.device_token_hash
        ):
            return _check_device_status(device)
    return None


def _check_device_status(device: Device) -> Device:
    if device.enrollment_status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device has been revoked",
        )
    if device.enrollment_status == "expired":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device enrollment has expired",
        )
    if device.enrollment_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device enrollment not yet completed",
        )
    return device


async def require_network_owner(
    session: AsyncSession,
    network_id: uuid.UUID,
    current_user: User,
) -> Network:
    """Fetch a network and verify the current user owns it (or is superuser).

    Raises 404 if not found, 403 if not owner.
    Returns the network on success.
    """
    result = await session.execute(
        select(Network).where(Network.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Network not found",
        )
    if not current_user.is_superuser and network.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this network",
        )
    return network


async def filter_owned_networks(
    session: AsyncSession,
    current_user: User,
) -> list[Network]:
    """Return all networks if superuser, or only owned networks for normal users."""
    query = select(Network).order_by(Network.created_at)
    if not current_user.is_superuser:
        query = query.where(Network.owner_id == current_user.id)
    result = await session.execute(query)
    return result.scalars().all()
