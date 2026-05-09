"""WebSocket connection manager for admin UI and daemon connections."""

import asyncio
import json
from typing import Optional

import structlog
from fastapi import WebSocket

logger = structlog.get_logger(__name__)


class WebSocketConnectionManager:
    """Manages active WebSocket connections.

    Supports two types of connections:
    - **Admin UI**: anonymous connections tracked in a set, all events
      broadcast to every connected admin.
    - **Daemon**: per-device connections tracked by device_id, events
      delivered only to the targeted device's daemon.
    """

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._daemon_connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info(
            "websocket client connected",
            client=websocket.client,
            total=len(self._connections),
        )

    async def connect_daemon(self, websocket: WebSocket, device_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            self._daemon_connections[device_id] = websocket
        logger.info(
            "daemon websocket connected",
            device_id=device_id,
            total_daemon=len(self._daemon_connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            for did, ws in list(self._daemon_connections.items()):
                if ws == websocket:
                    del self._daemon_connections[did]
                    logger.info("daemon websocket disconnected", device_id=did)
                    break
        logger.info(
            "websocket client disconnected",
            client=websocket.client,
            total=len(self._connections),
        )

    async def broadcast(self, message: dict) -> None:
        payload = json.dumps(message)
        stale: list[WebSocket] = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.discard(ws)
                for did, dws in list(self._daemon_connections.items()):
                    if dws == ws:
                        del self._daemon_connections[did]
                        logger.info(
                            "cleaned stale daemon connection",
                            device_id=did,
                        )
                        break
        if stale:
            logger.info(
                "cleaned stale websocket connections",
                count=len(stale),
            )

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """Send a JSON message to a specific daemon's WebSocket.

        Returns True if the device was connected and the message was sent.
        """
        payload = json.dumps(message)
        async with self._lock:
            ws = self._daemon_connections.get(device_id)
            if ws is None:
                return False
            try:
                await ws.send_text(payload)
                return True
            except Exception:
                self._connections.discard(ws)
                del self._daemon_connections[device_id]
                logger.info(
                    "removed dead daemon connection",
                    device_id=device_id,
                )
                return False

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    @property
    def active_daemon_connections(self) -> int:
        return len(self._daemon_connections)

    def is_device_connected(self, device_id: str) -> bool:
        return device_id in self._daemon_connections
