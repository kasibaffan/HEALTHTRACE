"""Every lookup is scoped by organization_id taken from the authenticated context.
A resource from another organization is indistinguishable from one that does not exist (404, never 403)."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.models import Case, Document, Evidence, Finding, Notification, Policy, User
from app.models.accounts import OrganizationMember


def parse_uuid(value: str, what: str = "Resource") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise not_found(what)


def get_case(db: Session, org_id: uuid.UUID, case_id: str) -> Case:
    cid = parse_uuid(case_id, "Case")
    row = db.execute(select(Case).where(Case.id == cid, Case.organization_id == org_id)).unique().scalar_one_or_none()
    if not row:
        raise not_found("Case")
    return row


def get_finding(db: Session, org_id: uuid.UUID, finding_id: str) -> Finding:
    fid = parse_uuid(finding_id, "Finding")
    row = db.execute(select(Finding).where(Finding.id == fid, Finding.organization_id == org_id)).unique().scalar_one_or_none()
    if not row:
        raise not_found("Finding")
    return row


def get_document(db: Session, org_id: uuid.UUID, document_id: str) -> Document:
    did = parse_uuid(document_id, "Document")
    row = db.execute(select(Document).where(Document.id == did, Document.organization_id == org_id)).unique().scalar_one_or_none()
    if not row:
        raise not_found("Document")
    return row


def get_evidence(db: Session, org_id: uuid.UUID, evidence_id: str) -> Evidence:
    eid = parse_uuid(evidence_id, "Evidence")
    row = db.execute(select(Evidence).where(Evidence.id == eid, Evidence.organization_id == org_id)).unique().scalar_one_or_none()
    if not row:
        raise not_found("Evidence")
    return row


def get_policy(db: Session, org_id: uuid.UUID, policy_id: str) -> Policy:
    pid = parse_uuid(policy_id, "Policy")
    row = db.execute(select(Policy).where(Policy.id == pid, Policy.organization_id == org_id)).unique().scalar_one_or_none()
    if not row:
        raise not_found("Policy")
    return row


def get_member_user(db: Session, org_id: uuid.UUID, user_id: str) -> tuple[User, OrganizationMember]:
    uid = parse_uuid(user_id, "User")
    row = db.execute(
        select(User, OrganizationMember).join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(User.id == uid, OrganizationMember.organization_id == org_id)
    ).unique().first()
    if not row:
        raise not_found("User")
    return row[0], row[1]


def get_notification(db: Session, user_id: uuid.UUID, notification_id: str) -> Notification:
    nid = parse_uuid(notification_id, "Notification")
    row = db.execute(select(Notification).where(Notification.id == nid, Notification.user_id == user_id)).scalar_one_or_none()
    if not row:
        raise not_found("Notification")
    return row
