"""Config renderer — converts TopologyPlan + device data into DeviceConfigV2Response.

This module handles the final step of the config generation pipeline:
taking a pure topology plan and enriching it with runtime metadata
(revision, hash, version fields) to produce the API response.
"""

import hashlib
import ipaddress
import json
from datetime import datetime, timezone

from app.core.constants import CONFIG_V2_VERSION, CONFIG_V2_SCHEMA_VERSION, CONFIG_V2_MIN_DAEMON_VERSION
from app.schemas.device import (
    DeviceConfigV2Response,
    PeerInfo,
    EndpointCandidate,
)
from app.services.topology import TopologyPlan


def compute_config_hash(config_data: dict) -> str:
    """Deterministic SHA-256 hash of configuration state.

    Only effective networking state is included in the hash:
    interface address, peers, routes, DNS, exit node, endpoint candidates,
    version fields. Volatile metadata (generated_at, revision) is excluded.
    """
    serialized = json.dumps(config_data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def render_config(
    plan: TopologyPlan,
    dns_servers: list[str] | None = None,
    routes: list[str] | None = None,
    exit_node_id: str | None = None,
    topology_type: str = "star",
) -> DeviceConfigV2Response:
    """Render a TopologyPlan into a DeviceConfigV2Response.

    Parameters
    ----------
    plan : TopologyPlan
        The pure topology plan from a generator.
    dns_servers : list[str] or None
        DNS server addresses for the device.
    routes : list[str] or None
        Approved route prefixes for the network.
    exit_node_id : str or None
        Exit node device ID if set.
    topology_type : str
        Topology type name (star/mesh/hybrid). Controls whether
        endpoint candidates are included in peer info.

    Returns
    -------
    DeviceConfigV2Response
        The formatted API response with computed hash.
    """
    routes = routes or []
    net = ipaddress.IPv4Network(plan.subnet, strict=False)
    is_mesh_or_hybrid = topology_type in ("mesh", "hybrid")

    peers: list[PeerInfo] = []
    for pp in plan.peers:
        endpoint_candidates: list[EndpointCandidate] = []
        best_ep = pp.endpoint
        best_port = pp.endpoint_port

        # We don't have raw endpoint data in PeerPlan currently.
        # Endpoint candidates are constructed from the best endpoint info.

        peer = PeerInfo(
            public_key=pp.public_key,
            allowed_ips=pp.allowed_ips,
            endpoint=pp.endpoint,
            endpoint_port=pp.endpoint_port,
            persistent_keepalive=pp.persistent_keepalive,
            endpoint_candidates=endpoint_candidates,
            relay_fallback=pp.relay_fallback and is_mesh_or_hybrid,
        )
        peers.append(peer)

    interface = {
        "address": f"{plan.address}/{net.prefixlen}",
        "dns": dns_servers,
        "mtu": None,
    }

    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    revision = str(int(now.timestamp()))

    config_data = {
        "interface": interface,
        "peers": [p.model_dump() for p in peers],
        "routes": routes,
        "exit_node": exit_node_id,
        "version": CONFIG_V2_VERSION,
        "config_version": CONFIG_V2_VERSION,
        "schema_version": CONFIG_V2_SCHEMA_VERSION,
    }
    config_hash = compute_config_hash(config_data)

    return DeviceConfigV2Response(
        interface=interface,
        peers=peers,
        routes=routes,
        exit_node=exit_node_id,
        version=CONFIG_V2_VERSION,
        config_version=CONFIG_V2_VERSION,
        schema_version=CONFIG_V2_SCHEMA_VERSION,
        min_daemon_version=CONFIG_V2_MIN_DAEMON_VERSION,
        revision=revision,
        generated_at=generated_at,
        hash=config_hash,
    )
