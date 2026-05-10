"""Relay client for DERP-style fallback connectivity.

Connects to the Midscale relay server when direct peer-to-peer
connectivity cannot be established after NAT traversal attempts.
Manages relay session lifecycle, heartbeat, and stats reporting.
"""

import asyncio
import json
import struct
import time
from typing import Any, Optional

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig

logger = structlog.get_logger(__name__)

RELAY_MAGIC = b"MIDSCALE_RELAY_V1"
HEADER_FORMAT = "!I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

MSG_TYPE_PING = 0x01
MSG_TYPE_PONG = 0x02
MSG_TYPE_DATA = 0x03
MSG_TYPE_CONNECT = 0x04
MSG_TYPE_CONNECT_ACK = 0x05
MSG_TYPE_DISCONNECT = 0x06
MSG_TYPE_HEARTBEAT = 0x07
MSG_TYPE_HEARTBEAT_ACK = 0x08

_RECONNECT_BASE_DELAY = 1.0
_RECONNECT_MAX_DELAY = 60.0
_HEARTBEAT_INTERVAL = 30.0
_STATS_INTERVAL = 60.0


class DaemonRelayClient:
    """Relay client for fallback connectivity when direct punch fails.

    Connects to the relay server, manages session lifecycle, and
    forwards/receives tunneled data when direct peer connectivity
    is unavailable.
    """

    def __init__(
        self,
        config: DaemonConfig,
        api_client: MidscaleAPIClient,
        device_id: str,
        device_token: str,
    ):
        self._config = config
        self._api = api_client
        self._device_id = device_id
        self._device_token = device_token
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._active_sessions: dict[str, dict[str, Any]] = {}
        self._bytes_tx: int = 0
        self._bytes_rx: int = 0
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "relay client started",
            host=self._config.relay_host,
            port=self._config.relay_port,
        )

    async def stop(self) -> None:
        self._running = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._connected = False
        logger.info("relay client stopped")

    async def _run(self) -> None:
        await asyncio.sleep(1)
        delay = _RECONNECT_BASE_DELAY
        while self._running:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._config.relay_host,
                        self._config.relay_port,
                    ),
                    timeout=10.0,
                )
                self._connected = True
                delay = _RECONNECT_BASE_DELAY
                logger.info(
                    "relay client connected",
                    host=self._config.relay_host,
                    port=self._config.relay_port,
                )
                await self._run_session()
            except asyncio.TimeoutError:
                logger.warning(
                    "relay connect timeout",
                    host=self._config.relay_host,
                    port=self._config.relay_port,
                    retry_after=delay,
                )
            except ConnectionRefusedError:
                logger.warning(
                    "relay connection refused",
                    host=self._config.relay_host,
                    retry_after=delay,
                )
            except Exception as e:
                logger.warning(
                    "relay client error",
                    error=str(e),
                    retry_after=delay,
                )
            self._connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    async def _run_session(self) -> None:
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        stats_task = asyncio.create_task(self._stats_report_loop())
        try:
            await self._read_loop()
        finally:
            heartbeat_task.cancel()
            stats_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            try:
                await stats_task
            except asyncio.CancelledError:
                pass

    async def _read_loop(self) -> None:
        if not self._reader:
            return
        buffer = b""
        while self._running and self._reader:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(4096), timeout=30.0
                )
                if not data:
                    logger.warning("relay connection closed by server")
                    break
                buffer += data
                while len(buffer) >= HEADER_SIZE:
                    msg_len = struct.unpack(HEADER_FORMAT, buffer[:HEADER_SIZE])[0]
                    total_len = HEADER_SIZE + msg_len
                    if len(buffer) < total_len:
                        break
                    payload = buffer[HEADER_SIZE:total_len]
                    buffer = buffer[total_len:]
                    await self._handle_message(payload)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("relay read error", error=str(e))
                break

    async def _handle_message(self, payload: bytes) -> None:
        try:
            if not payload.startswith(RELAY_MAGIC):
                return
            inner = payload[len(RELAY_MAGIC):]
            msg_type = inner[0]
            body = inner[1:]

            if msg_type == MSG_TYPE_PONG:
                pass
            elif msg_type == MSG_TYPE_CONNECT_ACK:
                await self._handle_connect_ack(body)
            elif msg_type == MSG_TYPE_DATA:
                await self._handle_data(body)
            elif msg_type == MSG_TYPE_DISCONNECT:
                logger.info("relay disconnect received")
            elif msg_type == MSG_TYPE_HEARTBEAT_ACK:
                pass
        except Exception as e:
            logger.error("relay message handling error", error=str(e))

    async def _handle_connect_ack(self, body: bytes) -> None:
        try:
            data = json.loads(body.decode())
            status = data.get("status", "")
            if status == "connected":
                logger.info(
                    "relay session activated",
                    session_id=data.get("session_id"),
                )
            else:
                logger.warning(
                    "relay session rejected",
                    reason=data.get("reason"),
                )
        except json.JSONDecodeError as e:
            logger.error("relay connect ack parse error", error=str(e))

    async def _handle_data(self, body: bytes) -> None:
        try:
            data = json.loads(body.decode())
            from_device = data.get("from_device_id", "")
            payload_hex = data.get("data", "")
            payload = bytes.fromhex(payload_hex)
            self._bytes_rx += len(payload)
            logger.debug(
                "relay data received",
                from_device=from_device,
                size=len(payload),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error("relay data parse error", error=str(e))

    def _send_message(self, msg_type: int, body: bytes = b"") -> None:
        if not self._writer:
            return
        payload = RELAY_MAGIC + bytes([msg_type]) + body
        header = struct.pack(HEADER_FORMAT, len(payload))
        try:
            self._writer.write(header + payload)
        except Exception as e:
            logger.error("relay send error", error=str(e))

    async def connect_session(self, session_id: str, token: str) -> None:
        connect_msg = json.dumps({
            "token": token,
            "device_id": self._device_id,
            "session_id": session_id,
        }).encode()
        self._send_message(MSG_TYPE_CONNECT, connect_msg)
        self._active_sessions[session_id] = {
            "token": token,
            "connected_at": time.monotonic(),
        }
        logger.info(
            "relay session connect sent",
            session_id=session_id,
        )

    async def disconnect_session(self, session_id: str) -> None:
        disconnect_msg = json.dumps({
            "session_id": session_id,
        }).encode()
        self._send_message(MSG_TYPE_DISCONNECT, disconnect_msg)
        self._active_sessions.pop(session_id, None)
        logger.info(
            "relay session disconnect sent",
            session_id=session_id,
        )

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            try:
                heartbeat_msg = json.dumps({
                    "device_id": self._device_id,
                }).encode()
                self._send_message(MSG_TYPE_HEARTBEAT, heartbeat_msg)
            except Exception as e:
                logger.error("relay heartbeat error", error=str(e))

    async def _stats_report_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_STATS_INTERVAL)
            try:
                tx = self._bytes_tx
                rx = self._bytes_rx
                if tx > 0 or rx > 0:
                    stats_msg = json.dumps({
                        "device_id": self._device_id,
                        "stats": {"bytes_tx": tx, "bytes_rx": rx},
                    }).encode()
                    self._send_message(MSG_TYPE_HEARTBEAT, stats_msg)

                for session_id in list(self._active_sessions.keys()):
                    await self._api.request_relay_session_update(
                        relay_session_id=session_id,
                        bytes_tx=tx,
                        bytes_rx=rx,
                    )
            except Exception as e:
                logger.error("relay stats report error", error=str(e))
