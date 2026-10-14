"""CRITICAL: multi-tenant isolation and role-based access control, enforced on the backend."""
import pytest


@pytest.fixture
def two_orgs(register):
    a = register("alice@orga.test", "Org A", "Alice")
    b = register("bob@orgb.test", "Org B", "Bob")
    ca = a.post("/api/cases/demo").json()
    cb = b.post("/api/cases/demo").json()
    return a, b, ca, cb


def _finding_ids(session, case_id):
    return [f["id"] for f in session.get(f"/api/cases/{case_id}/findings").json()]


def test_org_a_user_cannot_retrieve_org_b_case(two_orgs):
    a, b, ca, cb = two_orgs
    assert a.get(f"/api/cases/{ca['id']}").status_code == 200
    r = a.get(f"/api/cases/{cb['id']}")
    assert r.status_code == 404  # indistinguishable from a non-existent case
    assert a.get(f"/api/cases/{cb['id']}/findings").status_code == 404
    assert a.get(f"/api/cases/{cb['id']}/timeline").status_code == 404
    assert a.get(f"/api/cases/{cb['id']}/documents").status_code == 404
    assert a.get(f"/api/cases/{cb['id']}/audit").status_code == 404
    assert a.patch(f"/api/cases/{cb['id']}", json={"status": "ARCHIVED"}).status_code == 404


def test_org_a_user_cannot_retrieve_org_b_evidence(two_orgs):
    a, b, ca, cb = two_orgs
    b_evidence = b.get(f"/api/cases/{cb['id']}/evidence").json()["items"]
    assert b_evidence
    for ev in b_evidence:
        assert a.get(f"/api/evidence/{ev['id']}").status_code == 404
        assert a.post(f"/api/evidence/{ev['id']}/verify").status_code == 404
    assert a.get(f"/api/cases/{cb['id']}/evidence").status_code == 404


def test_org_a_cannot_touch_org_b_findings_documents_and_chain(two_orgs):
    a, b, ca, cb = two_orgs
    fid = _finding_ids(b, cb["id"])[0]
    assert a.get(f"/api/findings/{fid}").status_code == 404
    assert a.get(f"/api/findings/{fid}/evidence-chain").status_code == 404
    assert a.post(f"/api/findings/{fid}/accept").status_code == 404
    assert a.post(f"/api/findings/{fid}/override", json={"reason": "attack"}).status_code == 404
    assert a.post(f"/api/findings/{fid}/request-evidence").status_code == 404
    doc = b.get(f"/api/cases/{cb['id']}/documents").json()["items"][0]
    assert a.get(f"/api/documents/{doc['id']}").status_code == 404
    assert a.get(f"/api/documents/{doc['id']}/download").status_code == 404
    # The finding was not modified by the failed attempts.
    assert b.get(f"/api/findings/{fid}").json()["reviewerStatus"] == "PENDING"


def test_lists_search_audit_and_users_never_leak_across_orgs(two_orgs):
    a, b, ca, cb = two_orgs
    ids_a = {c["id"] for c in a.get("/api/cases").json()["items"]}
    assert ids_a == {ca["id"]}
    assert {c["id"] for c in a.get("/api/cases?search=John").json()["items"]} == {ca["id"]}
    b_evidence_ids = {e["id"] for e in b.get("/api/evidence").json()["items"]}
    a_evidence_ids = {e["id"] for e in a.get("/api/evidence?search=physiotherapy").json()["items"]}
    assert a_evidence_ids and not (a_evidence_ids & b_evidence_ids)
    assert all(e["caseId"] == ca["id"] for e in a.get("/api/audit").json()["items"] if e["caseId"])
    assert a.get(f"/api/audit?caseId={cb['id']}").json()["total"] == 0
    assert {u["email"] for u in a.get("/api/users").json()["items"]} == {"alice@orga.test"}
    assert a.get(f"/api/users/{b.user_id}").status_code == 404
    assert a.patch(f"/api/users/{b.user_id}", json={"role": "VIEWER"}).status_code == 404
    assert len(a.get("/api/policies").json()) == 1 and b.get("/api/policies").json()[0]["id"] != a.get("/api/policies").json()[0]["id"]


def test_cannot_assign_a_case_to_a_user_from_another_org(two_orgs):
    a, b, ca, cb = two_orgs
    r = a.post(f"/api/cases/{ca['id']}/assign", json={"userId": b.user_id})
    assert r.status_code == 404


def test_client_supplied_organization_ids_are_ignored(register):
    a = register("mass@orga.test", "Org A")
    b = register("mass@orgb.test", "Org B")
    b_org = b.get("/api/auth/me").json()["organization"]["id"]
    r = a.post("/api/cases", json={"patientReference": "Pt-001", "condition": "Cond", "requestedProcedure": "Proc", "organizationId": b_org})
    assert r.status_code == 422  # unknown fields are rejected outright (extra=forbid)
    ok = a.post("/api/cases", json={"patientReference": "Pt-001", "condition": "Cond", "requestedProcedure": "Proc"}).json()
    assert b.get(f"/api/cases/{ok['id']}").status_code == 404


def test_websocket_events_never_cross_organizations(two_orgs):
    a, b, ca, cb = two_orgs
    from tests.conftest import app  # noqa: F401
    with a.client.websocket_connect("/api/ws") as wa, b.client.websocket_connect("/api/ws") as wb:
        wa.send_json({"type": "auth", "token": a.token})
        wb.send_json({"type": "auth", "token": b.token})
        assert wa.receive_json()["type"] == "CONNECTED" and wb.receive_json()["type"] == "CONNECTED"
        fid = _finding_ids(a, ca["id"])[0]
        a.post(f"/api/findings/{fid}/accept")
        types = set()
        for _ in range(6):
            types.add(wa.receive_json()["type"])
            if "REVIEW_ACTION" in types:
                break
        assert "REVIEW_ACTION" in types
        wb.send_json({"type": "ping"})
        assert wb.receive_json()["type"] == "pong"  # the only thing org B ever receives is its own pong


# ---- RBAC --------------------------------------------------------------------------------
def test_viewer_is_read_only(workspace):
    ws = workspace
    v, cid = ws.viewer, ws.case["id"]
    assert v.get(f"/api/cases/{cid}").status_code == 200
    assert v.get(f"/api/cases/{cid}/findings").status_code == 200
    fid = _finding_ids(v, cid)[0]
    assert v.get(f"/api/findings/{fid}/evidence-chain").status_code == 200
    assert v.post(f"/api/findings/{fid}/accept").status_code == 403
    assert v.post(f"/api/findings/{fid}/override", json={"reason": "no"}).status_code == 403
    assert v.post(f"/api/findings/{fid}/request-evidence").status_code == 403
    assert v.post("/api/cases", json={"patientReference": "P", "condition": "C", "requestedProcedure": "X"}).status_code == 403
    assert v.post(f"/api/cases/{cid}/documents", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 403
    assert v.post(f"/api/cases/{cid}/assign", json={"userId": ws.reviewer.user_id}).status_code == 403
    assert v.get("/api/audit").status_code == 403
    assert v.post("/api/users/invite", json={"email": "x@y.test", "role": "VIEWER"}).status_code == 403
    assert v.patch(f"/api/users/{ws.analyst.user_id}", json={"role": "VIEWER"}).status_code == 403
    assert v.post("/api/policies", json={"name": "P", "version": "1"}).status_code == 403


def test_analyst_can_create_and_upload_but_not_review(workspace):
    ws = workspace
    a, cid = ws.analyst, ws.case["id"]
    made = a.post("/api/cases", json={"patientReference": "Pt 9", "condition": "Knee OA", "requestedProcedure": "Injection"})
    assert made.status_code == 201
    up = a.post(f"/api/cases/{made.json()['id']}/documents", files={"file": ("notes.txt", b"Patient completed 7 weeks of physiotherapy.", "text/plain")})
    assert up.status_code == 201
    fid = _finding_ids(a, cid)[0]
    assert a.post(f"/api/findings/{fid}/accept").status_code == 403
    assert a.get("/api/audit").status_code == 403
    assert a.get(f"/api/cases/{cid}/evidence").status_code == 200


def test_reviewer_can_review_and_view_audit_but_not_create_or_manage(workspace):
    ws = workspace
    r, cid = ws.reviewer, ws.case["id"]
    fid = _finding_ids(r, cid)[0]
    assert r.post(f"/api/findings/{fid}/accept").status_code == 200
    assert r.get("/api/audit").status_code == 200
    assert r.post("/api/cases", json={"patientReference": "P", "condition": "C", "requestedProcedure": "X"}).status_code == 403
    assert r.post(f"/api/cases/{cid}/documents", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 403
    assert r.post("/api/users/invite", json={"email": "x@y.test", "role": "VIEWER"}).status_code == 403
    assert r.post(f"/api/cases/{cid}/assign", json={"userId": r.user_id}).status_code == 200


def test_admin_manages_users_cases_policies_but_does_not_review(workspace):
    ws = workspace
    ad, cid = ws.admin, ws.case["id"]
    assert ad.patch(f"/api/users/{ws.analyst.user_id}", json={"role": "VIEWER"}).status_code == 200
    assert ad.post("/api/users/invite", json={"email": "n@a.test", "role": "REVIEWER"}).status_code == 201
    assert ad.post("/api/users/invite", json={"email": "n2@a.test", "role": "ADMIN"}).status_code == 403  # no lateral/upward escalation
    assert ad.patch(f"/api/users/{ws.owner.user_id}", json={"isActive": False}).status_code == 403
    assert ad.patch("/api/organization", json={"name": "Renamed"}).status_code == 403  # owner only
    assert ad.get("/api/audit").status_code == 200
    assert ad.post("/api/policies", json={"name": "Draft policy", "version": "1.0"}).status_code == 201
    assert ad.post(f"/api/findings/{_finding_ids(ad, cid)[0]}/accept").status_code == 403


def test_owner_has_full_access_and_last_owner_is_protected(workspace):
    ws = workspace
    assert ws.owner.patch("/api/organization", json={"name": "Renamed Org"}).status_code == 200
    assert ws.owner.patch(f"/api/users/{ws.owner.user_id}", json={"role": "VIEWER"}).status_code == 403  # cannot change self
    promoted = ws.owner.patch(f"/api/users/{ws.admin.user_id}", json={"role": "OWNER"})
    assert promoted.status_code == 200
    assert ws.admin.patch(f"/api/users/{ws.owner.user_id}", json={"role": "ADMIN"}).status_code == 200  # a second owner may demote the first
    assert ws.admin.patch(f"/api/users/{ws.reviewer.user_id}", json={"role": "VIEWER"}).status_code == 200


def test_pagination_is_enforced(workspace):
    ws = workspace
    assert ws.owner.get("/api/cases?pageSize=1000").status_code == 422
    r = ws.owner.get("/api/users?pageSize=2&page=1").json()
    assert len(r["items"]) == 2 and r["total"] == 5 and r["pageSize"] == 2
    assert ws.owner.get("/api/audit?pageSize=5").json()["items"].__len__() == 5
