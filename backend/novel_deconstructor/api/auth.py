from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..schemas import AuthLoginRequest, AuthMeResponse, AuthRegisterRequest, AuthResponse, AuthUserRead
from ..services.auth import authenticate_user, create_session, create_user_with_workspace, revoke_token, user_from_token, workspace_for_user


router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    return credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None


@router.post("/register", response_model=AuthResponse)
def register(
    payload: AuthRegisterRequest,
    request: Request,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    db: Session = Depends(get_db),
):
    user, workspace = create_user_with_workspace(
        db,
        email=payload.email,
        password=payload.password,
        username=payload.username,
        display_name=payload.display_name,
    )
    auth_session = create_session(
        db,
        user,
        days=get_settings().app_auth_session_days,
        user_agent=user_agent,
        ip_address=_client_ip(request),
    )
    return AuthResponse(
        access_token=auth_session.token,
        expires_at=auth_session.session.expires_at,
        workspace_id=workspace.id,
        user=AuthUserRead.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: AuthLoginRequest,
    request: Request,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, payload.identity, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    workspace_id = workspace_for_user(db, user)
    auth_session = create_session(
        db,
        user,
        days=get_settings().app_auth_session_days,
        user_agent=user_agent,
        ip_address=_client_ip(request),
    )
    return AuthResponse(
        access_token=auth_session.token,
        expires_at=auth_session.session.expires_at,
        workspace_id=workspace_id,
        user=AuthUserRead.model_validate(user),
    )


@router.get("/me", response_model=AuthMeResponse)
def me(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    token = _token(credentials)
    user = user_from_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return AuthMeResponse(user=AuthUserRead.model_validate(user), workspace_id=workspace_for_user(db, user))


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    revoke_token(db, _token(credentials))
    return {"ok": True}
