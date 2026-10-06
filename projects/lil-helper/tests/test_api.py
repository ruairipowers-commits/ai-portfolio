"""The phone app's API: sign-in, approval rules, hand-offs, feedback, calendar feed (HITL-02, SEC-01, DATA-03)."""
import re

import pytest
from fastapi.testclient import TestClient

from lilhelper import api

WEEK = "2026-10-05"


@pytest.fixture()
def client(workspace):
    return TestClient(api.app)


def _signin(client, workspace, email="dana@example.com"):
    client.post("/api/auth/request", json={"email": email})
    f = sorted((workspace / "output" / "outbox").glob("signin-*.html"))[-1]
    token = re.search(r"token=([^'\"<]+)", f.read_text()).group(1)
    r = client.post("/api/auth/verify", json={"token": token}).json()
    return {"Authorization": f"Bearer {r['session']}"}


def test_signin_flow_and_no_enumeration(client, workspace):
    a = client.post("/api/auth/request", json={"email": "nobody@example.com"}).json()
    b = client.post("/api/auth/request", json={"email": "dana@example.com"}).json()
    assert a == b                                              # same answer either way
    assert len(list((workspace / "output" / "outbox").glob("signin-*.html"))) == 1
    H = _signin(client, workspace)
    assert client.get("/api/household", headers=H).json()["me"] == "dana"


def test_needs_session_and_rejects_tampering(client):
    assert client.get("/api/household").status_code == 401
    tok = api.sign("session", "dana", 60)
    assert client.get("/api/household", headers={"Authorization": f"Bearer {tok[:-2]}xx"}).status_code == 401
    assert client.get("/api/household", headers={"Authorization": f"Bearer {api.sign('link', 'dana', 60)}"}).status_code == 401


def test_a_child_cannot_act(client):
    H = {"Authorization": f"Bearer {api.sign('session', 'leo', 60)}"}
    assert client.get("/api/household", headers=H).status_code == 403


def test_production_requires_a_secret(monkeypatch):
    monkeypatch.setenv("HELPER_ENV", "production")
    monkeypatch.delenv("HELPER_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        api.sign("session", "dana", 60)


def test_week_flow_handoffs_only_after_approval(client, workspace):
    H = _signin(client, workspace)
    w = client.post("/api/week/draft", json={"week": WEEK}, headers=H).json()
    assert w["status"] == "draft" and w["plan"]["entries"]
    assert client.get("/api/week/shopping", params={"week": WEEK}, headers=H).status_code == 409
    a = client.post("/api/week/approve", json={"week": WEEK, "seconds": 90}, headers=H).json()
    assert a["status"] == "approved" and a["approved_by"] == "dana"
    assert a["savings"]["planning_after"] == 1.5                # measured approval time, not a guess
    sh = client.get("/api/week/shopping", params={"week": WEEK}, headers=H).json()
    assert sh["orders"] and all(o["url"] is None for o in sh["orders"])    # no Instacart key: nothing sent
    assert all(o.get("share_text") or o["handoff"] == "instacart" for o in sh["orders"])


def test_swap_and_job_rules(client, workspace):
    H = _signin(client, workspace)
    w = client.post("/api/week/draft", json={"week": WEEK}, headers=H).json()
    before = {(e["day"], e["meal"]): e["recipe"] for e in w["plan"]["entries"]}
    w2 = client.post("/api/week/swap", json={"week": WEEK, "day": "mon", "meal": "dinner"}, headers=H).json()
    after = {(e["day"], e["meal"]): e["recipe"] for e in w2["plan"]["entries"]}
    assert after[("mon", "dinner")] != before[("mon", "dinner")]
    assert {k: v for k, v in after.items() if k != ("mon", "dinner")} == \
        {k: v for k, v in before.items() if k != ("mon", "dinner")}
    bad = client.post("/api/jobs/swap", json={"week": WEEK, "day": "mon", "job": "dishes", "person": "ivy"}, headers=H)
    assert bad.status_code == 422                                # a 4-year-old doesn't do the dishes
    ok = client.post("/api/jobs/swap", json={"week": WEEK, "day": "mon", "job": "set_table", "person": "leo"}, headers=H)
    assert ok.status_code == 200


def test_feedback_and_validation(client, workspace):
    H = _signin(client, workspace)
    w = client.post("/api/week/draft", json={"week": WEEK}, headers=H).json()
    e = w["plan"]["entries"][0]
    r = client.post("/api/feedback", json={"week": WEEK, "day": e["day"], "meal": e["meal"], "eaten": "lots_left",
                                           "rating": 3}, headers=H)
    assert r.status_code == 200 and r.json()["portions_changed"]
    assert client.post("/api/feedback", json={"week": WEEK, "day": e["day"], "meal": e["meal"], "eaten": "lots_left",
                                              "rating": 9}, headers=H).status_code == 422


def test_calendar_feed_is_unguessable(client, workspace):
    H = _signin(client, workspace)
    client.post("/api/week/draft", json={"week": WEEK}, headers=H)
    feed = client.get("/api/household", headers=H).json()["calendar_feed"]
    r = client.get(feed)
    assert r.status_code == 200 and "BEGIN:VCALENDAR" in r.text
    assert client.get("/api/calendar/guess.ics").status_code == 404
