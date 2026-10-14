import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import ROLE_PERMISSIONS, Perm
from app.core.errors import AppError, forbidden
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import Organization, RefreshSession, User
from app.models.enums import Role

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Ctx:
    """Authenticated request context. org_id always comes from the database membership, never from the client."""

    user: User
    org_id: uuid.UUID
    org: Organization
    role: Role
    session_id: uuid.UUID
    ip: str | None

    def can(self, perm: Perm) -> bool:
        return perm in ROLE_PERMISSIONS[self.role]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def authenticate(db: Session, token: str | None, ip: str | None = None) -> Ctx:
    payload = decode_access_token(token) if token else None
    if not payload:
        raise AppError(401, "Your session has expired. Please sign in again.", "unauthenticated")
    try:
        user_id, session_id = uuid.UUID(payload["sub"]), uuid.UUID(payload["sid"])
    except ValueError:
        raise AppError(401, "Invalid session.", "unauthenticated")
    session = db.get(RefreshSession, session_id)
    now = datetime.now(timezone.utc)
    if not session or session.user_id != user_id or session.revoked_at or session.expires_at < now:
        raise AppError(401, "Your session has ended. Please sign in again.", "unauthenticated")
    user = db.execute(select(User).where(User.id == user_id)).unique().scalar_one_or_none()
    if not user or not user.is_active or not user.membership:
        raise AppError(401, "This account is not active.", "unauthenticated")
    if not user.last_seen_at or now - user.last_seen_at > timedelta(seconds=60):
        user.last_seen_at = now
        db.commit()
    m = user.membership
    return Ctx(user=user, org_id=m.organization_id, org=m.organization, role=m.role, session_id=session_id, ip=ip)


def get_ctx(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> Ctx:
    ctx = authenticate(db, creds.credentials if creds else None, client_ip(request))
    request.state.user_id = str(ctx.user.id)
    return ctx


def require(*perms: Perm):
    """Dependency factory: the authoritative RBAC check, enforced on the backend."""

    def dependency(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        missing = [p for p in perms if not ctx.can(p)]
        if missing:
            raise forbidden(f"Your role ({ctx.role.value.title()}) cannot perform this action.")
        return ctx

    return dependency
