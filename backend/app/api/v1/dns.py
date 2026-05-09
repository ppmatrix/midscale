import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.dns import DNSEntry
from app.models.network import Network
from app.schemas.dns import DNSEntryCreate, DNSEntryResponse
from app.services.audit import audit_logger

router = APIRouter(prefix="/networks/{network_id}/dns", tags=["dns"])


@router.get("", response_model=list[DNSEntryResponse])
async def list_dns(
    network_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    result = await session.execute(
        select(DNSEntry)
        .where(DNSEntry.network_id == network_id)
        .order_by(DNSEntry.domain)
    )
    return result.scalars().all()


@router.post("", response_model=DNSEntryResponse, status_code=201)
async def create_dns(
    network_id: uuid.UUID,
    req: DNSEntryCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    net_result = await session.execute(
        select(Network).where(Network.id == network_id)
    )
    if not net_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found")
    entry = DNSEntry(
        network_id=network_id,
        domain=req.domain,
        address=req.address,
    )
    session.add(entry)
    await session.flush()
    await audit_logger.log(
        session=session,
        action="dns.create",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="dns",
        target_id=str(entry.id),
        details={"network_id": str(network_id), "domain": req.domain, "address": req.address},
        ip_address=request.client.host if request.client else None,
    )
    return entry


@router.delete("/{entry_id}", status_code=204)
async def delete_dns(
    network_id: uuid.UUID,
    entry_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    result = await session.execute(
        select(DNSEntry).where(
            DNSEntry.id == entry_id,
            DNSEntry.network_id == network_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DNS entry not found")
    await audit_logger.log(
        session=session,
        action="dns.delete",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="dns",
        target_id=str(entry_id),
        details={"network_id": str(network_id)},
        ip_address=request.client.host if request.client else None,
    )
    await session.delete(entry)
    await session.flush()
