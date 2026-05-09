import ipaddress

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device


def _network_address(subnet: str) -> ipaddress.IPv4Network:
    try:
        return ipaddress.IPv4Network(subnet, strict=False)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid subnet: {e}",
        )


def _hosts(net: ipaddress.IPv4Network) -> list[ipaddress.IPv4Address]:
    hosts = list(net.hosts())
    if net.prefixlen <= 30:
        return hosts
    return hosts


async def allocate_ip(
    session: AsyncSession, network_id, subnet: str
) -> str:
    net = _network_address(subnet)
    result = await session.execute(
        select(Device.ip_address).where(
            Device.network_id == network_id,
            Device.ip_address.isnot(None),
        )
    )
    used_ips = {row[0] for row in result}
    available = _hosts(net)
    gateway = str(available[0]) if available else None
    for host in available:
        ip_str = str(host)
        if ip_str == gateway:
            continue
        if ip_str not in used_ips:
            return ip_str
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="No available IP addresses in subnet",
    )


async def release_ip(
    session: AsyncSession, device_id
) -> None:
    result = await session.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if device:
        device.ip_address = None
        await session.flush()
