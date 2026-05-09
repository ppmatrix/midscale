from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services import auth as auth_service
from app.services.audit import audit_logger

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    req: RegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    user, access_token, refresh_token = await auth_service.register_user(session, req)
    await audit_logger.log(
        session=session,
        action="auth.register",
        actor_id=str(user.id),
        actor_type="user",
        target_type="user",
        target_id=str(user.id),
        details={"email": req.email, "display_name": req.display_name},
        ip_address=request.client.host if request.client else None,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    user, access_token, refresh_token = await auth_service.login_user(session, req)
    await audit_logger.log(
        session=session,
        action="auth.login",
        actor_id=str(user.id),
        actor_type="user",
        target_type="user",
        target_id=str(user.id),
        details={"email": req.email},
        ip_address=request.client.host if request.client else None,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    access_token = await auth_service.refresh_access_token(req.refresh_token)
    return TokenResponse(
        access_token=access_token, refresh_token=req.refresh_token
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
