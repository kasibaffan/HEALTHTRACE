import enum

from app.models.enums import Role


class Perm(str, enum.Enum):
    CASE_VIEW = "case:view"
    CASE_CREATE = "case:create"
    CASE_UPDATE = "case:update"
    CASE_ASSIGN = "case:assign"
    DOCUMENT_UPLOAD = "document:upload"
    EVIDENCE_VIEW = "evidence:view"
    EVIDENCE_VERIFY = "evidence:verify"
    FINDING_REVIEW = "finding:review"
    POLICY_VIEW = "policy:view"
    POLICY_MANAGE = "policy:manage"
    AUDIT_VIEW = "audit:view"
    USER_MANAGE = "user:manage"
    ORG_MANAGE = "org:manage"


_READ = {Perm.CASE_VIEW, Perm.EVIDENCE_VIEW, Perm.POLICY_VIEW}

ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.OWNER: frozenset(Perm),
    Role.ADMIN: frozenset(_READ | {Perm.CASE_CREATE, Perm.CASE_UPDATE, Perm.CASE_ASSIGN, Perm.DOCUMENT_UPLOAD, Perm.POLICY_MANAGE, Perm.AUDIT_VIEW, Perm.USER_MANAGE}),
    Role.REVIEWER: frozenset(_READ | {Perm.CASE_ASSIGN, Perm.FINDING_REVIEW, Perm.EVIDENCE_VERIFY, Perm.AUDIT_VIEW}),
    Role.ANALYST: frozenset(_READ | {Perm.CASE_CREATE, Perm.CASE_UPDATE, Perm.DOCUMENT_UPLOAD}),
    Role.VIEWER: frozenset(_READ),
}

ROLE_RANK = {Role.OWNER: 5, Role.ADMIN: 4, Role.REVIEWER: 3, Role.ANALYST: 2, Role.VIEWER: 1}


def permissions_for(role: Role) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS[role])
