"""Human review and retry for the ML document-type suggestion. Org-scoped like every other document route."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import Ctx, require
from app.auth.permissions import Perm
from app.core.errors import AppError
from app.database.session import get_db
from app.ml.classifier import reset_classifier
from app.ml.labels import LABELS
from app.models.enums import DocumentStatus
from app.repositories.scoped import get_document
from app.services.classification import classify_document
from app.services.structured_extraction import extract_fields
from app.services.serializers import classification_dict
from datetime import datetime, timezone

router = APIRouter(tags=["documents"])


class ClassificationReviewIn(BaseModel):
    label: str | None = None  # None clears the human correction


@router.patch("/documents/{document_id}/classification")
def review_classification(document_id: str, body: ClassificationReviewIn, ctx: Ctx = Depends(require(Perm.EVIDENCE_VERIFY)), db: Session = Depends(get_db)):
    doc = get_document(db, ctx.org_id, document_id)
    if body.label is not None and body.label not in LABELS:
        raise AppError(422, "Unknown document category.", "invalid_label")
    old = doc.reviewed_label
    if body.label is None:
        doc.reviewed_label = doc.reviewed_label_by = doc.reviewed_label_at = None
    else:
        doc.reviewed_label, doc.reviewed_label_by, doc.reviewed_label_at = body.label, ctx.user.id, datetime.now(timezone.utc)
    record(db, action="Document type reviewed", org_id=ctx.org_id, ctx=ctx, case_id=doc.case_id, entity_type="document", entity_id=doc.id, target=doc.filename,
           old={"reviewedLabel": old, "suggestedLabel": doc.ml_label}, new={"reviewedLabel": doc.reviewed_label})
    db.commit()
    db.refresh(doc)
    return classification_dict(doc)


@router.post("/documents/{document_id}/classification/retry")
def retry_classification(document_id: str, ctx: Ctx = Depends(require(Perm.CASE_UPDATE)), db: Session = Depends(get_db)):
    doc = get_document(db, ctx.org_id, document_id)
    if doc.status != DocumentStatus.PROCESSED:
        raise AppError(409, "The document must finish processing before it can be classified.", "not_processed")
    reset_classifier()  # pick up a newly trained or repaired artifact without a restart
    classify_document(db, doc, [p.text for p in doc.pages])
    db.commit()
    db.refresh(doc)
    return classification_dict(doc)


@router.get("/documents/{document_id}/structured-fields")
def structured_fields(document_id: str, ctx: Ctx = Depends(require(Perm.CASE_VIEW)), db: Session = Depends(get_db)):
    """Rule-based dates and lab-style results with page and character span, computed on demand from stored pages (nothing persisted)."""
    doc = get_document(db, ctx.org_id, document_id)
    return {"documentId": str(doc.id), **extract_fields([p.text for p in doc.pages])}
