"""Minimal STUN server (RFC 5389) for NAT traversal support.

Implements Binding request/response so that midscaled daemons can
discover their public IP:port as seen from the Midscale server.

STUN message format (RFC 5389):

    0                   1                   2                   3
    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |0 0|     STUN Message Type     |         Message Length        |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                         Magic Cookie                          |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                                                               |
   |                     Transaction ID (96 bits)                  |
   |                                                               |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                             Attributes ...
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
"""

import asyncio
import struct
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# STUN constants (RFC 5389)
STUN_MAGIC_COOKIE = 0x2112A442
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_XOR_MAPPED_ADDRESS = 0x0020
STUN_MAPPED_ADDRESS = 0x0001
STUN_SOFTWARE = 0x8022
STUN_FINGERPRINT = 0x8028

STUN_HEADER_SIZE = 20
STUN_MAX_MESSAGE_SIZE = 65535


def _build_binding_response(
    request_data: bytes,
    src_addr: tuple[str, int],
) -> Optional[bytes]:
    """Build a STUN Binding Response from a Binding Request.

    Parameters
    ----------
    request_data : bytes
        The raw STUN Binding Request (at least 20 bytes).
    src_addr : tuple[str, int]
        The client's (IP, port) as seen by this server. This is
        encoded as the XOR-MAPPED-ADDRESS attribute.

    Returns
    -------
    bytes or None
        The raw STUN Binding Response, or None if the request is
        malformed.
    """
    if len(request_data) < STUN_HEADER_SIZE:
        return None

    msg_type, msg_len, cookie = struct.unpack_from("!HHI", request_data, 0)

    if cookie != STUN_MAGIC_COOKIE:
        return None
    if msg_type != STUN_BINDING_REQUEST:
        return None

    transaction_id = request_data[8:20]
    if len(transaction_id) != 12:
        return None

    ip_str, port = src_addr
    family = 0x01  # IPv4

    try:
        packed_ip = _pack_ip(ip_str)
    except ValueError:
        logger.warning("stun: unable to pack client IP", ip=ip_str)
        return None

    xored_port = port ^ (STUN_MAGIC_COOKIE >> 16)
    xored_ip = struct.pack("!I", struct.unpack("!I", packed_ip)[0] ^ STUN_MAGIC_COOKIE)

    attr_value = struct.pack("!BBH", 0, family, xored_port) + xored_ip
    attr_length = len(attr_value)

    response_header = struct.pack(
        "!HHI",
        STUN_BINDING_RESPONSE,
        attr_length,
        STUN_MAGIC_COOKIE,
    )
    response = response_header + transaction_id + struct.pack("!HH", STUN_XOR_MAPPED_ADDRESS, attr_length) + attr_value

    return response


def _pack_ip(ip_str: str) -> bytes:
    """Pack an IPv4/IPv6 string into 4 or 16 raw bytes."""
    import ipaddress
    obj = ipaddress.ip_address(ip_str)
    return obj.packed


def _parse_request(request_data: bytes) -> Optional[dict]:
    """Parse a STUN Binding Request and return metadata (for logging)."""
    if len(request_data) < STUN_HEADER_SIZE:
        return None
    msg_type, msg_len, cookie = struct.unpack_from("!HHI", request_data, 0)
    if cookie != STUN_MAGIC_COOKIE or msg_type != STUN_BINDING_REQUEST:
        return None
    return {
        "type": "Binding Request",
        "length": msg_len,
    }


class StunServer:
    """Minimal RFC 5389 STUN server.

    Listens on a UDP port and responds to STUN Binding Requests with
    the client's observed IP and port encoded as XOR-MAPPED-ADDRESS.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 3478,
    ):
        self._host = host
        self._port = port
        self._running = False
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional[asyncio.DatagramProtocol] = None
        self._server: Optional[asyncio.AbstractServer] = None

    @property
    def port(self) -> int:
        return self._port

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        loop = asyncio.get_running_loop()
        stun_host = self._host
        stun_port = self._port

        class _StunProtocol(asyncio.DatagramProtocol):
            def __init__(self, handler):
                self.handler = handler

            def connection_made(self, transport):
                logger.info("stun server listening", host=stun_host, port=stun_port)

            def datagram_received(self, data, addr):
                handler(data, addr)

            def error_received(self, exc):
                logger.error("stun server error", error=str(exc))

        def handler(data: bytes, addr: tuple[str, int]):
            try:
                parsed = _parse_request(data)
                if parsed:
                    logger.debug(
                        "stun binding request",
                        client=addr,
                        length=parsed["length"],
                    )
                    response = _build_binding_response(data, addr)
                    if response and self._transport:
                        self._transport.sendto(response, addr)
                        logger.debug(
                            "stun binding response sent",
                            client=addr,
                        )
            except Exception as e:
                logger.warning("stun handler error", error=str(e))

        try:
            self._transport, self._protocol = await loop.create_datagram_endpoint(
                lambda: _StunProtocol(handler),
                local_addr=(self._host, self._port),
            )
            sockname = self._transport.get_extra_info("sockname")
            if sockname:
                self._port = sockname[1]
            logger.info(
                "stun server started",
                host=self._host,
                port=self._port,
            )
        except OSError as e:
            self._running = False
            logger.warning(
                "stun server failed to start (port in use?)",
                host=self._host,
                port=self._port,
                error=str(e),
            )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._transport:
            self._transport.close()
            self._transport = None
        logger.info("stun server stopped")
