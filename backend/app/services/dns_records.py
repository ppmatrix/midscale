import ipaddress
import re
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.device import Device
from app.models.network import Network
from app.models.dns import DNSEntry
from app.services.dns_provider import DNSProvider, DNSRecord, ZoneData

logger = structlog.get_logger(__name__)

_DNS_LABEL_CLEAN = re.compile(r"[^a-zA-Z0-9\-]")
_MULTI_DASH = re.compile(r"-+")


def sanitize_dns_name(name: str) -> str:
    clean = _DNS_LABEL_CLEAN.sub("-", name.lower())
    clean = _MULTI_DASH.sub("-", clean)
    return clean.strip("-") or "unnamed"


def _make_serial() -> int:
    now = datetime.now(timezone.utc)
    return int(now.strftime("%Y%m%d%H%M%S"))


def _reverse_zone_origin(subnet: str) -> Optional[str]:
    try:
        net = ipaddress.IPv4Network(subnet, strict=False)
    except ValueError:
        return None
    if net.prefixlen < 8:
        return None
    host_bytes = net.network_address.packed[: net.prefixlen // 8]
    octets = list(net.network_address.packed)
    if net.prefixlen >= 24:
        prefix = f"{octets[2]}.{octets[1]}.{octets[0]}"
    elif net.prefixlen >= 16:
        prefix = f"{octets[1]}.{octets[0]}"
    elif net.prefixlen >= 8:
        prefix = f"{octets[0]}"
    else:
        return None
    return f"{prefix}.in-addr.arpa"


def _reverse_record_name(
    ip_str: str, subnet: str
) -> str:
    ip = ipaddress.IPv4Address(ip_str)
    net = ipaddress.IPv4Network(subnet, strict=False)
    octets = list(ip.packed)
    if net.prefixlen >= 24:
        return str(octets[3])
    elif net.prefixlen >= 16:
        return f"{octets[3]}.{octets[2]}"
    elif net.prefixlen >= 8:
        return f"{octets[3]}.{octets[2]}.{octets[1]}"
    return ip_str


async def build_network_zone(
    session: AsyncSession,
    network: Network,
    devices: list[Device],
    dns_entries: list[DNSEntry],
) -> Optional[ZoneData]:
    base_domain = settings.dns_domain
    zone_name = sanitize_dns_name(network.name)
    origin = f"{zone_name}.{base_domain}"

    records: list[DNSRecord] = []

    ns1_name = f"ns1.{origin}"
    records.append(DNSRecord(name="@", record_type="NS", value=ns1_name))

    for device in devices:
        if not device.ip_address or not device.is_active:
            continue
        name = sanitize_dns_name(device.name)
        records.append(
            DNSRecord(name=name, record_type="A", value=device.ip_address)
        )

    for entry in dns_entries:
        domain = entry.domain.rstrip(".")
        if domain.endswith(f".{origin}") or "." not in domain:
            label = domain.replace(f".{origin}", "") if domain.endswith(f".{origin}") else domain
            label = label or "@"
            records.append(
                DNSRecord(name=label, record_type="A", value=entry.address)
            )

    if not [r for r in records if r.record_type != "NS"]:
        return None

    return ZoneData(
        origin=origin,
        records=records,
        serial=_make_serial(),
        ttl=settings.dns_default_ttl,
    )


async def build_reverse_zone(
    session: AsyncSession,
    network: Network,
    devices: list[Device],
) -> Optional[ZoneData]:
    subnet = network.subnet
    origin = _reverse_zone_origin(subnet)
    if not origin:
        return None

    records: list[DNSRecord] = []

    base_domain = settings.dns_domain
    zone_name = sanitize_dns_name(network.name)
    forward_origin = f"{zone_name}.{base_domain}"

    for device in devices:
        if not device.ip_address or not device.is_active:
            continue
        rev_name = _reverse_record_name(device.ip_address, subnet)
        fwd_name = f"{sanitize_dns_name(device.name)}.{forward_origin}"
        records.append(
            DNSRecord(name=rev_name, record_type="PTR", value=fwd_name)
        )

    if not records:
        return None

    return ZoneData(
        origin=origin,
        records=records,
        serial=_make_serial(),
        ttl=settings.dns_default_ttl,
    )


async def sync_network_dns(
    session: AsyncSession,
    network_id,
    dns_provider: DNSProvider,
) -> None:
    net_result = await session.execute(
        select(Network).where(Network.id == network_id)
    )
    network = net_result.scalar_one_or_none()
    if not network:
        return

    dev_result = await session.execute(
        select(Device).where(
            Device.network_id == network_id,
            Device.is_active,
            Device.ip_address.isnot(None),
        )
    )
    devices = dev_result.scalars().all()

    dns_result = await session.execute(
        select(DNSEntry).where(DNSEntry.network_id == network_id)
    )
    dns_entries = dns_result.scalars().all()

    forward_zone = await build_network_zone(
        session, network, devices, dns_entries
    )
    if forward_zone:
        await dns_provider.ensure_zone(forward_zone)
    else:
        base_domain = settings.dns_domain
        zone_name = sanitize_dns_name(network.name)
        origin = f"{zone_name}.{base_domain}"
        await dns_provider.remove_zone(origin)

    reverse_zone = await build_reverse_zone(session, network, devices)
    if reverse_zone:
        await dns_provider.ensure_zone(reverse_zone)
    else:
        origin = _reverse_zone_origin(network.subnet)
        if origin:
            await dns_provider.remove_zone(origin)
