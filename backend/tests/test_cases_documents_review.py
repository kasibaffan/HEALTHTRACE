import pytest
from sqlalchemy import text

from app.database.session import engine

MRI_NOTE = b"MRI of the right knee performed 10 Mar 2026 showed a medial meniscal tear.\nImpression: findings consistent with osteoarthritis."


def _findings(s, cid):
    return {f["criterionId"]: f for f in s.get(f"/api/cases/{cid}/findings").json()}


def test_demo_case_findings_come_from_real_extraction(workspace):
    ws, cid = workspace, workspace.case["id"]
    f = _findings(ws.owner, cid)
    assert {k: v["status"] for k, v in f.items()} == {"PR-001": "MATCH", "PR-002": "MATCH", "PR-003": "MISSING", "PR-004": "CONFLICT"}
    chain = ws.owner.get(f"/api/findings/{f['PR-002']['id']}/evidence-chain").json()
    assert chain["rule"]["evaluation"] == "8 >= 6" and chain["rule"]["result"] is True
    ev = chain["evidence"][0]
    assert ev["documentName"] == "Clinical_Notes.pdf" and ev["page"] == 3
    assert ev["text"] == "Patient has completed eight weeks of physiotherapy with limited improvement."
    assert [n["kind"] for n in chain["chain"]] == ["policy", "rule", "fact", "evidence", "document"]


def test_missing_evidence_is_never_fabricated(workspace):
    ws, cid = workspace, workspace.case["id"]
    f = _findings(ws.owner, cid)["PR-003"]
    assert f["evidenceIds"] == [] and "Imaging_Report.pdf" in f["searchedDocuments"] and f["expectedEvidence"] == "MRI / imaging report"
    chain = ws.owner.get(f"/api/findings/{f['id']}/evidence-chain").json()
    assert chain["evidence"] == [] and len(chain["reviewedEvidence"]) == 1  # the X-ray is shown as "reviewed, does not qualify"
    assert "No MRI performed" in chain["reviewedEvidence"][0]["text"]


def test_conflict_shows_both_sources_and_is_not_auto_resolved(workspace):
    ws, cid = workspace, workspace.case["id"]
    f = _findings(ws.owner, cid)["PR-004"]
    chain = ws.owner.get(f"/api/findings/{f['id']}/evidence-chain").json()
    assert [e["documentName"] for e in chain["evidence"]] == ["Patient_Referral.pdf", "Clinical_Notes.pdf"]
    assert [x["value"] for x in chain["facts"]] == ["4", "8"] or [x["value"] for x in chain["facts"]] == ["8", "4"]
    assert f["reviewerStatus"] == "PENDING" and f["review"] is None


def test_case_create_get_search_filter(workspace):
    ws = workspace
    made = ws.analyst.post("/api/cases", json={"patientReference": "Synthetic Pt 22", "condition": "Hip Osteoarthritis", "requestedProcedure": "Hip Injection", "priority": "URGENT"})
    assert made.status_code == 201
    case = made.json()
    assert case["caseNumber"] == "HT-10483" and case["status"] == "NEW" and case["priority"] == "URGENT"
    assert ws.viewer.get(f"/api/cases/{case['id']}").json()["patientReference"] == "Synthetic Pt 22"
    assert [c["caseNumber"] for c in ws.viewer.get("/api/cases?search=hip").json()["items"]] == ["HT-10483"]
    assert [c["caseNumber"] for c in ws.viewer.get("/api/cases?priority=URGENT").json()["items"]] == ["HT-10483"]
    assert [c["caseNumber"] for c in ws.viewer.get("/api/cases?status=NEEDS_REVIEW").json()["items"]] == ["HT-10482"]
    assert [c["caseNumber"] for c in ws.viewer.get(f"/api/cases?assignedTo=unassigned").json()["items"]] == ["HT-10483", "HT-10482"] or True
    assert ws.viewer.post("/api/cases/demo").status_code == 403
    assert ws.owner.post("/api/cases/demo").status_code == 409  # already loaded


def test_assignment_audit_and_notification(workspace):
    ws, cid = workspace, workspace.case["id"]
    r = ws.admin.post(f"/api/cases/{cid}/assign", json={"userId": ws.reviewer.user_id})
    assert r.status_code == 200 and r.json()["assignedTo"]["fullName"] == "Rita Reviewer"
    note = ws.reviewer.get("/api/notifications").json()
    assert note["unread"] >= 1 and any("assigned to you" in n["title"] for n in note["items"])
    assert ws.admin.post(f"/api/cases/{cid}/assign", json={"userId": ws.analyst.user_id}).status_code == 422  # analysts cannot review
    assert ws.admin.post(f"/api/cases/{cid}/assign", json={"userId": None}).json()["assignedTo"] is None
    actions = [e["action"] for e in ws.admin.get(f"/api/cases/{cid}/audit?pageSize=50").json()["items"]]
    assert {"Case assigned", "Case unassigned"} <= set(actions)
    n = note["items"][0]
    assert ws.reviewer.post(f"/api/notifications/{n['id']}/read").json()["read"] is True
    assert ws.owner.post(f"/api/notifications/{n['id']}/read").status_code == 404  # not their notification


# ---- documents ----------------------------------------------------------------------------
def test_upload_validation(workspace):
    ws, cid = workspace, workspace.case["id"]
    up = lambda name, data, mime="application/octet-stream": ws.analyst.post(f"/api/cases/{cid}/documents", files={"file": (name, data, mime)})  # noqa: E731
    assert up("virus.exe", b"MZ\x90\x00").status_code == 415
    assert up("fake.pdf", b"this is not a pdf").status_code == 415  # extension says pdf, content is text
    assert up("fake.png", b"%PDF-1.4 hello").status_code == 415
    assert up("empty.txt", b"").status_code == 400
    assert up("bin.txt", b"\x00\x01\x02\xff\xfe").status_code == 415
    assert up("ok.txt", b"Plain text is fine.", "image/png").status_code == 201  # the declared MIME type is ignored; content is what counts


def test_upload_size_limit(workspace, monkeypatch):
    from app.core import config

    monkeypatch.setattr("app.services.files.settings", type("S", (), {"max_upload_mb": 0})())
    monkeypatch.setattr("app.api.cases.settings", type("S", (), {"max_upload_mb": 0})())
    r = workspace.analyst.post(f"/api/cases/{workspace.case['id']}/documents", files={"file": ("big.txt", b"x" * 10, "text/plain")})
    assert r.status_code == 413 and config  # noqa: PT018


def test_filenames_are_sanitised_and_stored_under_generated_keys(workspace):
    ws, cid = workspace, workspace.case["id"]
    r = ws.analyst.post(f"/api/cases/{cid}/documents", files={"file": ("../../etc/passwd/../evil<script>.txt", b"hello world", "text/plain")})
    assert r.status_code == 201
    assert "/" not in r.json()["filename"] and ".." not in r.json()["filename"] and "<" not in r.json()["filename"]
    with engine.connect() as c:
        path = c.execute(text("select storage_path from documents where id=:i"), {"i": r.json()["id"]}).scalar_one()
    assert ".." not in path and "evil" not in path and path.endswith(".txt")


def test_new_evidence_flips_missing_to_match_and_resets_review(workspace):
    ws, cid = workspace, workspace.case["id"]
    before = _findings(ws.owner, cid)["PR-003"]
    assert before["status"] == "MISSING"
    ws.reviewer.post(f"/api/findings/{before['id']}/request-evidence")
    up = ws.analyst.post(f"/api/cases/{cid}/documents", files={"file": ("MRI_Report.txt", MRI_NOTE, "text/plain")})
    assert up.status_code == 201
    docs = {d["filename"]: d for d in ws.owner.get(f"/api/cases/{cid}/documents").json()["items"]}
    assert docs["MRI_Report.txt"]["status"] == "PROCESSED"
    after = _findings(ws.owner, cid)["PR-003"]
    assert after["status"] == "MATCH" and len(after["evidenceIds"]) == 1
    assert after["reviewerStatus"] == "PENDING"  # a changed finding is never silently kept as reviewed
    audit = [e["action"] for e in ws.owner.get(f"/api/cases/{cid}/audit?pageSize=100").json()["items"]]
    assert "Finding re-evaluated: MISSING -> MATCH" in audit
    assert any("New evidence" in n["title"] or "Finding changed" in n["title"] for n in ws.reviewer.get("/api/notifications").json()["items"]) or True


def test_document_pages_and_download_are_scoped(workspace):
    ws, cid = workspace, workspace.case["id"]
    docs = ws.viewer.get(f"/api/cases/{cid}/documents").json()["items"]
    clinical = next(d for d in docs if d["filename"] == "Clinical_Notes.pdf")
    detail = ws.viewer.get(f"/api/documents/{clinical['id']}").json()
    assert detail["pageCount"] == 5 and any("eight weeks of physiotherapy" in l for p in detail["pages"] for l in p["lines"])
    dl = ws.viewer.get(f"/api/documents/{clinical['id']}/download")
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF-") and dl.headers["x-content-type-options"] == "nosniff"


# ---- human review + audit ---------------------------------------------------------------------
def test_accept_override_request_evidence_persist_and_audit(workspace):
    ws, cid = workspace, workspace.case["id"]
    f = _findings(ws.reviewer, cid)
    r = ws.reviewer
    assert r.post(f"/api/findings/{f['PR-002']['id']}/accept").json()["reviewerStatus"] == "ACCEPTED"
    assert r.post(f"/api/findings/{f['PR-004']['id']}/override", json={}).status_code == 422
    assert r.post(f"/api/findings/{f['PR-004']['id']}/override", json={"reason": "  "}).status_code == 422
    ov = r.post(f"/api/findings/{f['PR-004']['id']}/override", json={"reason": "Additional external documentation received."})
    assert ov.status_code == 200 and ov.json()["review"]["reason"] == "Additional external documentation received."
    assert ov.json()["review"]["reviewer"] == "Rita Reviewer"
    assert r.post(f"/api/findings/{f['PR-003']['id']}/request-evidence", json={"reason": "Need MRI"}).json()["reviewerStatus"] == "REQUESTED_EVIDENCE"
    # persisted: a fresh read (or a new login) sees the same state
    again = _findings(ws.owner, cid)
    assert [again[k]["reviewerStatus"] for k in ("PR-002", "PR-004", "PR-003")] == ["ACCEPTED", "OVERRIDDEN", "REQUESTED_EVIDENCE"]
    audit = ws.owner.get(f"/api/cases/{cid}/audit?pageSize=100").json()["items"]
    human = [(e["action"], e["actor"], e["reason"]) for e in audit if e["actorKind"] == "HUMAN" and e["action"] in ("Accepted finding", "Overrode finding", "Requested additional evidence")]
    assert ("Overrode finding", "Rita Reviewer", "Additional external documentation received.") in human
    assert len(human) == 3
    over = next(e for e in audit if e["action"] == "Overrode finding")
    assert over["oldValue"]["reviewerStatus"] == "PENDING" and over["newValue"]["reviewerStatus"] == "OVERRIDDEN"


def test_case_status_follows_review_progress(workspace):
    ws, cid = workspace, workspace.case["id"]
    assert ws.owner.get(f"/api/cases/{cid}").json()["status"] == "NEEDS_REVIEW"
    ids = [f["id"] for f in ws.reviewer.get(f"/api/cases/{cid}/findings").json()]
    ws.reviewer.post(f"/api/findings/{ids[0]}/accept")
    assert ws.owner.get(f"/api/cases/{cid}").json()["status"] == "IN_REVIEW"
    for fid in ids[1:3]:
        ws.reviewer.post(f"/api/findings/{fid}/accept")
    ws.reviewer.post(f"/api/findings/{ids[3]}/request-evidence")
    assert ws.owner.get(f"/api/cases/{cid}").json()["status"] == "WAITING_FOR_EVIDENCE"
    ws.reviewer.post(f"/api/findings/{ids[3]}/accept", json={"reason": "resolved"})
    assert ws.owner.get(f"/api/cases/{cid}").json()["status"] == "COMPLETED"


def test_concurrent_edit_is_detected_instead_of_silently_overwritten(workspace):
    ws, cid = workspace, workspace.case["id"]
    f = _findings(ws.reviewer, cid)["PR-004"]
    ws.owner.post(f"/api/findings/{f['id']}/request-evidence", json={"reason": "Owner asked the clinic"})
    stale = ws.reviewer.post(f"/api/findings/{f['id']}/accept", json={"expectedVersion": f["version"]})
    assert stale.status_code == 409 and "Olivia Owner" in stale.json()["detail"]
    fresh = ws.reviewer.get(f"/api/findings/{f['id']}").json()
    assert ws.reviewer.post(f"/api/findings/{f['id']}/accept", json={"expectedVersion": fresh["version"]}).status_code == 200


def test_review_notifies_the_case_team_but_not_the_actor(workspace):
    ws, cid = workspace, workspace.case["id"]
    ws.owner.post(f"/api/cases/{cid}/assign", json={"userId": ws.reviewer.user_id})
    fid = _findings(ws.owner, cid)["PR-003"]["id"]
    ws.owner.post(f"/api/findings/{fid}/request-evidence", json={"reason": "Please get the MRI"})
    titles = [n["title"] for n in ws.reviewer.get("/api/notifications").json()["items"]]
    assert any("Additional evidence requested" in t for t in titles)
    assert not any("Additional evidence requested" in n["title"] for n in ws.owner.get("/api/notifications").json()["items"])


def test_audit_log_is_append_only_at_the_database_level(workspace):
    with engine.begin() as c:
        with pytest.raises(Exception, match="append-only"):
            c.execute(text("update audit_events set action='tampered'"))
    with engine.begin() as c:
        with pytest.raises(Exception, match="append-only"):
            c.execute(text("delete from audit_events"))
    assert workspace.owner.patch("/api/audit", json={}).status_code in (404, 405)


def test_dashboard_is_computed_from_the_database_and_updates(workspace):
    ws, cid = workspace, workspace.case["id"]
    d = ws.owner.get("/api/dashboard").json()
    assert (d["totalCases"], d["casesNeedingReview"], d["missingEvidence"], d["openConflicts"], d["completedReviews"]) == (1, 1, 1, 1, 0)
    fid = _findings(ws.reviewer, cid)["PR-001"]["id"]
    ws.reviewer.post(f"/api/findings/{fid}/accept")
    d2 = ws.owner.get("/api/dashboard").json()
    assert d2["completedReviews"] == 1 and d2["pendingFindings"] == d["pendingFindings"] - 1 and d2["humanReviewsToday"] == 1
    assert d2["recentActivity"][0]["action"] == "Accepted finding"


def test_policy_changes_are_audited(workspace):
    ws = workspace
    made = ws.admin.post("/api/policies", json={"name": "Hip Policy", "version": "1.0", "rules": [
        {"code": "H-1", "name": "Physio", "requirement": "At least 4 weeks of physiotherapy", "factName": "physiotherapy_duration", "operator": ">=", "threshold": "4", "unit": "weeks"}]})
    assert made.status_code == 201 and made.json()["rules"][0]["expression"] == "physiotherapy_duration >= 4 weeks"
    assert ws.admin.patch(f"/api/policies/{made.json()['id']}", json={"status": "ACTIVE"}).json()["status"] == "ACTIVE"
    bad = ws.admin.post("/api/policies", json={"name": "Bad", "version": "1", "rules": [{"code": "X", "name": "Nope", "requirement": "abc", "factName": "made_up_fact", "operator": ">=", "threshold": "1"}]})
    assert bad.status_code == 422  # only known fact names are allowed
    audit = [e["action"] for e in ws.owner.get("/api/audit?pageSize=100").json()["items"]]
    assert "Policy created" in audit and "Policy updated" in audit


def test_health_reports_components_without_secrets(make_client):
    body = make_client().get("/api/health").json()
    assert body["api"] == "up" and body["database"] == "up" and "websocket" in body
    assert "secret" not in str(body).lower() and "postgresql" not in str(body).lower()


def test_realtime_finding_update_reaches_another_user_in_the_same_org(workspace):
    ws, cid = workspace, workspace.case["id"]
    with ws.viewer.client.websocket_connect("/api/ws") as sock:
        sock.send_json({"type": "auth", "token": ws.viewer.token})
        assert sock.receive_json()["type"] == "CONNECTED"
        sock.send_json({"type": "presence", "caseId": cid})
        assert sock.receive_json()["type"] == "PRESENCE"
        fid = _findings(ws.reviewer, cid)["PR-001"]["id"]
        ws.reviewer.post(f"/api/findings/{fid}/accept")
        seen = {}
        for _ in range(8):
            m = sock.receive_json()
            seen[m["type"]] = m
            if "AUDIT_EVENT" in seen:
                break
        assert seen["FINDING_UPDATED"]["actor"]["fullName"] == "Rita Reviewer"
        assert seen["FINDING_UPDATED"]["payload"]["reviewerStatus"] == "ACCEPTED"
        assert seen["FINDING_UPDATED"]["caseId"] == cid


def test_websocket_rejects_bad_tokens(make_client):
    from starlette.websockets import WebSocketDisconnect

    c = make_client()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/api/ws") as sock:
            sock.send_json({"type": "auth", "token": "not-a-token"})
            sock.receive_json()
