"""Applies the ML document-type suggestion to a Document row. Shared by the processing pipeline and the retry endpoint."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.audit.service import AI_ACTOR, record
from app.ml.classifier import CLASSIFIED, classify_pages
from app.models import Document


def classify_document(db: Session, doc: Document, pages: list[str]) -> None:
    """Never raises for model problems (classify_pages absorbs them). A previous human correction is kept: re-running the
    model replaces only the machine suggestion."""
    result = classify_pages(pages)
    doc.ml_status, doc.ml_label, doc.ml_score = result.status, result.label, result.score
    doc.ml_low_confidence, doc.ml_model_version = result.low_confidence if result.status == CLASSIFIED else None, result.model_version
    doc.ml_classified_at = datetime.now(timezone.utc)
    record(db, action="Document type suggested" if result.status == CLASSIFIED else "Document type not suggested", org_id=doc.organization_id, case_id=doc.case_id,
           actor_label=AI_ACTOR, actor_kind="AI", entity_type="document", entity_id=doc.id, target=doc.filename,
           new={"status": result.status, "label": result.label, "lowConfidence": result.low_confidence, "modelVersion": result.model_version},
           reason="Machine suggestion; not verified")
