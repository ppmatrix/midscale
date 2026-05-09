"""Build pure state objects from database models.

Separates the concerns of database access and state computation.
Pipeline: DB models → NetworkState/DeviceState → TopologyPlan → ConfigV2Response.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.network import Network
from app.models.dns import DNSEntry
from app.models.route import AdvertisedRoute
from app.models.endpoint import DeviceEndpoint
from app.services.topology import DeviceState, NetworkState


async def build_network_state(session: AsyncSession, network_id) -> NetworkState:
    """Fetch network and return a pure NetworkState."""
    net_result = await session.execute(
        select(Network).where(Network.id == network_id)
    )
    network = net_result.scalar_one()
    return NetworkState(
        subnet=network.subnet,
        topology=network.topology,
    )


async def build_device_states(
    session: AsyncSession, network_id
) -> tuple[list[DeviceState], Optional[str]]:
    """Fetch all active devices in a network and return DeviceState list + server id."""
    dev_result = await session.execute(
        select(Device).where(
            Device.network_id == network_id,
            Device.is_active,
            Device.public_key.isnot(None),
            Device.ip_address.isnot(None),
        )
    )
    devices = dev_result.scalars().all()

    server_device_id: Optional[str] = None
    states: list[DeviceState] = []
    for d in devices:
        sid = str(d.id)
        if d.name == "__midscale_server__":
            server_device_id = sid
        states.append(
            DeviceState(
                id=sid,
                public_key=d.public_key,
                ip_address=d.ip_address,
                dns_enabled=d.dns_enabled,
                exit_node_id=str(d.exit_node_id) if d.exit_node_id else None,
            )
        )
    return states, server_device_id


async def build_dns_servers(session: AsyncSession, network_id) -> Optional[list[str]]:
    """Fetch DNS entries for a network."""
    dns_result = await session.execute(
        select(DNSEntry).where(DNSEntry.network_id == network_id)
    )
    dns_entries = dns_result.scalars().all()
    return list({e.address for e in dns_entries}) if dns_entries else None


async def build_routes_by_device(
    session: AsyncSession, network_id
) -> tuple[list[str], dict[str, list[str]]]:
    """Fetch approved routes for a network.

    Returns (routes_list, routes_by_device_dict).
    """
    route_result = await session.execute(
        select(AdvertisedRoute).where(
            AdvertisedRoute.network_id == network_id,
            AdvertisedRoute.approved,
            AdvertisedRoute.enabled,
        )
    )
    route_rows = route_result.scalars().all()
    routes = [r.prefix for r in route_rows]
    routes_by_device: dict[str, list[str]] = {}
    for r in route_rows:
        did = str(r.device_id)
        if did not in routes_by_device:
            routes_by_device[did] = []
        routes_by_device[did].append(r.prefix)
    return routes, routes_by_device


async def build_endpoints_by_device(
    session: AsyncSession, network_id
) -> dict[str, list[DeviceEndpoint]]:
    """Fetch active endpoints for all devices in a network, grouped by device_id."""
    ep_result = await session.execute(
        select(DeviceEndpoint).where(
            DeviceEndpoint.is_active,
            DeviceEndpoint.device_id.in_(
                select(Device.id).where(
                    Device.network_id == network_id,
                    Device.is_active,
                )
            ),
        ).order_by(DeviceEndpoint.priority.desc(), DeviceEndpoint.last_seen.desc())
    )
    eps_by_device: dict[str, list[DeviceEndpoint]] = {}
    for ep in ep_result.scalars().all():
        did = str(ep.device_id)
        if did not in eps_by_device:
            eps_by_device[did] = []
        eps_by_device[did].append(ep)
    return eps_by_device
