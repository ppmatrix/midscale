"""WebSocket endpoints for admin UI and daemon connections."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.core.security import decode_token
from app.models.user import User
from app.models.device import Device
from app.services.ws_manager import WebSocketConnectionManager
from app.api.deps import _lookup_device_by_token

router = APIRouter(tags=["websocket"])


def get_ws_manager() -> Optional[WebSocketConnectionManager]:
    from app.main import _ws_manager
    return _ws_manager


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = None,
):
    """Admin UI WebSocket — broadcasts all events to every connected client."""
    manager = get_ws_manager()
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    if token:
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


@router.websocket("/daemon/ws")
async def daemon_websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,
):
    """Daemon WebSocket — authenticated with device token.

    Query parameters:
    - ``token``: device token (``midscale_device_<prefix>_<secret>``)

    On connect, the daemon is authenticated and registered for targeted
    config-changed push events. Invalid tokens are rejected with 4001.
    """
    manager = get_ws_manager()
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    if not token:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Device token required",
        )
        return

    device = await _lookup_device_by_token(session, token)
    if device is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid device token",
        )
        return

    if device.enrollment_status != "active":
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=f"Device status is '{device.enrollment_status}'",
        )
        return

    await manager.connect_daemon(websocket, str(device.id))
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
