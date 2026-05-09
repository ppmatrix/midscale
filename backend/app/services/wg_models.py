from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WGPeer:
    """Represents a single peer's runtime state from a WireGuard interface."""

    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    endpoint: Optional[str] = None
    latest_handshake: Optional[datetime] = None
    transfer_rx: int = 0
    transfer_tx: int = 0
    persistent_keepalive: Optional[int] = None


@dataclass
class WGInterfaceState:
    """Represents the complete runtime state of a WireGuard interface."""

    name: str
    private_key: Optional[str] = None
    public_key: Optional[str] = None
    listen_port: int = 51820
    fwmark: Optional[str] = None
    peers: list[WGPeer] = field(default_factory=list)


@dataclass
class DesiredPeer:
    """Desired state for a single peer from the database perspective."""

    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    remove: bool = False


@dataclass
class PeerDiff:
    """Result of comparing desired vs actual peer state."""

    to_add: list[DesiredPeer] = field(default_factory=list)
    to_update: list[DesiredPeer] = field(default_factory=list)
    to_remove: list[DesiredPeer] = field(default_factory=list)


@dataclass
class InterfaceDiff:
    """Complete diff for an interface reconciliation."""

    interface: str
    peer_diff: PeerDiff = field(default_factory=PeerDiff)
    needs_reconfig: bool = False


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation cycle for one interface."""

    interface: str
    peers_added: int = 0
    peers_removed: int = 0
    peers_updated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
