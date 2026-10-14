import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import Ctx, client_ip, get_ctx
from app.core.config import settings
from app.core.errors import AppError, conflict
from app.core.security import (
    create_access_token, hash_one_time_token, hash_password, hash_refresh_token, needs_rehash, new_opaque_token, password_problems, verify_password,
)
from app.database.session import get_db
from app.middleware.http import rate_limit
from app.models import Invitation, Organization, OrganizationMember, PasswordResetToken, RefreshSession, User
from app.models.enums import Role
from app.schemas.inputs import (
    AcceptInviteIn, ChangePasswordIn, ForgotPasswordIn, LoginIn, ProfileUpdateIn, RegisterIn, ResetPasswordIn,
)
from app.services.email import get_email_service
from app.services.policy_templates import create_default_policy
from app.services.serializers import iso, me_dict

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "ht_refresh"
DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=settings.refresh_token_expire_days * 86400, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/api/auth")


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/api/auth")


def _issue(db: Session, user: User, request: Request, response: Response) -> tuple[dict, RefreshSession]:
    token = new_opaque_token()
    session = RefreshSession(user_id=user.id, token_hash=hash_refresh_token(token), expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
                             user_agent=(request.headers.get("user-agent") or "")[:300], ip_address=client_ip(request), last_used_at=_now())
    db.add(session)
    db.flush()
    access, ttl = create_access_token(user.id, session.id)
    _set_cookie(response, token)
    m = user.membership
    return {"accessToken": access, "expiresIn": ttl, **me_dict(user, m.organization, m.role)}, session


def _check_password(password: str, confirm: str) -> None:
    if password != confirm:
        raise AppError(422, "Passwords do not match.", "password_mismatch")
    problems = password_problems(password)
    if problems:
        raise AppError(422, "Password needs " + ", ".join(problems) + ".", "weak_password")


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


@router.post("/register", status_code=201, dependencies=[rate_limit("register", 10, 300)])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _check_password(body.password, body.confirm_password)
    email = body.email.lower()
    if db.execute(select(User.id).where(func.lower(User.email) == email)).first():
        raise conflict("An account with this email already exists.")
    user = User(full_name=body.full_name, email=email, password_hash=hash_password(body.password), is_verified=False, last_login_at=_now())
    org = Organization(name=body.organization_name or f"{body.full_name.split()[0]}'s Workspace", slug="pending")
    org.slug = _slug(org.name)
    db.add_all([user, org])
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=Role.OWNER))
    create_default_policy(db, org.id, user.id)
    db.flush()
    db.refresh(user)
    record(db, action="User registered", org_id=org.id, user=user, entity_type="user", entity_id=user.id, target=user.email, ip=client_ip(request))
    record(db, action="Organization created", org_id=org.id, user=user, entity_type="organization", entity_id=org.id, target=org.name, ip=client_ip(request))
    out, _ = _issue(db, user, request, response)
    db.commit()
    return out


@router.post("/login", dependencies=[rate_limit("login", 10, 60)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(func.lower(User.email) == body.email.lower())).unique().scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)  # constant-ish time whether or not the user exists
    if not user or not ok:
        record(db, action="Login failed", org_id=user.membership.organization_id if user and user.membership else None, target=body.email.lower(), ip=client_ip(request), actor_label="Anonymous", actor_kind="SYSTEM")
        db.commit()
        raise AppError(401, "Invalid email or password.", "invalid_credentials")
    if not user.is_active or not user.membership:
        raise AppError(403, "This account has been deactivated. Contact your administrator.", "account_disabled")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = _now()
    out, _ = _issue(db, user, request, response)
    record(db, action="User logged in", org_id=user.membership.organization_id, user=user, entity_type="user", entity_id=user.id, target=user.email, ip=client_ip(request))
    db.commit()
    return out


@router.post("/refresh", dependencies=[rate_limit("refresh", 60, 60)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db), ht_refresh: str | None = Cookie(default=None)):
    if not ht_refresh:
        raise AppError(401, "Not signed in.", "unauthenticated")
    session = db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(ht_refresh))).scalar_one_or_none()
    if not session or session.expires_at < _now():
        _clear_cookie(response)
        raise AppError(401, "Your session has expired. Please sign in again.", "unauthenticated")
    if session.revoked_at:
        # A rotated token was replayed: assume theft and end every session for this user.
        db.execute(update(RefreshSession).where(RefreshSession.user_id == session.user_id, RefreshSession.revoked_at.is_(None)).values(revoked_at=_now()))
        db.commit()
        _clear_cookie(response)
        raise AppError(401, "Your session was ended for security reasons. Please sign in again.", "session_reuse")
    user = db.execute(select(User).where(User.id == session.user_id)).unique().scalar_one()
    if not user.is_active or not user.membership:
        raise AppError(401, "This account is not active.", "unauthenticated")
    session.revoked_at = _now()
    out, new_session = _issue(db, user, request, response)
    session.replaced_by = new_session.id
    db.commit()
    return out


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db), ht_refresh: str | None = Cookie(default=None)):
    if ht_refresh:
        session = db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(ht_refresh))).scalar_one_or_none()
        if session and not session.revoked_at:
            session.revoked_at = _now()
            user = db.execute(select(User).where(User.id == session.user_id)).unique().scalar_one()
            if user.membership:
                record(db, action="User logged out", org_id=user.membership.organization_id, user=user, entity_type="user", entity_id=user.id, target=user.email, ip=client_ip(request))
            db.commit()
    _clear_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    db.execute(update(RefreshSession).where(RefreshSession.user_id == ctx.user.id, RefreshSession.revoked_at.is_(None)).values(revoked_at=_now()))
    record(db, action="Signed out of all sessions", org_id=ctx.org_id, ctx=ctx, entity_type="user", entity_id=ctx.user.id, target=ctx.user.email)
    db.commit()
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    return me_dict(ctx.user, ctx.org, ctx.role)


@router.patch("/me")
def update_profile(body: ProfileUpdateIn, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    user, changed = ctx.user, {}
    if body.full_name and body.full_name != user.full_name:
        changed["fullName"] = [user.full_name, body.full_name]
        user.full_name = body.full_name
    if body.email and body.email.lower() != user.email:
        if db.execute(select(User.id).where(func.lower(User.email) == body.email.lower(), User.id != user.id)).first():
            raise conflict("That email is already in use.")
        changed["email"] = [user.email, body.email.lower()]
        user.email = body.email.lower()
    if "avatar_url" in body.model_fields_set:
        changed["avatarUrl"] = [user.avatar_url, body.avatar_url]
        user.avatar_url = body.avatar_url
    if changed:
        record(db, action="Profile updated", org_id=ctx.org_id, ctx=ctx, entity_type="user", entity_id=user.id, target=user.email, new={k: v[1] for k, v in changed.items() if k != "email"})
    db.commit()
    return me_dict(user, ctx.org, ctx.role)


@router.post("/change-password", dependencies=[rate_limit("change-password", 10, 300)])
def change_password(body: ChangePasswordIn, response: Response, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise AppError(400, "Your current password is incorrect.", "invalid_credentials")
    problems = password_problems(body.new_password)
    if problems:
        raise AppError(422, "Password needs " + ", ".join(problems) + ".", "weak_password")
    ctx.user.password_hash = hash_password(body.new_password)
    db.execute(update(RefreshSession).where(RefreshSession.user_id == ctx.user.id, RefreshSession.id != ctx.session_id, RefreshSession.revoked_at.is_(None)).values(revoked_at=_now()))
    record(db, action="Password changed", org_id=ctx.org_id, ctx=ctx, entity_type="user", entity_id=ctx.user.id, target=ctx.user.email)
    db.commit()
    return {"ok": True, "message": "Password updated. Other sessions were signed out."}


@router.get("/sessions")
def sessions(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    rows = db.execute(select(RefreshSession).where(RefreshSession.user_id == ctx.user.id, RefreshSession.revoked_at.is_(None), RefreshSession.expires_at > _now())
                      .order_by(RefreshSession.last_used_at.desc())).scalars()
    return [{"id": str(s.id), "current": s.id == ctx.session_id, "userAgent": s.user_agent, "ipAddress": s.ip_address, "createdAt": iso(s.created_at), "lastUsedAt": iso(s.last_used_at)} for s in rows]


@router.post("/forgot-password", dependencies=[rate_limit("forgot", 5, 300)])
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    generic = {"ok": True, "message": "If an account exists for that email, a reset link has been prepared."}
    user = db.execute(select(User).where(func.lower(User.email) == body.email.lower())).unique().scalar_one_or_none()
    if not user or not user.is_active:
        return generic
    token = new_opaque_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=hash_one_time_token(token), expires_at=_now() + timedelta(hours=1)))
    if user.membership:
        record(db, action="Password reset requested", org_id=user.membership.organization_id, user=user, entity_type="user", entity_id=user.id, target=user.email, ip=client_ip(request))
    db.commit()
    link = f"{settings.frontend_url}/#/reset-password?token={token}"
    get_email_service().send(user.email, "Reset your HealthTrace password", f"Use this link within 1 hour: {link}")
    if not settings.is_production:
        return {**generic, "devResetLink": link}  # development convenience only; never returned in production
    return generic


@router.post("/reset-password", dependencies=[rate_limit("reset", 10, 300)])
def reset_password(body: ResetPasswordIn, db: Session = Depends(get_db)):
    _check_password(body.password, body.confirm_password)
    row = db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_one_time_token(body.token))).scalar_one_or_none()
    if not row or row.used_at or row.expires_at < _now():
        raise AppError(400, "This reset link is invalid or has expired.", "invalid_token")
    user = db.execute(select(User).where(User.id == row.user_id)).unique().scalar_one()
    user.password_hash = hash_password(body.password)
    row.used_at = _now()
    db.execute(update(RefreshSession).where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)).values(revoked_at=_now()))
    if user.membership:
        record(db, action="Password reset completed", org_id=user.membership.organization_id, user=user, entity_type="user", entity_id=user.id, target=user.email)
    db.commit()
    return {"ok": True, "message": "Password updated. Please sign in."}


def _invitation(db: Session, token: str) -> Invitation:
    inv = db.execute(select(Invitation).where(Invitation.token_hash == hash_one_time_token(token))).scalar_one_or_none()
    if not inv or inv.accepted_at or inv.revoked_at or inv.expires_at < _now():
        raise AppError(404, "This invitation is invalid or has expired.", "invalid_invitation")
    return inv


@router.get("/invitations/{token}")
def invitation_preview(token: str, db: Session = Depends(get_db)):
    inv = _invitation(db, token)
    org = db.get(Organization, inv.organization_id)
    inviter = db.get(User, inv.invited_by)
    return {"email": inv.email, "role": inv.role.value, "organizationName": org.name, "invitedBy": inviter.full_name if inviter else None, "expiresAt": iso(inv.expires_at)}


@router.post("/accept-invite", status_code=201, dependencies=[rate_limit("invite", 10, 300)])
def accept_invite(body: AcceptInviteIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _check_password(body.password, body.confirm_password)
    inv = _invitation(db, body.token)
    if db.execute(select(User.id).where(func.lower(User.email) == inv.email.lower())).first():
        raise conflict("An account with this email already exists. Sign in instead.")
    user = User(full_name=body.full_name, email=inv.email.lower(), password_hash=hash_password(body.password), is_verified=True, last_login_at=_now())
    db.add(user)
    db.flush()
    db.add(OrganizationMember(organization_id=inv.organization_id, user_id=user.id, role=inv.role))
    inv.accepted_at = _now()
    db.flush()
    db.refresh(user)
    record(db, action="Invitation accepted", org_id=inv.organization_id, user=user, entity_type="invitation", entity_id=inv.id, target=user.email, new={"role": inv.role.value})
    out, _ = _issue(db, user, request, response)
    db.commit()
    return out
