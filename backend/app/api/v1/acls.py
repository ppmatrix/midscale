import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user, require_network_owner
from app.models.user import User
from app.models.acl import ACLRule
from app.models.network import Network
from app.schemas.acl import ACLRuleCreate, ACLRuleUpdate, ACLRuleResponse
from app.services.audit import audit_logger

router = APIRouter(prefix="/networks/{network_id}/acls", tags=["acls"])


@router.get("", response_model=list[ACLRuleResponse])
async def list_acls(
    network_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(ACLRule)
        .where(ACLRule.network_id == network_id)
        .order_by(ACLRule.priority)
    )
    return result.scalars().all()


@router.post("", response_model=ACLRuleResponse, status_code=201)
async def create_acl(
    network_id: uuid.UUID,
    req: ACLRuleCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await require_network_owner(session, network_id, current_user)
    rule = ACLRule(
        network_id=network_id,
        src_tags=req.src_tags,
        dst_tags=req.dst_tags,
        action=req.action,
        priority=req.priority,
    )
    session.add(rule)
    await session.flush()
    await audit_logger.log(
        session=session,
        action="acl.create",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="acl",
        target_id=str(rule.id),
        details={
            "network_id": str(network_id),
            "src_tags": req.src_tags,
            "dst_tags": req.dst_tags,
            "action": req.action,
            "priority": req.priority,
        },
        ip_address=request.client.host if request.client else None,
    )
    return rule


@router.put("/{rule_id}", response_model=ACLRuleResponse)
async def update_acl(
    network_id: uuid.UUID,
    rule_id: uuid.UUID,
    req: ACLRuleUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(ACLRule).where(
            ACLRule.id == rule_id,
            ACLRule.network_id == network_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ACL rule not found")
    if req.src_tags is not None:
        rule.src_tags = req.src_tags
    if req.dst_tags is not None:
        rule.dst_tags = req.dst_tags
    if req.action is not None:
        rule.action = req.action
    if req.priority is not None:
        rule.priority = req.priority
    await session.flush()
    await audit_logger.log(
        session=session,
        action="acl.update",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="acl",
        target_id=str(rule_id),
        details={
            "network_id": str(network_id),
            "action": req.action,
            "priority": req.priority,
        },
        ip_address=request.client.host if request.client else None,
    )
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_acl(
    network_id: uuid.UUID,
    rule_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from fastapi import HTTPException, status
    await require_network_owner(session, network_id, current_user)
    result = await session.execute(
        select(ACLRule).where(
            ACLRule.id == rule_id,
            ACLRule.network_id == network_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ACL rule not found")
    await audit_logger.log(
        session=session,
        action="acl.delete",
        actor_id=str(current_user.id),
        actor_type="user",
        target_type="acl",
        target_id=str(rule_id),
        details={"network_id": str(network_id)},
        ip_address=request.client.host if request.client else None,
    )
    await session.delete(rule)
    await session.flush()
