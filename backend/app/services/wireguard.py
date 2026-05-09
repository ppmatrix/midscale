import asyncio
import ipaddress
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import encrypt_private_key, decrypt_private_key
from app.models.device import Device
from app.models.network import Network
from app.models.dns import DNSEntry
from app.models.route import AdvertisedRoute
from app.models.endpoint import DeviceEndpoint
from app.schemas.device import DeviceConfigV2Response, PeerInfo, EndpointCandidate
from app.services.topology import (
    StarTopologyGenerator,
    MeshTopologyGenerator,
    HybridTopologyGenerator,
    TopologyType,
    TopologyGenerator,
    DeviceState,
    NetworkState,
)
from app.services.network_state import (
    build_network_state,
    build_device_states,
    build_dns_servers,
    build_routes_by_device,
    build_endpoints_by_device,
)
from app.services.config_renderer import render_config, compute_config_hash
from app.services.endpoint_scoring import compute_endpoint_score, select_best_endpoint, sort_endpoint_candidates
from app.services.wg_adapter import WgCliAdapter, WgMockAdapter

logger = structlog.get_logger(__name__)


def _get_topology_generator(network: Optional[Network] = None) -> TopologyGenerator:
    ttype_str = network.topology if (network and network.topology) else settings.wireguard_topology
    return _get_topology_generator_from_state(NetworkState(subnet="", topology=ttype_str))


def _get_topology_generator_from_state(network: Optional[NetworkState] = None) -> TopologyGenerator:
    ttype_str = network.topology if (network and network.topology) else settings.wireguard_topology
    ttype = TopologyType(ttype_str)
    if ttype == TopologyType.STAR:
        return StarTopologyGenerator()
    elif ttype == TopologyType.MESH:
        return MeshTopologyGenerator()
    elif ttype == TopologyType.HYBRID:
        return HybridTopologyGenerator()
    return StarTopologyGenerator()


def _create_adapter():
    try:
        import subprocess
        subprocess.run(
            [settings.wireguard_binary, "version"],
            capture_output=True, timeout=5,
        )
        return WgCliAdapter(wg_binary=settings.wireguard_binary)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("wg binary not available, using mock adapter")
        return WgMockAdapter()


async def _run_wg(*args: str) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        "wg",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode().strip(), stderr.decode().strip()


async def _run_wg_with_input(input_data: str, *args: str) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        "wg",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=input_data.encode())
    return stdout.decode().strip(), stderr.decode().strip()


async def generate_keypair() -> tuple[str, str]:
    try:
        private_key, _ = await _run_wg("genkey")
        public_key, _ = await _run_wg_with_input(private_key, "pubkey")
        return private_key, public_key
    except FileNotFoundError:
        logger.warning("wg binary not found — simulating key generation")
        private_key = "MOCK_" + "a" * 44
        public_key = "MOCK_" + "b" * 44
        return private_key, public_key


def generate_device_config(
    private_key: str,
    device_ip: str,
    subnet: str,
    server_public_key: str,
    server_endpoint: str,
    server_port: int,
    dns_servers: Optional[list[str]] = None,
) -> str:
    net = ipaddress.IPv4Network(subnet, strict=False)
    prefixlen = net.prefixlen
    dns_line = ""
    if dns_servers:
        dns_line = f"DNS = {', '.join(dns_servers)}\n"
    config = f"""[Interface]
PrivateKey = {private_key}
Address = {device_ip}/{prefixlen}
{dns_line}

[Peer]
PublicKey = {server_public_key}
Endpoint = {server_endpoint}:{server_port}
AllowedIPs = {subnet}
PersistentKeepalive = 25
"""
    return config


def generate_server_config(
    private_key: str,
    server_ip: str,
    subnet: str,
    listen_port: int,
    peers: list[dict],
) -> str:
    config = f"""[Interface]
PrivateKey = {private_key}
Address = {server_ip}/{ipaddress.IPv4Network(subnet, strict=False).prefixlen}
ListenPort = {listen_port}
SaveConfig = false

"""
    for peer in peers:
        allowed_ips = peer.get("allowed_ips", peer["ip_address"])
        config += f"""[Peer]
PublicKey = {peer['public_key']}
AllowedIPs = {allowed_ips}

"""
    return config


async def get_device_config(session: AsyncSession, device_id) -> str:
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    if not device.public_key or not device.private_key_enc or not device.ip_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device keys not yet generated",
        )
    network_result = await session.execute(
        select(Network).where(Network.id == device.network_id)
    )
    network = network_result.scalar_one()

    dev_result = await session.execute(
        select(Device).where(
            Device.network_id == device.network_id,
            Device.is_active,
            Device.public_key.isnot(None),
            Device.ip_address.isnot(None),
        )
    )
    all_devices = dev_result.scalars().all()

    server_device = None
    for d in all_devices:
        if d.name == "__midscale_server__":
            server_device = d
            break
    if not server_device:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server device not found in network",
        )

    dns_servers = None
    if device.dns_enabled:
        dns_result = await session.execute(
            select(DNSEntry).where(DNSEntry.network_id == device.network_id)
        )
        dns_entries = dns_result.scalars().all()
        if dns_entries:
            dns_servers = list({e.address for e in dns_entries})

    route_result = await session.execute(
        select(AdvertisedRoute).where(
            AdvertisedRoute.network_id == device.network_id,
            AdvertisedRoute.approved,
            AdvertisedRoute.enabled,
        )
    )
    routes = route_result.scalars().all()
    routes_by_device: dict[str, list[str]] = {}
    for r in routes:
        did = str(r.device_id)
        if did not in routes_by_device:
            routes_by_device[did] = []
        routes_by_device[did].append(r.prefix)

    generator = _get_topology_generator(network)
    configs = await generator.generate_configs(
        devices=all_devices,
        server_device=server_device,
        network=network,
        dns_servers=dns_servers,
        routes_by_device=routes_by_device,
    )

    config = configs.get(device.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate device config",
        )
    return config.to_ini()


async def get_server_public_key(session: AsyncSession) -> Optional[str]:
    keys_result = await session.execute(
        select(Device.public_key).where(
            Device.name == "__midscale_server__",
            Device.public_key.isnot(None),
        )
    )
    key = keys_result.scalar_one_or_none()
    return key


async def save_device_keys(
    session: AsyncSession, device: Device
) -> None:
    private_key, public_key = await generate_keypair()
    device.private_key_enc = encrypt_private_key(private_key)
    device.public_key = public_key
    await session.flush()


async def build_config_v2(
    session: AsyncSession, device: Device
) -> DeviceConfigV2Response:
    network_state = await build_network_state(session, device.network_id)
    device_states, server_device_id = await build_device_states(session, device.network_id)
    dns_servers = await build_dns_servers(session, device.network_id) if device.dns_enabled else None
    routes, routes_by_device = await build_routes_by_device(session, device.network_id)
    eps_by_device = await build_endpoints_by_device(session, device.network_id)

    ttype_str = network_state.topology or settings.wireguard_topology
    is_mesh_or_hybrid = ttype_str in ("mesh", "hybrid")

    current_dev_state = None
    for ds in device_states:
        if ds.id == str(device.id):
            current_dev_state = ds
            break
    if not current_dev_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found in active devices",
        )

    generator = _get_topology_generator_from_state(network_state)
    plan = generator.generate_plan(
        device=current_dev_state,
        all_devices=device_states,
        network=network_state,
        server_device_id=server_device_id or "",
        routes_by_device=routes_by_device,
        endpoints_by_device=eps_by_device,
    )

    peers: list[PeerInfo] = []
    pk_to_device_id: dict[str, str] = {ds.public_key: ds.id for ds in device_states}
    for pp in plan.peers:
        endpoint_candidates: list[EndpointCandidate] = []
        best_ep = pp.endpoint
        best_port = pp.endpoint_port
        relay_fallback = pp.relay_fallback

        peer_device_id = pk_to_device_id.get(pp.public_key, "")
        d_eps = eps_by_device.get(peer_device_id, [])
        if d_eps and is_mesh_or_hybrid:
            sorted_eps = sort_endpoint_candidates(d_eps)
            best = select_best_endpoint(d_eps)
            best_id = str(best.id) if best else None
            for ep_obj in sorted_eps:
                is_preferred = str(ep_obj.id) == best_id
                endpoint_candidates.append(
                    EndpointCandidate(
                        endpoint=ep_obj.endpoint,
                        port=ep_obj.port,
                        source=ep_obj.source,
                        priority=ep_obj.priority,
                        last_seen_at=ep_obj.last_seen.isoformat() if ep_obj.last_seen else None,
                        local_ip=ep_obj.local_ip,
                        public_ip=ep_obj.public_ip,
                        reachable=ep_obj.reachable,
                        latency_ms=ep_obj.latency_ms,
                        score=ep_obj.score,
                        preferred=is_preferred,
                    )
                )
                if best_ep is None or is_preferred:
                    best_ep = ep_obj.endpoint
                    best_port = ep_obj.port
                    relay_fallback = not ep_obj.reachable

        peer = PeerInfo(
            public_key=pp.public_key,
            allowed_ips=pp.allowed_ips,
            endpoint=best_ep or pp.endpoint,
            endpoint_port=best_port or pp.endpoint_port,
            persistent_keepalive=pp.persistent_keepalive,
            endpoint_candidates=endpoint_candidates if is_mesh_or_hybrid else [],
            relay_fallback=relay_fallback and is_mesh_or_hybrid,
        )
        peers.append(peer)

    net = ipaddress.IPv4Network(network_state.subnet, strict=False)
    interface = {
        "address": f"{current_dev_state.ip_address}/{net.prefixlen}",
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
        "exit_node": str(device.exit_node_id) if device.exit_node_id else None,
        "version": "2",
        "config_version": "2",
        "schema_version": "1",
    }
    config_hash = compute_config_hash(config_data)

    return DeviceConfigV2Response(
        interface=interface,
        peers=peers,
        routes=routes,
        exit_node=str(device.exit_node_id) if device.exit_node_id else None,
        version="2",
        config_version="2",
        schema_version="1",
        min_daemon_version="0.1.0",
        revision=revision,
        generated_at=generated_at,
        hash=config_hash,
    )


async def sync_wireguard_interface(session: AsyncSession, network_id) -> None:
    adapter = _create_adapter()
    result = await session.execute(
        select(Network).where(Network.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        return
    interface = network.interface_name or settings.wireguard_interface

    try:
        if not await adapter.interface_exists(interface):
            logger.info(
                "interface does not exist — skipping sync",
                interface=interface,
            )
            return
    except Exception:
        logger.info(
            "cannot check interface — skipping sync",
            interface=interface,
        )
        return

    device_result = await session.execute(
        select(Device).where(
            Device.network_id == network_id,
            Device.is_active,
            Device.public_key.isnot(None),
            Device.ip_address.isnot(None),
        )
    )
    devices = device_result.scalars().all()

    for dev in devices:
        if dev.name == "__midscale_server__":
            continue
        try:
            await adapter.add_peer(
                interface=interface,
                public_key=dev.public_key,
                allowed_ips=[f"{dev.ip_address}/32"],
            )
        except Exception as e:
            logger.error(
                "failed to sync peer",
                peer_name=dev.name,
                interface=interface,
                error=str(e),
            )
