"""Audit log query API.

Provides paginated, filterable access to the append-only audit log.
Only superusers can query audit logs.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_superuser
from app.models.user import User
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogResponse, AuditLogPage

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    actor_id: Optional[str] = Query(None, description="Filter by actor UUID"),
    action: Optional[str] = Query(None, description="Filter by action name"),
    target_type: Optional[str] = Query(None, description="Filter by target type"),
    target_id: Optional[str] = Query(None, description="Filter by target UUID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: Annotated[User, Depends(get_current_superuser)] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,
):
    from datetime import datetime, timezone

    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
        count_query = count_query.where(AuditLog.actor_id == actor_id)
    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
        count_query = count_query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
        count_query = count_query.where(AuditLog.target_id == target_id)

    query = query.order_by(AuditLog.created_at.desc())
    query = query.offset(skip).limit(limit)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    result = await session.execute(query)
    items = result.scalars().all()

    return AuditLogPage(
        items=[AuditLogResponse.model_validate(item) for item in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/actions", response_model=list[str])
async def list_audit_actions(
    current_user: Annotated[User, Depends(get_current_superuser)] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,
):
    result = await session.execute(
        select(AuditLog.action).distinct().order_by(AuditLog.action)
    )
    return [row[0] for row in result]
