from sqlalchemy import text

from app.database.session import engine
from tests.conftest import PASSWORD


def test_register_creates_user_org_membership_and_logs_in(register):
    s = register("kasib@example.test", "Acentra Review Team", "Kasib")
    me = s.get("/api/auth/me").json()
    assert me["user"]["email"] == "kasib@example.test"
    assert me["organization"]["name"] == "Acentra Review Team"
    assert me["role"] == "OWNER" and "org:manage" in me["permissions"]
    assert "passwordHash" not in str(me) and "password" not in me["user"]


def test_password_is_hashed_with_argon2_never_stored_plaintext(register):
    register("hash@example.test")
    with engine.connect() as c:
        stored = c.execute(text("select password_hash from users where email='hash@example.test'")).scalar_one()
    assert stored.startswith("$argon2") and PASSWORD not in stored


def test_registration_validation(make_client):
    c = make_client()
    base = {"fullName": "A B", "email": "a@b.test", "password": PASSWORD, "confirmPassword": PASSWORD}
    assert c.post("/api/auth/register", json={**base, "confirmPassword": "different"}).status_code == 422
    assert c.post("/api/auth/register", json={**base, "password": "short", "confirmPassword": "short"}).status_code == 422
    assert c.post("/api/auth/register", json={**base, "password": "alllowercase123", "confirmPassword": "alllowercase123"}).status_code == 422
    assert c.post("/api/auth/register", json={**base, "email": "not-an-email"}).status_code == 422
    assert c.post("/api/auth/register", json=base).status_code == 201
    dup = c.post("/api/auth/register", json={**base, "email": "A@B.test"})
    assert dup.status_code == 409


def test_login_and_invalid_login(register, make_client):
    register("login@example.test")
    c = make_client()
    ok = c.post("/api/auth/login", json={"email": "LOGIN@example.test", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["accessToken"]
    bad = c.post("/api/auth/login", json={"email": "login@example.test", "password": "Wrong-Password1"})
    unknown = c.post("/api/auth/login", json={"email": "nobody@example.test", "password": "Wrong-Password1"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]  # no user enumeration


def test_routes_require_authentication(make_client):
    c = make_client()
    for url in ("/api/cases", "/api/dashboard", "/api/evidence", "/api/audit", "/api/policies", "/api/users", "/api/notifications", "/api/auth/me"):
        assert c.get(url).status_code == 401, url
    assert c.get("/api/cases", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_rotates_and_reuse_is_detected(register, make_client):
    s = register("rot@example.test")
    old_cookie = s.client.cookies.get("ht_refresh")
    first = s.client.post("/api/auth/refresh")
    assert first.status_code == 200
    new_cookie = s.client.cookies.get("ht_refresh")
    assert new_cookie != old_cookie
    # Replaying the already-rotated token is treated as theft and kills every session.
    thief = make_client()
    thief.cookies.set("ht_refresh", old_cookie, path="/api/auth")
    assert thief.post("/api/auth/refresh").status_code == 401
    assert s.client.post("/api/auth/refresh").status_code == 401
    assert s.get("/api/auth/me").status_code == 401  # even the access token is dead: its session was revoked


def test_logout_invalidates_refresh_token(register):
    s = register("out@example.test")
    assert s.client.post("/api/auth/logout").status_code == 200
    assert s.client.post("/api/auth/refresh").status_code == 401
    assert s.get("/api/auth/me").status_code == 401


def test_logout_all_revokes_every_session(register, make_client):
    s = register("all@example.test")
    other = make_client()
    other.post("/api/auth/login", json={"email": "all@example.test", "password": PASSWORD})
    assert s.post("/api/auth/logout-all").status_code == 200
    assert other.post("/api/auth/refresh").status_code == 401


def test_password_reset_flow_revokes_sessions(register, make_client):
    s = register("reset@example.test")
    c = make_client()
    r = c.post("/api/auth/forgot-password", json={"email": "reset@example.test"})
    assert r.status_code == 200
    token = r.json()["devResetLink"].split("token=")[1]
    unknown = c.post("/api/auth/forgot-password", json={"email": "ghost@example.test"}).json()
    assert "devResetLink" not in unknown  # no enumeration
    new_pw = "Brand-New-Pass9"
    assert c.post("/api/auth/reset-password", json={"token": token, "password": new_pw, "confirmPassword": new_pw}).status_code == 200
    assert c.post("/api/auth/reset-password", json={"token": token, "password": new_pw, "confirmPassword": new_pw}).status_code == 400  # single use
    assert s.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "reset@example.test", "password": new_pw}).status_code == 200


def test_change_password(register):
    s = register("chg@example.test")
    assert s.post("/api/auth/change-password", json={"currentPassword": "nope", "newPassword": "Another-Pass-1"}).status_code == 400
    assert s.post("/api/auth/change-password", json={"currentPassword": PASSWORD, "newPassword": "Another-Pass-1"}).status_code == 200


def test_deactivated_user_loses_access_immediately(workspace):
    ws = workspace
    assert ws.viewer.get("/api/cases").status_code == 200
    assert ws.owner.patch(f"/api/users/{ws.viewer.user_id}", json={"isActive": False}).status_code == 200
    assert ws.viewer.get("/api/cases").status_code == 401
