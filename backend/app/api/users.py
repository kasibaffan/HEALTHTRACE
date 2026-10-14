from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.common import PageParams, page_out, paginate
from app.audit.service import record
from app.auth.deps import Ctx, get_ctx, require
from app.auth.permissions import ROLE_RANK, Perm
from app.core.config import settings
from app.core.errors import AppError, forbidden
from app.core.security import hash_one_time_token, new_opaque_token
from app.database.session import get_db
from app.models import Invitation, OrganizationMember, RefreshSession, User
from app.models.enums import Role
from app.repositories.scoped import get_member_user, parse_uuid
from app.schemas.inputs import InviteIn, OrganizationUpdateIn, UserPatchIn
from app.services.email import get_email_service
from app.services.notify import notify
from app.services.serializers import iso, member_dict, org_dict
from app.websocket.manager import Outbox

router = APIRouter(tags=["users"])


def _members_stmt(ctx: Ctx, search: str | None, role: Role | None, status: str | None):
    stmt = select(User, OrganizationMember).join(OrganizationMember, OrganizationMember.user_id == User.id).where(OrganizationMember.organization_id == ctx.org_id)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    if role:
        stmt = stmt.where(OrganizationMember.role == role)
    if status in ("active", "deactivated"):
        stmt = stmt.where(User.is_active == (status == "active"))
    return stmt.order_by(User.full_name)


@router.get("/users")
def list_users(search: str | None = Query(None, max_length=100), role: Role | None = None, status: str | None = None, p: PageParams = Depends(),
               ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    # Any member may list colleagues (needed for assignment); management actions below require USER_MANAGE.
    rows, total = paginate(db, _members_stmt(ctx, search, role, status), p)
    return page_out([member_dict(u, m) for u, m in rows], total, p)


@router.get("/organization")
def get_organization(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(OrganizationMember).where(OrganizationMember.organization_id == ctx.org_id)).scalar_one()
    return {**org_dict(ctx.org), "memberCount": count, "yourRole": ctx.role.value}


@router.patch("/organization")
def update_organization(body: OrganizationUpdateIn, ctx: Ctx = Depends(require(Perm.ORG_MANAGE)), db: Session = Depends(get_db)):
    old = ctx.org.name
    ctx.org.name = body.name
    record(db, action="Organization renamed", org_id=ctx.org_id, ctx=ctx, entity_type="organization", entity_id=ctx.org_id, old={"name": old}, new={"name": body.name}, target=body.name)
    db.commit()
    return org_dict(ctx.org)


@router.get("/organization/members")
def organization_members(search: str | None = Query(None, max_length=100), role: Role | None = None, status: str | None = None, p: PageParams = Depends(),
                         ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    return list_users(search, role, status, p, ctx, db)


@router.get("/users/invitations")
def list_invitations(ctx: Ctx = Depends(require(Perm.USER_MANAGE)), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.execute(select(Invitation).where(Invitation.organization_id == ctx.org_id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None), Invitation.expires_at > now)
                      .order_by(Invitation.created_at.desc())).scalars()
    return [{"id": str(i.id), "email": i.email, "role": i.role.value, "createdAt": iso(i.created_at), "expiresAt": iso(i.expires_at)} for i in rows]


@router.post("/users/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: str, ctx: Ctx = Depends(require(Perm.USER_MANAGE)), db: Session = Depends(get_db)):
    inv = db.execute(select(Invitation).where(Invitation.id == parse_uuid(invitation_id, "Invitation"), Invitation.organization_id == ctx.org_id)).scalar_one_or_none()
    if not inv:
        raise AppError(404, "Invitation not found.", "not_found")
    inv.revoked_at = datetime.now(timezone.utc)
    record(db, action="Invitation revoked", org_id=ctx.org_id, ctx=ctx, entity_type="invitation", entity_id=inv.id, target=inv.email)
    db.commit()
    return {"ok": True}


@router.post("/users/invite", status_code=201)
def invite_user(body: InviteIn, ctx: Ctx = Depends(require(Perm.USER_MANAGE)), db: Session = Depends(get_db)):
    if body.role == Role.OWNER or ROLE_RANK[body.role] >= ROLE_RANK[ctx.role]:
        raise forbidden("You can only invite users with a role below your own.")
    email = body.email.lower()
    if db.execute(select(User.id).where(func.lower(User.email) == email)).first():
        raise AppError(409, "A user with this email already exists.", "conflict")
    db.execute(update(Invitation).where(Invitation.organization_id == ctx.org_id, func.lower(Invitation.email) == email, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))
    token = new_opaque_token()
    inv = Invitation(organization_id=ctx.org_id, email=email, role=body.role, token_hash=hash_one_time_token(token), invited_by=ctx.user.id,
                     expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db.add(inv)
    db.flush()
    record(db, action="User invited", org_id=ctx.org_id, ctx=ctx, entity_type="invitation", entity_id=inv.id, target=email, new={"role": body.role.value})
    db.commit()
    link = f"{settings.frontend_url}/#/invite/{token}"
    get_email_service().send(email, f"You're invited to {ctx.org.name} on HealthTrace", f"Accept your invitation: {link}")
    out = {"id": str(inv.id), "email": email, "role": body.role.value, "expiresAt": iso(inv.expires_at)}
    if not settings.is_production:
        out["inviteLink"] = link  # development convenience; in production the link is only emailed
    return out


@router.get("/users/{user_id}")
def get_user(user_id: str, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    u, m = get_member_user(db, ctx.org_id, user_id)
    return member_dict(u, m)


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatchIn, ctx: Ctx = Depends(require(Perm.USER_MANAGE)), db: Session = Depends(get_db)):
    target, member = get_member_user(db, ctx.org_id, user_id)
    if target.id == ctx.user.id:
        raise forbidden("You cannot change your own role or status.")
    if member.role == Role.OWNER and ctx.role != Role.OWNER:
        raise forbidden("Only an owner can modify another owner.")
    if ROLE_RANK[member.role] >= ROLE_RANK[ctx.role] and ctx.role != Role.OWNER:
        raise forbidden("You can only manage users with a role below your own.")
    outbox = Outbox()
    if body.role is not None and body.role != member.role:
        if body.role == Role.OWNER and ctx.role != Role.OWNER:
            raise forbidden("Only an owner can grant the owner role.")
        if body.role != Role.OWNER and ROLE_RANK[body.role] >= ROLE_RANK[ctx.role] and ctx.role != Role.OWNER:
            raise forbidden("You cannot grant a role equal to or above your own.")
        if member.role == Role.OWNER:
            owners = db.execute(select(func.count()).select_from(OrganizationMember).where(OrganizationMember.organization_id == ctx.org_id, OrganizationMember.role == Role.OWNER)).scalar_one()
            if owners <= 1:
                raise AppError(409, "An organization must keep at least one owner.", "conflict")
        old = member.role.value
        member.role = body.role
        record(db, action="User role changed", org_id=ctx.org_id, ctx=ctx, entity_type="user", entity_id=target.id, target=target.email, old={"role": old}, new={"role": body.role.value})
        notify(db, outbox, org_id=ctx.org_id, user_ids=[target.id], type_="ROLE_CHANGED", title="Your role changed", message=f"You are now a {body.role.value.title()}.")
    if body.is_active is not None and body.is_active != target.is_active:
        target.is_active = body.is_active
        if not body.is_active:
            db.execute(update(RefreshSession).where(RefreshSession.user_id == target.id, RefreshSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
        record(db, action="User reactivated" if body.is_active else "User deactivated", org_id=ctx.org_id, ctx=ctx, entity_type="user", entity_id=target.id, target=target.email)
    db.commit()
    outbox.flush()
    return member_dict(target, member)
