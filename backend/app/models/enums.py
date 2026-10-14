import enum


class Role(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class CaseStatus(str, enum.Enum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class Priority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FindingStatus(str, enum.Enum):
    MATCH = "MATCH"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    INCONCLUSIVE = "INCONCLUSIVE"


class ReviewerStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    OVERRIDDEN = "OVERRIDDEN"
    REQUESTED_EVIDENCE = "REQUESTED_EVIDENCE"


class PolicyStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EvidenceLinkRole(str, enum.Enum):
    SUPPORTING = "SUPPORTING"
    REVIEWED = "REVIEWED"
