import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, DDL, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, event, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import (
    CaseStatus, DocumentStatus, EvidenceLinkRole, FindingStatus, JobStatus, PolicyStatus, Priority, ReviewerStatus,
)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PolicyStatus] = mapped_column(Enum(PolicyStatus, native_enum=False, length=20), default=PolicyStatus.ACTIVE)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    rules: Mapped[list["Rule"]] = relationship(back_populates="policy", order_by="Rule.sort_order", cascade="all, delete-orphan")


class Rule(Base):
    """A policy criterion with a deterministic rule (operator + threshold over a named fact)."""

    __tablename__ = "rules"
    id: Mapped[uuid.UUID] = _pk()
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policies.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    finding_title: Mapped[str | None] = mapped_column(String(200))
    requirement: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(String(300))
    fact_name: Mapped[str] = mapped_column(String(80))
    operator: Mapped[str] = mapped_column(String(20))
    threshold: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str | None] = mapped_column(String(30))
    expected_evidence: Mapped[str | None] = mapped_column(String(200))
    suggested_action: Mapped[str | None] = mapped_column(String(300))
    source_document_name: Mapped[str | None] = mapped_column(String(255))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    policy: Mapped[Policy] = relationship(back_populates="rules")
    __table_args__ = (UniqueConstraint("policy_id", "code"),)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[uuid.UUID] = _pk()
    case_number: Mapped[str] = mapped_column(String(30))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("policies.id"))
    patient_reference: Mapped[str] = mapped_column(String(160))
    member_reference: Mapped[str | None] = mapped_column(String(60))
    condition: Mapped[str] = mapped_column(String(200))
    requested_procedure: Mapped[str] = mapped_column(String(200))
    requested_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus, native_enum=False, length=30), default=CaseStatus.NEW, index=True)
    priority: Mapped[Priority] = mapped_column(Enum(Priority, native_enum=False, length=10), default=Priority.MEDIUM)
    review_complexity: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    assignee = relationship("User", foreign_keys=[assigned_to], lazy="joined")
    policy: Mapped[Policy | None] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("organization_id", "case_number"),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str | None] = mapped_column(String(64))
    doc_type: Mapped[str] = mapped_column(String(30), default="Supporting")
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus, native_enum=False, length=20), default=DocumentStatus.UPLOADED)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    # ML document-type SUGGESTION (see app/ml). Kept apart from doc_type, which is filename-derived and drives extraction.
    # NULL ml_status = never classified (rows created before the feature existed).
    ml_status: Mapped[str | None] = mapped_column(String(20))
    ml_label: Mapped[str | None] = mapped_column(String(30))
    ml_score: Mapped[float | None] = mapped_column(Float)
    ml_low_confidence: Mapped[bool | None] = mapped_column(Boolean)
    ml_model_version: Mapped[str | None] = mapped_column(String(80))
    ml_classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_label: Mapped[str | None] = mapped_column(String(30))
    reviewed_label_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_label_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    pages: Mapped[list["DocumentPage"]] = relationship(order_by="DocumentPage.page_number", cascade="all, delete-orphan")
    uploader = relationship("User", foreign_keys=[uploaded_by], lazy="joined")
    label_reviewer = relationship("User", foreign_keys=[reviewed_label_by], lazy="joined")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    type: Mapped[str] = mapped_column(String(40), default="EXTRACTION")
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False, length=20), default=JobStatus.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Fact(Base):
    __tablename__ = "facts"
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str | None] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    source: Mapped[str] = mapped_column(String(80), default="mock-ai")
    created_at: Mapped[datetime] = _created()


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(20))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id"))
    evidence_type: Mapped[str] = mapped_column(String(40))
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    highlight: Mapped[str | None] = mapped_column(String(300))
    topic: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(400))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    document: Mapped[Document] = relationship(lazy="joined")
    fact: Mapped[Fact | None] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("organization_id", "code"),)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policies.id"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id"))
    status: Mapped[FindingStatus] = mapped_column(Enum(FindingStatus, native_enum=False, length=20))
    severity: Mapped[str] = mapped_column(String(10), default="low")
    explanation: Mapped[str] = mapped_column(Text, default="")
    reviewer_status: Mapped[ReviewerStatus] = mapped_column(Enum(ReviewerStatus, native_enum=False, length=30), default=ReviewerStatus.PENDING)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    expected_evidence: Mapped[str | None] = mapped_column(String(200))
    suggested_action: Mapped[str | None] = mapped_column(String(300))
    searched_documents: Mapped[list] = mapped_column(JSON, default=list)
    evaluation: Mapped[str | None] = mapped_column(String(200))
    rule_result: Mapped[bool | None] = mapped_column(Boolean)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    rule: Mapped[Rule] = relationship(lazy="joined")
    reviewer = relationship("User", foreign_keys=[reviewed_by], lazy="joined")
    links: Mapped[list["FindingEvidence"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (UniqueConstraint("case_id", "rule_id"),)


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    role: Mapped[EvidenceLinkRole] = mapped_column(Enum(EvidenceLinkRole, native_enum=False, length=20), default=EvidenceLinkRole.SUPPORTING)
    position: Mapped[int] = mapped_column(Integer, default=0)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    id: Mapped[uuid.UUID] = _pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str | None] = mapped_column(String(300))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence.id"))


class AuditEvent(Base):
    """Append-only. A database trigger rejects UPDATE and DELETE (see migration)."""

    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_label: Mapped[str] = mapped_column(String(120))
    actor_kind: Mapped[str] = mapped_column(String(10), default="HUMAN")
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(300))
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


AUDIT_APPEND_ONLY_DDL = [
    """CREATE OR REPLACE FUNCTION audit_events_immutable() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON audit_events
       FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()""",
]
for _stmt in AUDIT_APPEND_ONLY_DDL:
    event.listen(AuditEvent.__table__, "after_create", DDL(_stmt).execute_if(dialect="postgresql"))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(500))
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
