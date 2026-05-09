from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.acl import ACLRule


async def check_device_access(
    session: AsyncSession,
    source_device_id,
    dest_ip: str,
) -> bool:
    result = await session.execute(
        select(Device).where(Device.id == source_device_id)
    )
    source = result.scalar_one_or_none()
    if not source or not source.is_active:
        return False
    dest_result = await session.execute(
        select(Device).where(Device.ip_address == dest_ip)
    )
    dest = dest_result.scalar_one_or_none()
    if not dest or not dest.is_active:
        return False
    if source.network_id != dest.network_id:
        return False
    acl_result = await session.execute(
        select(ACLRule)
        .where(ACLRule.network_id == source.network_id)
        .order_by(ACLRule.priority)
    )
    rules = acl_result.scalars().all()
    if not rules:
        return True
    source_tags = set(source.tags or [])
    dest_tags = set(dest.tags or [])
    for rule in rules:
        src_match = not rule.src_tags or source_tags.intersection(rule.src_tags)
        dst_match = not rule.dst_tags or dest_tags.intersection(rule.dst_tags)
        if src_match and dst_match:
            return rule.action == "allow"
    return True
