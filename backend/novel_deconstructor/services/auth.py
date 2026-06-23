from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from typing import NamedTuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import User, UserSession, Workspace, WorkspaceMember


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


class AuthSession(NamedTuple):
    token: str
    session: UserSession


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS).hex()
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = encoded.split("$", 3)
        iterations = int(iterations_raw)
    except (ValueError, AttributeError):
        return False
    if algorithm != PASSWORD_ALGORITHM:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user_with_workspace(
    db: Session,
    *,
    email: str,
    password: str,
    username: str | None = None,
    display_name: str = "",
) -> tuple[User, Workspace]:
    clean_email = normalize_email(email)
    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少需要 8 位")
    clean_username = (username or "").strip() or None
    if db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(status_code=409, detail="邮箱已注册")
    if clean_username and db.query(User).filter(User.username == clean_username).first():
        raise HTTPException(status_code=409, detail="用户名已被占用")

    user = User(
        email=clean_email,
        username=clean_username,
        password_hash=hash_password(password),
        display_name=(display_name or clean_username or clean_email.split("@", 1)[0])[:120],
        status="active",
    )
    db.add(user)
    db.flush()

    workspace_id = f"user_{user.id}_{secrets.token_hex(5)}"
    workspace = Workspace(
        id=workspace_id,
        owner_user_id=user.id,
        name=f"{user.display_name} 的空间",
        slug=workspace_id,
        plan="free",
    )
    db.add(workspace)
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="owner", status="active"))
    db.commit()
    db.refresh(user)
    db.refresh(workspace)
    return user, workspace


def authenticate_user(db: Session, email_or_username: str, password: str) -> User | None:
    identity = (email_or_username or "").strip()
    if not identity:
        return None
    query = db.query(User)
    user = query.filter(User.email == normalize_email(identity)).first()
    if not user:
        user = query.filter(User.username == identity).first()
    if not user or user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def create_session(
    db: Session,
    user: User,
    *,
    days: int,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> AuthSession:
    token = secrets.token_urlsafe(40)
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=token_hash(token),
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=datetime.utcnow() + timedelta(days=max(days, 1)),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return AuthSession(token=token, session=session)


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = (
        db.query(UserSession)
        .filter(
            UserSession.refresh_token_hash == token_hash(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not session:
        return None
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        return None
    return user


def revoke_token(db: Session, token: str | None) -> bool:
    if not token:
        return False
    session = db.query(UserSession).filter(UserSession.refresh_token_hash == token_hash(token), UserSession.revoked_at.is_(None)).first()
    if not session:
        return False
    session.revoked_at = datetime.utcnow()
    db.commit()
    return True


def ensure_legacy_workspace(db: Session, workspace_id: str) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace:
        return workspace
    workspace = Workspace(id=workspace_id, name=workspace_id, slug=workspace_id, plan="legacy")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def workspace_for_user(db: Session, user: User, requested_workspace_id: str | None = None) -> str:
    query = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id, WorkspaceMember.status == "active")
    if requested_workspace_id:
        membership = query.filter(WorkspaceMember.workspace_id == requested_workspace_id).first()
        if not membership:
            raise HTTPException(status_code=403, detail="无权访问该用户空间")
        return membership.workspace_id

    membership = query.order_by(WorkspaceMember.created_at.asc()).first()
    if membership:
        return membership.workspace_id

    workspace_id = f"user_{user.id}_{secrets.token_hex(5)}"
    workspace = Workspace(id=workspace_id, owner_user_id=user.id, name=f"{user.display_name or user.email} 的空间", slug=workspace_id, plan="free")
    db.add(workspace)
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="owner", status="active"))
    db.commit()
    return workspace_id
