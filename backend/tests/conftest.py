import os
import re
import tempfile
from pathlib import Path

# Configure the app for tests BEFORE it is imported: a separate database, no rate limits, instant processing.
_env = Path(__file__).resolve().parents[1] / ".env"
_test_url = os.getenv("TEST_DATABASE_URL")
if not _test_url and _env.exists():
    m = re.search(r"^TEST_DATABASE_URL=(.+)$", _env.read_text(encoding="utf-8"), re.M)
    _test_url = m.group(1).strip() if m else None
if not _test_url:
    raise RuntimeError("Set TEST_DATABASE_URL (a dedicated, disposable PostgreSQL database) to run the tests.")
os.environ["DATABASE_URL"] = _test_url
os.environ["APP_ENV"] = "development"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["PROCESSING_STEP_DELAY_MS"] = "0"
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789abcdef"
os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret-not-for-production-0123456789"
os.environ["STORAGE_PATH"] = tempfile.mkdtemp(prefix="ht-test-storage-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.database.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Str0ng-Test-Pass1"


@pytest.fixture(scope="session", autouse=True)
def schema():
    assert engine.url.database.endswith("_test"), "Refusing to run tests against a non-test database"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def clean_db(schema):
    with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


class Session:
    """A logged-in API client with its own cookie jar."""

    def __init__(self, client: TestClient, data: dict):
        self.client, self.data = client, data
        self.token = data["accessToken"]
        self.user_id = data["user"]["id"]
        self.email = data["user"]["email"]
        self.role = data["role"]

    @property
    def h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.h, **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self.h, **kw)


@pytest.fixture
def make_client():
    clients = []

    def _make() -> TestClient:
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def register(make_client):
    def _register(email: str, org: str | None = None, name: str = "Test User") -> Session:
        c = make_client()
        r = c.post("/api/auth/register", json={"fullName": name, "email": email, "password": PASSWORD, "confirmPassword": PASSWORD, **({"organizationName": org} if org else {})})
        assert r.status_code == 201, r.text
        return Session(c, r.json())

    return _register


@pytest.fixture
def add_member(register, make_client):
    """Invite + accept through the real API. Returns a Session for the new member."""

    def _add(owner: Session, email: str, role: str, name: str = "Member") -> Session:
        r = owner.post("/api/users/invite", json={"email": email, "role": role})
        assert r.status_code == 201, r.text
        token = r.json()["inviteLink"].rsplit("/", 1)[-1]
        c = make_client()
        a = c.post("/api/auth/accept-invite", json={"token": token, "fullName": name, "password": PASSWORD, "confirmPassword": PASSWORD})
        assert a.status_code == 201, a.text
        return Session(c, a.json())

    return _add


@pytest.fixture
def workspace(register, add_member):
    """One organization with a member of every role, plus a loaded demo case."""
    owner = register("owner@a.test", "Org A", "Olivia Owner")
    # OWNER can invite ADMIN; ADMIN cannot invite ADMIN, so the owner invites everyone.
    admin = add_member(owner, "admin@a.test", "ADMIN", "Adam Admin")
    reviewer = add_member(owner, "reviewer@a.test", "REVIEWER", "Rita Reviewer")
    analyst = add_member(owner, "analyst@a.test", "ANALYST", "Alan Analyst")
    viewer = add_member(owner, "viewer@a.test", "VIEWER", "Vera Viewer")
    case = owner.post("/api/cases/demo")
    assert case.status_code == 201, case.text
    return type("WS", (), dict(owner=owner, admin=admin, reviewer=reviewer, analyst=analyst, viewer=viewer, case=case.json()))
