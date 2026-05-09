"""STUN client (RFC 5389) for NAT traversal support.

Sends STUN Binding Requests to a STUN server and parses the response
to discover the public IP and port as seen from the server's perspective.

This allows devices behind NAT to discover their mapped address and
report it to the Midscale control plane for direct peer-to-peer
connectivity in mesh/hybrid topologies.
"""

import asyncio
import random
import socket
import struct
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# STUN constants (RFC 5389)
STUN_MAGIC_COOKIE = 0x2112A442
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_XOR_MAPPED_ADDRESS = 0x0020

STUN_HEADER_SIZE = 20
STUN_DEFAULT_TIMEOUT = 3.0
STUN_DEFAULT_PORT = 3478


@dataclass
class StunResult:
    """Result of a STUN query to a single server."""

    public_ip: str
    public_port: int
    server: str
    rtt_ms: float


def _build_binding_request() -> tuple[bytes, bytes]:
    """Build a STUN Binding Request with a random transaction ID.

    Returns
    -------
    tuple[bytes, bytes]
        The (request_bytes, transaction_id) pair.
    """
    transaction_id = random.randbytes(12)
    header = struct.pack(
        "!HHI",
        STUN_BINDING_REQUEST,
        0,
        STUN_MAGIC_COOKIE,
    )
    return header + transaction_id, transaction_id


def _parse_binding_response(
    data: bytes,
    expected_tid: bytes,
) -> Optional[tuple[str, int]]:
    """Parse a STUN Binding Response and extract XOR-MAPPED-ADDRESS.

    Parameters
    ----------
    data : bytes
        Raw STUN response.
    expected_tid : bytes
        The transaction ID we sent in the request (12 bytes).

    Returns
    -------
    tuple[str, int] or None
        (public_ip, public_port) or None if parsing fails.
    """
    if len(data) < STUN_HEADER_SIZE:
        return None

    msg_type, msg_len, cookie = struct.unpack_from("!HHI", data, 0)

    if cookie != STUN_MAGIC_COOKIE:
        return None
    if msg_type != STUN_BINDING_RESPONSE:
        return None

    tid = data[8:20]
    if tid != expected_tid or len(tid) != 12:
        return None

    offset = STUN_HEADER_SIZE
    end = offset + msg_len

    while offset + 4 <= end:
        attr_type, attr_length = struct.unpack_from("!HH", data, offset)
        attr_value_offset = offset + 4

        if attr_type == STUN_XOR_MAPPED_ADDRESS and attr_length >= 8:
            reserved, family, xored_port = struct.unpack_from(
                "!BBH", data, attr_value_offset
            )
            port = xored_port ^ (STUN_MAGIC_COOKIE >> 16)

            if family == 0x01 and attr_length >= 8:
                xored_ip = struct.unpack_from("!I", data, attr_value_offset + 4)[0]
                ip_int = xored_ip ^ STUN_MAGIC_COOKIE
                ip = socket.inet_ntoa(struct.pack("!I", ip_int))
                return ip, port

            elif family == 0x02 and attr_length >= 20:
                words = struct.unpack_from("!IIII", data, attr_value_offset + 4)
                xored_words = [
                    w ^ STUN_MAGIC_COOKIE for w in words
                ]
                ip = socket.inet_ntop(
                    socket.AF_INET6,
                    struct.pack("!IIII", *xored_words),
                )
                return ip, port

        offset += 4 + attr_length
        if attr_length % 2:
            offset += 1

    return None


async def query_stun_server(
    server: str,
    port: int = STUN_DEFAULT_PORT,
    timeout: float = STUN_DEFAULT_TIMEOUT,
    source_port: int = 0,
) -> Optional[StunResult]:
    """Send a STUN Binding Request to a server and return the result.

    Parameters
    ----------
    server : str
        STUN server hostname or IP.
    port : int
        STUN server port (default 3478).
    timeout : float
        Maximum time to wait for a response (seconds).
    source_port : int
        Local UDP port to bind (0 = OS-assigned).

    Returns
    -------
    StunResult or None
        The discovered public address and server info, or None on failure.
    """
    import time

    request, tid = _build_binding_request()
    loop = asyncio.get_running_loop()

    try:
        addr = await loop.getaddrinfo(server, port, type=socket.SOCK_DGRAM)
        if not addr:
            logger.warning("stun: no addresses resolved", server=server)
            return None
        family, _, _, _, sockaddr = addr[0]

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _StunClientProtocol(request, tid, timeout),
            local_addr=("0.0.0.0", source_port) if source_port else None,
            family=family,
        )

        try:
            result = await asyncio.wait_for(
                protocol.done,
                timeout=timeout + 1.0,
            )
            return result
        except asyncio.TimeoutError:
            logger.debug("stun: timeout", server=server, port=port)
            return None
        finally:
            if not transport.is_closing():
                transport.close()

    except Exception as e:
        logger.debug("stun: query error", server=server, error=str(e))
        return None


class _StunClientProtocol(asyncio.DatagramProtocol):
    """Internal UDP protocol for a single STUN request."""

    def __init__(
        self,
        request: bytes,
        transaction_id: bytes,
        timeout: float,
    ):
        self._request = request
        self._transaction_id = transaction_id
        self._timeout = timeout
        self._transport: Optional[asyncio.DatagramTransport] = None
        self.done: asyncio.Future[Optional[StunResult]] = asyncio.Future()
        self._start_time: float = 0.0
        self._server_addr: Optional[tuple] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport
        self._start_time = __import__("time").time()
        transport.sendto(self._request)

    def datagram_received(self, data: bytes, addr: tuple):
        rtt = (__import__("time").time() - self._start_time) * 1000
        result = _parse_binding_response(data, self._transaction_id)
        if result:
            ip, port = result
            server_str = f"{addr[0]}:{addr[1]}" if addr else "unknown"
            if not self.done.done():
                self.done.set_result(
                    StunResult(
                        public_ip=ip,
                        public_port=port,
                        server=server_str,
                        rtt_ms=round(rtt, 1),
                    )
                )
        elif not self.done.done():
            self.done.set_result(None)

    def error_received(self, exc: Exception):
        if not self.done.done():
            self.done.set_result(None)

    def connection_lost(self, exc: Optional[Exception]):
        if not self.done.done():
            self.done.set_result(None)


async def query_stun_servers(
    servers: list[tuple[str, int]],
    timeout: float = STUN_DEFAULT_TIMEOUT,
) -> Optional[StunResult]:
    """Query multiple STUN servers and return the first successful result.

    Parameters
    ----------
    servers : list[tuple[str, int]]
        List of (host, port) tuples to query.
    timeout : float
        Per-server timeout in seconds.

    Returns
    -------
    StunResult or None
        The first successful result, or None if all servers failed.
    """
    for server, port in servers:
        result = await query_stun_server(server, port, timeout=timeout)
        if result:
            return result
    return None
