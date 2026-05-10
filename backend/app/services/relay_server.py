"""Minimal asyncio TCP relay server for DERP-style relay fallback.

Provides a lightweight TCP-based relay for devices that cannot establish
direct peer-to-peer connectivity after NAT traversal attempts. Designed
as a modular transport abstraction for future QUIC/UDP relay support.
"""

import asyncio
import json
import struct
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

RELAY_MAGIC = b"MIDSCALE_RELAY_V1"
HEADER_FORMAT = "!I"  # 4-byte message length
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

MSG_TYPE_PING = 0x01
MSG_TYPE_PONG = 0x02
MSG_TYPE_DATA = 0x03
MSG_TYPE_CONNECT = 0x04
MSG_TYPE_CONNECT_ACK = 0x05
MSG_TYPE_DISCONNECT = 0x06
MSG_TYPE_HEARTBEAT = 0x07
MSG_TYPE_HEARTBEAT_ACK = 0x08


class RelayProtocol(asyncio.Protocol):
    """TCP protocol handler for relay connections."""

    def __init__(self, server: "RelayServer"):
        self._server = server
        self._transport: Optional[asyncio.Transport] = None
        self._buffer = b""
        self._session_token: Optional[str] = None
        self._device_id: Optional[str] = None
        self._peer_addr: Optional[str] = None

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._transport = transport
        addr = transport.get_extra_info("peername") or ("unknown", 0)
        self._peer_addr = f"{addr[0]}:{addr[1]}"
        logger.debug("relay connection made", peer=self._peer_addr)

    def data_received(self, data: bytes) -> None:
        self._buffer += data
        while len(self._buffer) >= HEADER_SIZE:
            msg_len = struct.unpack(HEADER_FORMAT, self._buffer[:HEADER_SIZE])[0]
            total_len = HEADER_SIZE + msg_len
            if len(self._buffer) < total_len:
                break
            payload = self._buffer[HEADER_SIZE:total_len]
            self._buffer = self._buffer[total_len:]
            self._handle_message(payload)

    def _handle_message(self, payload: bytes) -> None:
        try:
            if not payload.startswith(RELAY_MAGIC):
                logger.warning("invalid relay magic", peer=self._peer_addr)
                return
            inner = payload[len(RELAY_MAGIC):]
            msg_type = inner[0]
            body = inner[1:]
            if msg_type == MSG_TYPE_PING:
                self._send_pong()
            elif msg_type == MSG_TYPE_CONNECT:
                self._handle_connect(body)
            elif msg_type == MSG_TYPE_DATA:
                self._handle_data(body)
            elif msg_type == MSG_TYPE_DISCONNECT:
                self._handle_disconnect()
            elif msg_type == MSG_TYPE_HEARTBEAT:
                self._handle_heartbeat(body)
            else:
                logger.warning("unknown relay message type", msg_type=msg_type)
        except Exception as e:
            logger.error("relay message handling error", error=str(e))

    def _send_message(self, msg_type: int, body: bytes = b"") -> None:
        if not self._transport:
            return
        payload = RELAY_MAGIC + bytes([msg_type]) + body
        header = struct.pack(HEADER_FORMAT, len(payload))
        self._transport.write(header + payload)

    def _send_pong(self) -> None:
        self._send_message(MSG_TYPE_PONG)

    def _handle_connect(self, body: bytes) -> None:
        try:
            data = json.loads(body.decode())
            self._session_token = data.get("token", "")
            self._device_id = data.get("device_id", "")
            session_id = data.get("session_id", "")

            is_valid = self._server.validate_session(
                self._session_token, session_id
            )
            if is_valid:
                self._server.register_connection(self._device_id, self)
                ack = json.dumps({
                    "status": "connected",
                    "session_id": session_id,
                    "device_id": self._device_id,
                }).encode()
                self._send_message(MSG_TYPE_CONNECT_ACK, ack)
                logger.info(
                    "relay session connected",
                    device_id=self._device_id,
                    session_id=session_id,
                )
            else:
                nack = json.dumps({
                    "status": "rejected",
                    "reason": "invalid token or session",
                }).encode()
                self._send_message(MSG_TYPE_CONNECT_ACK, nack)
                logger.warning(
                    "relay connect rejected",
                    device_id=self._device_id,
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("relay connect parse error", error=str(e))

    def _handle_data(self, body: bytes) -> None:
        """Forward relayed data to the target device connection."""
        try:
            header_end = body.index(b"|")
            target_device_id = body[:header_end].decode()
            relay_data = body[header_end + 1:]

            target_conn = self._server.get_connection(target_device_id)
            if target_conn:
                forward = json.dumps({
                    "from_device_id": self._device_id,
                    "data": relay_data.hex(),
                }).encode()
                target_conn._send_message(MSG_TYPE_DATA, forward)
        except (ValueError, IndexError) as e:
            logger.error("relay data forward error", error=str(e))

    def _handle_disconnect(self) -> None:
        if self._device_id:
            self._server.unregister_connection(self._device_id)
            logger.info(
                "relay device disconnected",
                device_id=self._device_id,
            )
        self._session_token = None
        self._device_id = None

    def _handle_heartbeat(self, body: bytes) -> None:
        try:
            data = json.loads(body.decode())
            stats = data.get("stats", {})
            if self._device_id:
                self._server.update_heartbeat(
                    self._device_id, stats
                )
            ack = json.dumps({
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).encode()
            self._send_message(MSG_TYPE_HEARTBEAT_ACK, ack)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("relay heartbeat parse error", error=str(e))

    def send_data(self, data: bytes) -> None:
        self._send_message(MSG_TYPE_DATA, data)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        if self._device_id:
            self._server.unregister_connection(self._device_id)
            logger.info(
                "relay connection lost",
                device_id=self._device_id,
                peer=self._peer_addr,
            )
        self._transport = None


class RelayServer:
    """Minimal TCP relay server for DERP-style fallback.

    Manages authenticated relay sessions between devices that cannot
    establish direct peer-to-peer connectivity.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False
        self._connections: dict[str, RelayProtocol] = {}
        self._heartbeats: dict[str, float] = {}
        self._valid_tokens: dict[str, str] = {}  # token -> session_id

    @property
    def port(self) -> int:
        return self._port

    def add_valid_token(self, token: str, session_id: str) -> None:
        self._valid_tokens[token] = session_id

    def validate_session(self, token: str, session_id: str) -> bool:
        stored = self._valid_tokens.get(token)
        return stored == session_id

    def register_connection(
        self, device_id: str, protocol: RelayProtocol
    ) -> None:
        self._connections[device_id] = protocol
        self._heartbeats[device_id] = time.monotonic()

    def unregister_connection(self, device_id: str) -> None:
        self._connections.pop(device_id, None)
        self._heartbeats.pop(device_id, None)
        self._valid_tokens = {
            k: v for k, v in self._valid_tokens.items()
            if v != device_id
        }

    def get_connection(
        self, device_id: str
    ) -> Optional[RelayProtocol]:
        return self._connections.get(device_id)

    def update_heartbeat(
        self, device_id: str, stats: dict[str, Any]
    ) -> None:
        self._heartbeats[device_id] = time.monotonic()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_running_loop()
        self._server = await loop.create_server(
            lambda: RelayProtocol(self),
            host=self._host,
            port=self._port,
        )
        logger.info(
            "relay server started",
            host=self._host,
            port=self._port,
        )

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for conn in list(self._connections.values()):
            conn._handle_disconnect()
        self._connections.clear()
        self._heartbeats.clear()
        self._valid_tokens.clear()
        logger.info("relay server stopped")

    def remove_expired_tokens(self) -> None:
        now = time.monotonic()
        stale_threshold = now - 120
        stale = [
            token for token, ts in self._heartbeats.items()
            if ts < stale_threshold
        ]
        for device_id in stale:
            self.unregister_connection(device_id)
            logger.info(
                "relay connection expired (no heartbeat)",
                device_id=device_id,
            )


_relay_server: Optional[RelayServer] = None


def get_relay_server() -> Optional[RelayServer]:
    return _relay_server


def set_relay_server(server: RelayServer) -> None:
    global _relay_server
    _relay_server = server
