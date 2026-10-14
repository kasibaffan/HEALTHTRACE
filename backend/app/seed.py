"""Seed synthetic demo data:  python -m app.seed
Passwords come from DEMO_PASSWORD (never hard-coded). All data is synthetic."""
import secrets
import sys

from sqlalchemy import select

from app.audit.service import record
from app.core.config import settings
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.models import Organization, OrganizationMember, User
from app.models.enums import Role
from app.services.demo import create_demo_case
from app.services.notify import notify
from app.services.policy_templates import create_default_policy
from app.websocket.manager import Outbox

DEMO_ORG = ("HealthTrace Demo Organization", "healthtrace-demo")
DEMO_USERS = [
    ("demo@healthtrace.local", "Demo Owner", Role.OWNER),
    ("admin@healthtrace.local", "Priya Nair", Role.ADMIN),
    ("reviewer@healthtrace.local", "Dr. Sarah Chen", Role.REVIEWER),
    ("analyst@healthtrace.local", "Marcus Lee", Role.ANALYST),
    ("viewer@healthtrace.local", "Jordan Ellis", Role.VIEWER),
]
OTHER_ORG = ("Northwind Review Group", "northwind-review")
OTHER_USER = ("outsider@northwind.local", "Riley Northwind", Role.OWNER)


def _password() -> str:
    if settings.demo_password:
        return settings.demo_password
    if settings.is_production:
        sys.exit("DEMO_PASSWORD must be set to seed demo users in production.")
    generated = "Demo-" + secrets.token_urlsafe(9) + "9a"
    print(f"DEMO_PASSWORD not set; generated a one-off development password: {generated}")
    return generated


def _org(db, name: str, slug: str) -> Organization:
    org = db.execute(select(Organization).where(Organization.slug == slug)).scalar_one_or_none()
    if not org:
        org = Organization(name=name, slug=slug)
        db.add(org)
        db.flush()
    return org


def _user(db, org: Organization, email: str, name: str, role: Role, pw_hash: str) -> User:
    user = db.execute(select(User).where(User.email == email)).unique().scalar_one_or_none()
    if user:
        return user
    user = User(email=email, full_name=name, password_hash=pw_hash, is_verified=True)
    db.add(user)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    db.flush()
    db.refresh(user)
    record(db, action="User registered", org_id=org.id, user=user, entity_type="user", entity_id=user.id, target=email)
    return user


def main() -> None:
    from app.models import Case

    db = SessionLocal()
    try:
        pw_hash = hash_password(_password())
        for (name, slug), users in ((DEMO_ORG, DEMO_USERS), (OTHER_ORG, [OTHER_USER])):
            org = _org(db, name, slug)
            members = {role: _user(db, org, email, full, role, pw_hash) for email, full, role in users}
            if not db.execute(select(Case.id).where(Case.organization_id == org.id, Case.case_number == "HT-10482")).first():
                owner = members[Role.OWNER]
                reviewer, analyst = members.get(Role.REVIEWER, owner), members.get(Role.ANALYST, owner)
                case = create_demo_case(db, org.id, uploader=analyst, assignee=reviewer, creator=analyst)
                outbox = Outbox()
                notify(db, outbox, org_id=org.id, user_ids=[reviewer.id], type_="CASE_ASSIGNED", title=f"Case {case.case_number} assigned to you",
                       message="Marcus Lee assigned you to review John Anderson.", case_id=case.id)
                db.commit()
                print(f"Seeded {name}: case {case.case_number} ({case.status.value})")
            else:
                db.commit()
                print(f"{name}: already seeded")
        print("Demo accounts (password = DEMO_PASSWORD):", ", ".join(e for e, _, _ in DEMO_USERS))
    finally:
        db.close()


if __name__ == "__main__":
    main()
