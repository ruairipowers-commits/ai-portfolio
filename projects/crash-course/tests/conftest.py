import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("COURSE_SECRET", "test-secret-not-for-production")


@pytest.fixture(autouse=True)
def governance_spool(tmp_path, monkeypatch):
    """Telemetry goes to a per-test spool file, never to ~/.ai-portfolio or a real console."""
    spool = tmp_path / "governance-events.jsonl"
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(spool))
    monkeypatch.delenv("GOVERNANCE_URL", raising=False)
    monkeypatch.delenv("GOVERNANCE_TELEMETRY", raising=False)
    from crash_course import telemetry
    telemetry._state_cache = (0.0, None)
    return spool


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    """Every test gets its own data folder: learners database, drafts, published versions and the email outbox."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("COURSE_DATA", str(d))
    monkeypatch.setenv("COURSE_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("COURSE_SHOW_LINKS", "1")
    for k in ("RESEND_API_KEY", "COURSE_PUBLIC_URL", "ROOT_PATH", "COURSE_MODERATOR_MODEL", "COURSE_WRITER_MODEL",
              "COURSE_REVISER_MODEL", "PORTFOLIO_DEMO"):
        monkeypatch.delenv(k, raising=False)
    return d


@pytest.fixture()
def s():
    from crash_course.config import Settings
    return Settings.load()


@pytest.fixture()
def conn():
    from crash_course.store import connect
    with connect() as c:
        yield c


@pytest.fixture()
def published(s):
    """The owner has published the Streamlit and dbt Familiar levels (in this test's data folder)."""
    from crash_course import builder
    from crash_course.store import connect
    with connect() as c:
        for slug in ("streamlit", "dbt"):
            ok, problems = builder.publish(c, s, slug, "familiar", "Test Owner")
            assert ok, problems
    return ["streamlit", "dbt"]


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from crash_course.web import create_app
    return TestClient(create_app(start_worker=False))


def sign_in(client, email: str, name: str = "Test Learner"):
    r = client.post("/signin", data={"email": email, "name": name, "next": "/tracker"})
    link = re.search(r'href="[^"]*?(/auth\?t=[^"]+)"', r.text).group(1).replace("&amp;", "&")
    client.get(link, follow_redirects=False)
    return client


@pytest.fixture()
def learner(client, published):
    return sign_in(client, "ada@example.com", "Ada")


@pytest.fixture()
def owner(published):
    from fastapi.testclient import TestClient
    from crash_course.web import create_app
    return sign_in(TestClient(create_app()), "owner@example.com", "Owner")
