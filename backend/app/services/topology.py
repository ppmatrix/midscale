"""Topology generators — produce pure peer connectivity plans.

Each topology type implements a deterministic, I/O-free algorithm
that maps device state to a peer connectivity plan.
"""

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ── Pure state types (no ORM dependencies) ──────────────────────────


class TopologyType(str, enum.Enum):
    STAR = "star"
    MESH = "mesh"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class DeviceState:
    """Read-only device snapshot for topology planning."""

    id: str
    public_key: str
    ip_address: str
    dns_enabled: bool = False
    exit_node_id: Optional[str] = None


@dataclass(frozen=True)
class NetworkState:
    """Read-only network snapshot for topology planning."""

    subnet: str
    topology: Optional[str] = None


@dataclass
class PeerPlan:
    """A single peer entry in a device's topology plan."""

    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    endpoint: Optional[str] = None
    endpoint_port: Optional[int] = None
    persistent_keepalive: Optional[int] = None
    relay_fallback: bool = False


@dataclass
class TopologyPlan:
    """Pure connectivity plan for a single device.

    Contains everything needed to render a WireGuard configuration
    for one device. No private keys — those are injected by the
    config renderer.
    """

    device_id: str
    address: str
    subnet: str
    dns_servers: Optional[list[str]] = None
    peers: list[PeerPlan] = field(default_factory=list)
    mtu: Optional[int] = None


# ── Legacy types (backward compatible) ──────────────────────────────


@dataclass
class PeerConfig:
    """Configuration for a single WireGuard peer in a device config."""

    public_key: str
    allowed_ips: list[str] = field(default_factory=list)
    endpoint: Optional[str] = None
    endpoint_port: Optional[int] = None
    persistent_keepalive: Optional[int] = None


@dataclass
class WireGuardConfig:
    """Complete structured WireGuard configuration for a device."""

    private_key: str
    address: str
    subnet: str
    listen_port: Optional[int] = None
    dns_servers: Optional[list[str]] = None
    peers: list[PeerConfig] = field(default_factory=list)
    mtu: Optional[int] = None

    def to_ini(self) -> str:
        lines: list[str] = []
        lines.append("[Interface]")
        lines.append(f"PrivateKey = {self.private_key}")
        net = __import__("ipaddress").IPv4Network(self.subnet, strict=False)
        lines.append(f"Address = {self.address}/{net.prefixlen}")
        if self.listen_port:
            lines.append(f"ListenPort = {self.listen_port}")
        if self.dns_servers:
            lines.append(f"DNS = {', '.join(self.dns_servers)}")
        if self.mtu:
            lines.append(f"MTU = {self.mtu}")
        lines.append("")

        for peer in self.peers:
            lines.append("[Peer]")
            lines.append(f"PublicKey = {peer.public_key}")
            if peer.endpoint:
                port = peer.endpoint_port or 51820
                lines.append(f"Endpoint = {peer.endpoint}:{port}")
            if peer.allowed_ips:
                lines.append(f"AllowedIPs = {', '.join(peer.allowed_ips)}")
            if peer.persistent_keepalive is not None:
                lines.append(f"PersistentKeepalive = {peer.persistent_keepalive}")
            lines.append("")

        return "\n".join(lines)


# ── Topology generator base ─────────────────────────────────────────


class TopologyGenerator(ABC):
    """Abstract interface for generating peer connectivity plans.

    Implementations must be:
    - Deterministic (same inputs → same plan)
    - I/O-free (no database queries, no decryption)
    - Non-mutating (do not modify input objects)
    """

    @abstractmethod
    def generate_plan(
        self,
        device: DeviceState,
        all_devices: list[DeviceState],
        network: NetworkState,
        server_device_id: str,
        routes_by_device: Optional[dict[str, list[str]]] = None,
        endpoints_by_device: Optional[dict[str, list]] = None,
    ) -> TopologyPlan:
        """Generate a pure topology plan for one device.

        Parameters
        ----------
        device : DeviceState
            The device to generate a plan for.
        all_devices : list[DeviceState]
            All active devices in the network (including server and self).
        network : NetworkState
            Network configuration.
        server_device_id : str
            The ID of the server/hub device.
        routes_by_device : dict or None
            Maps device_id (str) to list of CIDR prefixes the device has
            advertised and been approved for.
        endpoints_by_device : dict or None
            Maps device_id (str) to list of DeviceEndpoint objects
            (active, ordered by priority).

        Returns
        -------
        TopologyPlan
            Pure connectivity plan for the device.
        """

    async def generate_configs(
        self,
        devices: list,
        server_device,
        network,
        dns_servers: Optional[list[str]] = None,
        routes_by_device: Optional[dict[str, list[str]]] = None,
        endpoints_by_device: Optional[dict[str, list]] = None,
    ) -> dict:
        """Legacy entrypoint: generate WireGuardConfig for every device.

        Converts ORM objects to state objects, calls ``generate_plan``
        for each device, then wraps results into ``WireGuardConfig``
        (which includes decrypted private keys).

        This method exists for backward compatibility. New code should
        call ``generate_plan`` directly.
        """
        from app.core.security import decrypt_private_key
        from app.config import settings

        configs: dict = {}
        server_endpoint = settings.wireguard_server_endpoint or "localhost"
        server_port = settings.wireguard_port

        routes_by_device = routes_by_device or {}
        endpoints_by_device = endpoints_by_device or {}

        server_id = str(server_device.id)
        all_devices = [
            DeviceState(
                id=str(d.id),
                public_key=d.public_key or "",
                ip_address=d.ip_address or "",
                dns_enabled=d.dns_enabled,
                exit_node_id=str(d.exit_node_id) if d.exit_node_id else None,
            )
            for d in devices
            if d.public_key and d.ip_address
        ]

        network_state = NetworkState(subnet=network.subnet)

        for d in devices:
            if not d.private_key_enc or not d.ip_address or not d.public_key:
                continue

            dev_state = DeviceState(
                id=str(d.id),
                public_key=d.public_key,
                ip_address=d.ip_address,
                dns_enabled=d.dns_enabled,
                exit_node_id=str(d.exit_node_id) if d.exit_node_id else None,
            )

            plan = self.generate_plan(
                device=dev_state,
                all_devices=all_devices,
                network=network_state,
                server_device_id=server_id,
                routes_by_device=routes_by_device,
                endpoints_by_device=endpoints_by_device,
            )

            private = decrypt_private_key(d.private_key_enc)
            wg_peers: list[PeerConfig] = []
            for pp in plan.peers:
                wg_peers.append(
                    PeerConfig(
                        public_key=pp.public_key,
                        allowed_ips=pp.allowed_ips,
                        endpoint=pp.endpoint,
                        endpoint_port=pp.endpoint_port,
                        persistent_keepalive=pp.persistent_keepalive,
                    )
                )

            dev_dns = dns_servers if d.dns_enabled else None
            configs[d.id] = WireGuardConfig(
                private_key=private,
                address=d.ip_address,
                subnet=network.subnet,
                listen_port=server_port if str(d.id) == server_id else None,
                dns_servers=dev_dns,
                peers=wg_peers,
            )

        return configs


# ── Helpers ─────────────────────────────────────────────────────────


def _sort_endpoints(eps: list) -> list:
    return sorted(
        eps,
        key=lambda e: (-getattr(e, "priority", 100), -getattr(e, "last_seen", 0).timestamp() if getattr(e, "last_seen", None) else 0),
    )


def _best_endpoint(eps: list) -> tuple[Optional[str], Optional[int]]:
    active = [e for e in eps if getattr(e, "is_active", True)]
    if not active:
        return None, None
    best = _sort_endpoints(active)[0]
    return best.endpoint, best.port


# ── Star Topology ───────────────────────────────────────────────────


class StarTopologyGenerator(TopologyGenerator):
    """Star topology — all peers connect to the server hub.

    Each client device has one peer: the server.
    The server has one peer per client device.
    """

    def generate_plan(
        self,
        device: DeviceState,
        all_devices: list[DeviceState],
        network: NetworkState,
        server_device_id: str,
        routes_by_device: Optional[dict[str, list[str]]] = None,
        endpoints_by_device: Optional[dict[str, list]] = None,
    ) -> TopologyPlan:
        from app.config import settings

        routes_by_device = routes_by_device or {}
        server_endpoint = settings.wireguard_server_endpoint or "localhost"
        server_port = settings.wireguard_port

        # Find the server
        server = None
        for d in all_devices:
            if d.id == server_device_id:
                server = d
                break
        if not server:
            return TopologyPlan(
                device_id=device.id,
                address=device.ip_address,
                subnet=network.subnet,
            )

        peers: list[PeerPlan] = []

        if device.id == server_device_id:
            # Server config: one peer per client
            for other in all_devices:
                if other.id == server_device_id:
                    continue
                allowed_ips = [f"{other.ip_address}/32"]
                extra = routes_by_device.get(other.id, [])
                allowed_ips.extend(extra)
                peers.append(
                    PeerPlan(
                        public_key=other.public_key,
                        allowed_ips=allowed_ips,
                    )
                )
        else:
            # Client config: one peer (the server)
            # Also add exit node peers
            allowed_ips = [network.subnet]
            peers.append(
                PeerPlan(
                    public_key=server.public_key,
                    allowed_ips=allowed_ips,
                    endpoint=server_endpoint,
                    endpoint_port=server_port,
                    persistent_keepalive=25,
                )
            )

            # Exit node peer
            if device.exit_node_id and device.exit_node_id != server_device_id:
                exit_dev = [d for d in all_devices if d.id == device.exit_node_id]
                if exit_dev:
                    ed = exit_dev[0]
                    if ed.public_key and not any(p.public_key == ed.public_key for p in peers):
                        peers.append(
                            PeerPlan(
                                public_key=ed.public_key,
                                allowed_ips=["0.0.0.0/0", "::/0"],
                            )
                        )

        return TopologyPlan(
            device_id=device.id,
            address=device.ip_address,
            subnet=network.subnet,
            peers=peers,
        )


# ── Mesh Topology ───────────────────────────────────────────────────


class MeshTopologyGenerator(TopologyGenerator):
    """Mesh topology — every device connects to every other device directly.

    Each device has a peer entry for every other device in the network
    with their endpoint candidates. The server/hub is included as a
    routing peer for the subnet but not as the sole connection point.
    """

    def generate_plan(
        self,
        device: DeviceState,
        all_devices: list[DeviceState],
        network: NetworkState,
        server_device_id: str,
        routes_by_device: Optional[dict[str, list[str]]] = None,
        endpoints_by_device: Optional[dict[str, list]] = None,
    ) -> TopologyPlan:
        from app.config import settings

        routes_by_device = routes_by_device or {}
        endpoints_by_device = endpoints_by_device or {}
        server_endpoint = settings.wireguard_server_endpoint or "localhost"
        server_port = settings.wireguard_port

        peers: list[PeerPlan] = []

        for other in all_devices:
            if other.id == device.id:
                continue

            allowed_ips = [f"{other.ip_address}/32"]
            extra = routes_by_device.get(other.id, [])
            allowed_ips.extend(extra)

            eps = endpoints_by_device.get(other.id, [])
            ep, ep_port = _best_endpoint(eps)

            use_ep = ep or (server_endpoint if other.id == server_device_id else None)
            use_port = ep_port or (server_port if other.id == server_device_id else None)

            peers.append(
                PeerPlan(
                    public_key=other.public_key,
                    allowed_ips=allowed_ips,
                    endpoint=use_ep,
                    endpoint_port=use_port,
                    persistent_keepalive=25,
                    relay_fallback=(not eps),
                )
            )

        # Exit node peer (if different from server and not already included)
        if device.exit_node_id and device.exit_node_id != server_device_id:
            exit_dev = [d for d in all_devices if d.id == device.exit_node_id]
            if exit_dev:
                ed = exit_dev[0]
                if ed.public_key and not any(p.public_key == ed.public_key for p in peers):
                    peers.append(
                        PeerPlan(
                            public_key=ed.public_key,
                            allowed_ips=["0.0.0.0/0", "::/0"],
                        )
                    )

        return TopologyPlan(
            device_id=device.id,
            address=device.ip_address,
            subnet=network.subnet,
            peers=peers,
        )


# ── Hybrid Topology ─────────────────────────────────────────────────


class HybridTopologyGenerator(TopologyGenerator):
    """Hybrid topology — direct peer-to-peer when endpoints available,
    hub fallback when not.

    Devices that have reported active endpoints get direct peer entries.
    Devices without known endpoints connect only to the hub, which
    relays traffic until a direct path is established.
    """

    def generate_plan(
        self,
        device: DeviceState,
        all_devices: list[DeviceState],
        network: NetworkState,
        server_device_id: str,
        routes_by_device: Optional[dict[str, list[str]]] = None,
        endpoints_by_device: Optional[dict[str, list]] = None,
    ) -> TopologyPlan:
        from app.config import settings

        routes_by_device = routes_by_device or {}
        endpoints_by_device = endpoints_by_device or {}
        server_endpoint = settings.wireguard_server_endpoint or "localhost"
        server_port = settings.wireguard_port

        peers: list[PeerPlan] = []

        for other in all_devices:
            if other.id == device.id:
                continue

            allowed_ips = [f"{other.ip_address}/32"]
            extra = routes_by_device.get(other.id, [])
            allowed_ips.extend(extra)

            eps = endpoints_by_device.get(other.id, [])
            ep, ep_port = _best_endpoint(eps)

            if other.id == server_device_id:
                peers.append(
                    PeerPlan(
                        public_key=other.public_key,
                        allowed_ips=[network.subnet],
                        endpoint=ep or server_endpoint,
                        endpoint_port=ep_port or server_port,
                        persistent_keepalive=25,
                    )
                )
            elif ep:
                peers.append(
                    PeerPlan(
                        public_key=other.public_key,
                        allowed_ips=allowed_ips,
                        endpoint=ep,
                        endpoint_port=ep_port,
                        persistent_keepalive=25,
                    )
                )
            else:
                peers.append(
                    PeerPlan(
                        public_key=other.public_key,
                        allowed_ips=allowed_ips,
                        relay_fallback=True,
                    )
                )

        # Exit node peer
        if device.exit_node_id and device.exit_node_id != server_device_id:
            exit_dev = [d for d in all_devices if d.id == device.exit_node_id]
            if exit_dev:
                ed = exit_dev[0]
                if ed.public_key and not any(p.public_key == ed.public_key for p in peers):
                    peers.append(
                        PeerPlan(
                            public_key=ed.public_key,
                            allowed_ips=["0.0.0.0/0", "::/0"],
                        )
                    )

        return TopologyPlan(
            device_id=device.id,
            address=device.ip_address,
            subnet=network.subnet,
            peers=peers,
        )
