from fastapi import Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
import re

from ..config import get_settings
from ..database import get_db
from ..services.auth import ensure_legacy_workspace, user_from_token, workspace_for_user


DEFAULT_WORKSPACE_ID = "anonymous"
WORKSPACE_RE = re.compile(r"[^a-zA-Z0-9_-]+")
bearer = HTTPBearer(auto_error=False)


def normalize_workspace_id(value: str | None) -> str:
    cleaned = WORKSPACE_RE.sub("", (value or "").strip())[:80]
    return cleaned or DEFAULT_WORKSPACE_ID


def get_workspace_id(
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    workspace_id: str | None = Query(default=None),
    access_token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> str:
    requested = normalize_workspace_id(x_workspace_id or workspace_id) if (x_workspace_id or workspace_id) else None
    settings = get_settings()
    bearer_token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    token = bearer_token or access_token
    if token:
        user = user_from_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        return workspace_for_user(db, user, requested)

    if settings.app_require_auth:
        raise HTTPException(status_code=401, detail="请先登录")

    legacy_workspace_id = requested or DEFAULT_WORKSPACE_ID
    ensure_legacy_workspace(db, legacy_workspace_id)
    return legacy_workspace_id
