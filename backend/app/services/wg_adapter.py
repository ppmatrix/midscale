import asyncio
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from app.services.wg_exceptions import (
    WireGuardCommandError,
    WireGuardInterfaceNotFound,
    WireGuardKeyError,
)
from app.services.wg_models import WGInterfaceState, WGPeer

_PEER_KEY_PATTERN = re.compile(r"^[A-Za-z0-9+/]{43}=$")
_HEX_KEY_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def validate_wireguard_key(key: str) -> bool:
    if not key or not isinstance(key, str):
        return False
    if _PEER_KEY_PATTERN.match(key):
        return True
    if _HEX_KEY_PATTERN.match(key):
        return True
    return False


class WireGuardAdapter(ABC):
    """Abstract interface for WireGuard operations.

    All methods are idempotent where possible.
    Private keys are never logged.
    """

    @abstractmethod
    async def get_interface_state(self, interface: str) -> WGInterfaceState:
        """Fetch full runtime state of a WireGuard interface.
        Raises WireGuardInterfaceNotFound if the interface does not exist.
        """

    @abstractmethod
    async def interface_exists(self, interface: str) -> bool:
        """Check if a WireGuard interface exists on the system."""

    @abstractmethod
    async def add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: list[str],
        endpoint: Optional[str] = None,
        persistent_keepalive: Optional[int] = None,
    ) -> None:
        """Add a peer to the interface. Idempotent — overwrites if exists."""

    @abstractmethod
    async def remove_peer(self, interface: str, public_key: str) -> None:
        """Remove a peer from the interface. Idempotent — no-op if not found."""

    @abstractmethod
    async def update_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: Optional[list[str]] = None,
        endpoint: Optional[str] = None,
        persistent_keepalive: Optional[int] = None,
    ) -> None:
        """Update an existing peer's attributes."""

    @abstractmethod
    async def set_peer_endpoint(
        self, interface: str, public_key: str, endpoint: str
    ) -> None:
        """Update just the endpoint of an existing peer."""

    @abstractmethod
    async def list_interfaces(self) -> list[str]:
        """List all WireGuard interfaces on the system."""


def _parse_dump_timestamp(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    if not raw or raw == "0":
        return None
    try:
        ts = int(raw)
        if ts == 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


class WgCliAdapter(WireGuardAdapter):
    """WireGuard adapter using the `wg` CLI via subprocess.

    This is the primary implementation. It shells out to the `wg` binary
    and parses its output. The `dump` command is used for reading state
    as it provides all peer information in a single call.

    Security: private keys are never logged. Command arguments that
    include keys are redacted in log output.
    """

    def __init__(self, wg_binary: str = "wg", log=None):
        self._wg_binary = wg_binary
        self._log = log

    async def _run(
        self, *args: str, input_data: Optional[str] = None
    ) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            self._wg_binary,
            *args,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(
            input=input_data.encode() if input_data else None
        )
        out = stdout.decode().strip()
        err = stderr.decode().strip()
        if proc.returncode != 0:
            cmd_str = " ".join(str(a) for a in ([self._wg_binary] + list(args)))
            raise WireGuardCommandError(
                command=cmd_str,
                return_code=proc.returncode,
                stderr=err,
            )
        return out, err

    async def interface_exists(self, interface: str) -> bool:
        try:
            await self._run("show", interface)
            return True
        except WireGuardCommandError:
            return False

    async def get_interface_state(self, interface: str) -> WGInterfaceState:
        raw, _ = await self._run("show", interface, "dump")
        if not raw:
            raise WireGuardInterfaceNotFound(interface)
        return self._parse_dump(raw, interface)

    async def add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: list[str],
        endpoint: Optional[str] = None,
        persistent_keepalive: Optional[int] = None,
    ) -> None:
        if not validate_wireguard_key(public_key):
            raise WireGuardKeyError(f"Invalid public key format: {public_key[:16]}...")
        args: list[str] = [
            "set",
            interface,
            "peer",
            public_key,
            "allowed-ips",
            ",".join(allowed_ips),
        ]
        if endpoint:
            args.extend(["endpoint", endpoint])
        if persistent_keepalive is not None:
            args.extend(["persistent-keepalive", str(persistent_keepalive)])
        try:
            await self._run(*args)
        except WireGuardCommandError as e:
            if "No such device" in e.stderr or "does not exist" in e.stderr:
                raise WireGuardInterfaceNotFound(interface) from e
            raise

    async def remove_peer(self, interface: str, public_key: str) -> None:
        if not validate_wireguard_key(public_key):
            raise WireGuardKeyError(f"Invalid public key format: {public_key[:16]}...")
        try:
            await self._run("set", interface, "peer", public_key, "remove")
        except WireGuardCommandError as e:
            if "No such device" in e.stderr or "does not exist" in e.stderr:
                raise WireGuardInterfaceNotFound(interface) from e
            if "Invalid peer" in e.stderr or "is not a valid" in e.stderr:
                raise WireGuardKeyError(f"Invalid peer key: {public_key[:16]}...") from e
            raise

    async def update_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: Optional[list[str]] = None,
        endpoint: Optional[str] = None,
        persistent_keepalive: Optional[int] = None,
    ) -> None:
        if not validate_wireguard_key(public_key):
            raise WireGuardKeyError(f"Invalid public key format: {public_key[:16]}...")
        args: list[str] = [
            "set",
            interface,
            "peer",
            public_key,
        ]
        if allowed_ips is not None:
            args.extend(["allowed-ips", ",".join(allowed_ips)])
        if endpoint is not None:
            args.extend(["endpoint", endpoint])
        if persistent_keepalive is not None:
            args.extend(["persistent-keepalive", str(persistent_keepalive)])
        if len(args) == 4:
            return
        try:
            await self._run(*args)
        except WireGuardCommandError as e:
            if "No such device" in e.stderr or "does not exist" in e.stderr:
                raise WireGuardInterfaceNotFound(interface) from e
            raise

    async def set_peer_endpoint(
        self, interface: str, public_key: str, endpoint: str
    ) -> None:
        if not validate_wireguard_key(public_key):
            raise WireGuardKeyError(f"Invalid public key format: {public_key[:16]}...")
        try:
            await self._run(
                "set", interface, "peer", public_key, "endpoint", endpoint
            )
        except WireGuardCommandError as e:
            if "No such device" in e.stderr or "does not exist" in e.stderr:
                raise WireGuardInterfaceNotFound(interface) from e
            raise

    async def list_interfaces(self) -> list[str]:
        try:
            raw, _ = await self._run("show", "interfaces")
            if not raw:
                return []
            return raw.split()
        except WireGuardCommandError:
            return []

    def _parse_dump(self, raw: str, interface: str) -> WGInterfaceState:
        lines = raw.split("\n")
        if not lines:
            raise WireGuardInterfaceNotFound(interface)

        first = lines[0].split("\t")
        priv_key = first[0] if len(first) > 0 and first[0] != "(none)" else None
        listen_port = int(first[1]) if len(first) > 1 else 51820
        pub_key = first[2] if len(first) > 2 and first[2] != "(none)" else None
        fwmark = first[3] if len(first) > 3 and first[3] != "(off)" else None

        peers: list[WGPeer] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            peer = WGPeer(
                public_key=parts[0],
                allowed_ips=parts[1].split(",") if parts[1] else [],
                endpoint=parts[2] if parts[2] and parts[2] != "(none)" else None,
                latest_handshake=_parse_dump_timestamp(parts[3]),
                transfer_rx=int(parts[4]) if parts[4] else 0,
                transfer_tx=int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                persistent_keepalive=int(parts[6]) if len(parts) > 6 and parts[6] and parts[6] != "(off)" else None,
            )
            peers.append(peer)

        return WGInterfaceState(
            name=interface,
            private_key=priv_key,
            public_key=pub_key,
            listen_port=listen_port,
            fwmark=fwmark,
            peers=peers,
        )


class WgMockAdapter(WireGuardAdapter):
    """Mock adapter for development and testing.

    Maintains an in-memory representation of WireGuard state.
    Useful when `wg` binary is not available or in CI.
    """

    def __init__(self):
        self._interfaces: dict[str, WGInterfaceState] = {}
        self._next_key_counter = 0

    def _make_mock_key(self) -> str:
        self._next_key_counter += 1
        return f"MOCK_{self._next_key_counter:040d}="

    async def interface_exists(self, interface: str) -> bool:
        return interface in self._interfaces

    async def get_interface_state(self, interface: str) -> WGInterfaceState:
        if interface not in self._interfaces:
            raise WireGuardInterfaceNotFound(interface)
        return self._interfaces[interface]

    async def add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: list[str],
        endpoint: Optional[str] = None,
        persistent_keepalive: Optional[int] = None,
    ) -> None:
        if interface not in self._interfaces:
            self._interfaces[interface] = WGInterfaceState(
                name=interface, public_key=self._make_mock_key()
            )
        state = self._interfaces[interface]
        for i, p in enumerate(state.peers):
            if p.public_key == public_key:
                state.peers[i] = WGPeer(
                    public_key=public_key,
                    allowed_ips=allowed_ips,
                    endpoint=endpoint,
                    persistent_keepalive=persistent_keepalive,
                )
                return
        state.peers.append(
            WGPeer(
                public_key=public_key,
                allowed_ips=allowed_ips,
                endpoint=endpoint,
                persistent_keepalive=persistent_keepalive,
            )
        )

    async def remove_peer(self, interface: str, public_key: str) -> None:
        if interface not in self._interfaces:
            return
        state = self._interfaces[interface]
        state.peers = [p for p in state.peers if p.public_key != public_key]

    async def update_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: Optional[list[str]] = None,
        endpoint: Optional[str] = None,
        persistent_keepalive: Optional[int] = None,
    ) -> None:
        if interface not in self._interfaces:
            return
        state = self._interfaces[interface]
        for p in state.peers:
            if p.public_key == public_key:
                if allowed_ips is not None:
                    p.allowed_ips = allowed_ips
                if endpoint is not None:
                    p.endpoint = endpoint
                if persistent_keepalive is not None:
                    p.persistent_keepalive = persistent_keepalive
                return

    async def set_peer_endpoint(
        self, interface: str, public_key: str, endpoint: str
    ) -> None:
        if interface not in self._interfaces:
            return
        for p in self._interfaces[interface].peers:
            if p.public_key == public_key:
                p.endpoint = endpoint
                return

    async def list_interfaces(self) -> list[str]:
        return list(self._interfaces.keys())
