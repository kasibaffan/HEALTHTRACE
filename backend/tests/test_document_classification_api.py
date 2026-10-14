"""ML classification wired into the document workflow: persistence, RBAC, tenant isolation, failure tolerance, compatibility."""
import dataclasses

import pytest
from sqlalchemy import select

from app.core.config import settings as real_settings
from app.database.session import SessionLocal
from app.ml import classifier as clf_mod
from app.ml import training
from app.ml.labels import CLAIM_BILLING, REFERRAL_ORDER
from app.models import AuditEvent, Document

CLAIM = (b"Claim number CLM-55123 payer Example Assurance date of service 12 March 2025. Line 1: CPT 99213 units 1 charge $145.00. "
         b"Total billed $145.00 allowed amount $110.00 patient responsibility $35.00. Billing provider NPI 1234567890.")
CANARY = "ZEBRA-CANARY-9942"


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("api-model")
    model, report = training.train(per_class=40, seed=3, cv_folds=3, c_grid=(3.0,), challenge_path=None)
    training.save_artifacts(model, report, out)
    return out


@pytest.fixture
def with_model(monkeypatch, model_dir):
    monkeypatch.setattr(clf_mod, "settings", dataclasses.replace(real_settings, doc_classifier_artifact_dir=model_dir))
    clf_mod.reset_classifier()
    yield
    clf_mod.reset_classifier()


@pytest.fixture
def without_model(monkeypatch, tmp_path):
    monkeypatch.setattr(clf_mod, "settings", dataclasses.replace(real_settings, doc_classifier_artifact_dir=tmp_path / "missing"))
    clf_mod.reset_classifier()
    yield
    clf_mod.reset_classifier()


def _upload(session, case_id, name="Billing_Statement.txt", data=CLAIM):
    r = session.post(f"/api/cases/{case_id}/documents", files={"file": (name, data, "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()


def _doc(session, doc_id):
    return session.get(f"/api/documents/{doc_id}").json()


def test_upload_is_classified_and_persisted_without_changing_existing_fields(workspace, with_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    assert up["classification"]["status"] == "NOT_RUN"  # the 201 response is returned before background processing
    d = _doc(ws.viewer, up["id"])
    c = d["classification"]
    assert d["status"] == "PROCESSED" and d["docType"] == "Supporting"  # filename-derived doc_type is untouched
    assert c["status"] == "CLASSIFIED" and c["label"] == CLAIM_BILLING and c["effectiveLabel"] == CLAIM_BILLING
    assert c["modelVersion"] and 0 < c["score"] <= 1 and c["reviewedLabel"] is None and c["classifiedAt"]
    # existing contract still present
    assert {"id", "caseId", "filename", "fileType", "fileSize", "docType", "status", "pageCount", "progress", "error", "uploadedBy"} <= d.keys()
    listed = ws.viewer.get(f"/api/cases/{ws.case['id']}/documents").json()["items"]
    assert any(x["id"] == up["id"] and x["classification"]["label"] == CLAIM_BILLING for x in listed)


def test_classification_is_audited_as_an_unverified_ai_suggestion(workspace, with_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    with SessionLocal() as db:
        ev = db.execute(select(AuditEvent).where(AuditEvent.entity_id == up["id"], AuditEvent.action == "Document type suggested")).scalar_one()
        assert ev.actor_kind == "AI" and "not verified" in ev.reason and ev.new_value["label"] == CLAIM_BILLING


def test_processing_still_succeeds_when_model_is_unavailable(workspace, without_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    d = _doc(ws.owner, up["id"])
    assert d["status"] == "PROCESSED" and d["error"] is None
    assert d["classification"]["status"] == "UNAVAILABLE" and d["classification"]["label"] is None
    assert len(ws.owner.get(f"/api/cases/{ws.case['id']}/findings").json()) == 4  # rule evaluation unaffected


def test_unreadable_image_gets_no_text_status_not_a_guess(workspace, with_model):
    ws = workspace
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = ws.analyst.post(f"/api/cases/{ws.case['id']}/documents", files={"file": ("scan.png", png, "image/png")}).json()
    c = _doc(ws.owner, up["id"])["classification"]
    assert c["status"] == "NO_TEXT" and c["label"] is None


def test_legacy_documents_without_a_classification_report_not_run(workspace):
    d = workspace.owner.get(f"/api/cases/{workspace.case['id']}/documents").json()["items"][0]
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == d["id"])).unique().scalar_one()
        doc.ml_status = doc.ml_label = doc.ml_score = None
        db.commit()
    c = workspace.owner.get(f"/api/documents/{d['id']}").json()["classification"]
    assert c["status"] == "NOT_RUN" and c["label"] is None and c["effectiveLabel"] is None and c["lowConfidence"] is False


def test_reviewer_can_correct_and_clear_a_prediction(workspace, with_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    r = ws.reviewer.patch(f"/api/documents/{up['id']}/classification", json={"label": REFERRAL_ORDER})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["label"] == CLAIM_BILLING and c["reviewedLabel"] == REFERRAL_ORDER and c["effectiveLabel"] == REFERRAL_ORDER
    assert c["reviewedBy"]["fullName"] == "Rita Reviewer" and c["reviewedAt"]
    audit = ws.owner.get(f"/api/cases/{ws.case['id']}/audit?pageSize=100").json()["items"]
    assert any(a["action"] == "Document type reviewed" and a["actor"] == "Rita Reviewer" and a["newValue"] == {"reviewedLabel": REFERRAL_ORDER} for a in audit)
    cleared = ws.reviewer.patch(f"/api/documents/{up['id']}/classification", json={"label": None}).json()
    assert cleared["reviewedLabel"] is None and cleared["effectiveLabel"] == CLAIM_BILLING


def test_invalid_label_is_rejected(workspace, with_model):
    up = _upload(workspace.analyst, workspace.case["id"])
    for bad in ("MADE_UP", "", "clinical_report", 5):
        assert workspace.reviewer.patch(f"/api/documents/{up['id']}/classification", json={"label": bad}).status_code in (400, 422)
    assert _doc(workspace.owner, up["id"])["classification"]["reviewedLabel"] is None


def test_review_permissions(workspace, with_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    url = f"/api/documents/{up['id']}/classification"
    assert ws.viewer.patch(url, json={"label": REFERRAL_ORDER}).status_code == 403
    assert ws.analyst.patch(url, json={"label": REFERRAL_ORDER}).status_code == 403
    assert ws.admin.patch(url, json={"label": REFERRAL_ORDER}).status_code == 403
    assert ws.owner.patch(url, json={"label": REFERRAL_ORDER}).status_code == 200
    anon = ws.owner.client.patch(url, json={"label": REFERRAL_ORDER}, headers={"Authorization": "Bearer nope"})
    assert anon.status_code == 401


def test_other_organisations_cannot_see_review_or_retry_a_document(workspace, register, with_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    outsider = register("eve@other.test", "Org B", "Eve")
    assert outsider.get(f"/api/documents/{up['id']}").status_code == 404
    assert outsider.patch(f"/api/documents/{up['id']}/classification", json={"label": REFERRAL_ORDER}).status_code == 404
    assert outsider.post(f"/api/documents/{up['id']}/classification/retry").status_code == 404
    assert _doc(ws.owner, up["id"])["classification"]["reviewedLabel"] is None


def test_retry_recovers_after_the_model_becomes_available_and_keeps_human_correction(workspace, monkeypatch, model_dir, without_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    assert _doc(ws.owner, up["id"])["classification"]["status"] == "UNAVAILABLE"
    ws.reviewer.patch(f"/api/documents/{up['id']}/classification", json={"label": REFERRAL_ORDER})
    monkeypatch.setattr(clf_mod, "settings", dataclasses.replace(real_settings, doc_classifier_artifact_dir=model_dir))
    r = ws.analyst.post(f"/api/documents/{up['id']}/classification/retry")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "CLASSIFIED" and c["label"] == CLAIM_BILLING and c["reviewedLabel"] == REFERRAL_ORDER
    assert ws.viewer.post(f"/api/documents/{up['id']}/classification/retry").status_code == 403


def test_retry_requires_a_processed_document(workspace, with_model):
    ws = workspace
    up = _upload(ws.analyst, ws.case["id"])
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == up["id"])).unique().scalar_one()
        doc.status = type(doc.status).PROCESSING
        db.commit()
    assert ws.analyst.post(f"/api/documents/{up['id']}/classification/retry").status_code == 409


def test_document_text_is_not_logged_by_the_pipeline(workspace, with_model, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        _upload(workspace.analyst, workspace.case["id"], data=f"Claim number CLM-1 billed charge CPT payer allowed amount {CANARY}".encode())
    assert CANARY not in caplog.text
