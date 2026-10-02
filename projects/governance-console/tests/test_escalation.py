"""Governance escalation: detect → incident → auto-shutdown → email → investigate → resolve → re-enable."""
import re

import pytest

from conftest import event


@pytest.fixture(autouse=True)
def _no_smtp(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "GOVERNANCE_ALERT_EMAIL", "GOVERNANCE_PUBLIC_URL", "PORTFOLIO_DEMO_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOVERNANCE_ESCALATION_CHECK", "0")


@pytest.fixture()
def sent(monkeypatch):
    """Capture SMTP traffic instead of sending it."""
    box = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): pass
        def login(self, user, pw): box.append(("login", user))
        def send_message(self, msg): box.append(msg)

    import govconsole.notify as n
    monkeypatch.setattr(n.smtplib, "SMTP", FakeSMTP)
    for k, v in {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "alerts@example.com", "SMTP_PASSWORD": "app-pass",
                 "GOVERNANCE_ALERT_EMAIL": "owner@example.com", "GOVERNANCE_PUBLIC_URL": "https://demos.example.com/governance-console"}.items():
        monkeypatch.setenv(k, v)
    return box


def unsafe(**kw):
    return event(workflow="eod-heartbeat", event_type="eod-check", status="needs_human", run_id="run-42",
                 actor="claire.dubois", flags=["unsafe_action", "critical_break"],
                 detail={"action": "eod-check", "business_date": "2026-09-24"}, **kw)


def test_violation_shuts_down_emails_and_resolves(client, store, sent):
    r = client.post("/api/events", json=[unsafe()])
    assert r.status_code == 202 and r.json()["incidents"], r.text
    iid = r.json()["incidents"][0]

    # auto-shutdown: the status endpoint the apps poll now refuses, with the incident in the reason
    st = client.get("/api/workflows/eod-heartbeat/status").json()
    assert st["enabled"] is False and iid in st["reason"] and st["changed_by"] == "governance-console (auto)"

    # one email, with the incident link and the details
    import time
    for _ in range(100):   # delivery runs in a background thread
        if store.notifications(iid) and store.notifications(iid)[0]["status"] != "queued":
            break
        time.sleep(0.05)
    msgs = [m for m in sent if not isinstance(m, tuple)]
    assert len(msgs) == 1
    body = msgs[0].get_body(("plain",)).get_content()
    assert msgs[0]["To"] == "owner@example.com" and "[HIGH]" in msgs[0]["Subject"]
    assert f"https://demos.example.com/governance-console/incidents/{iid}" in body
    assert "unsafe_action" in body and "run-42" in body and "Switched off automatically" in body
    assert store.notifications(iid)[0]["status"] == "sent"

    # repeats don't re-alert
    r2 = client.post("/api/events", json=[unsafe()])
    assert r2.json()["incidents"] == [iid]
    assert store.incident(iid)["occurrences"] == 2 and len(store.notifications(iid)) == 1

    # the link works: the incident page shows evidence, guidance, timeline and ticket payloads
    page = client.get(f"/incidents/{iid}").text
    assert "run-42" in page and "What to do" in page and "Auto-shutdown" in page and "PagerDuty" in page

    # investigate, then resolve with documentation; re-enable and re-confirm the control in the same step
    assert client.post(f"/incidents/{iid}/note", data={"kind": "investigation", "text": "RB-04 edited to add --force"},
                       follow_redirects=False).status_code == 303
    assert client.post(f"/incidents/{iid}/resolve", data={"root_cause": "x", "fix": "", "documentation": "y"}).status_code == 422
    r = client.post(f"/incidents/{iid}/resolve", data={
        "root_cause": "Runbook RB-04 was edited to say 'rerun with --force'", "fix": "Runbook restored; edits need review",
        "documentation": "PR #57; DATA-05 mapping updated", "reenable": "1", "attest": "1"}, follow_redirects=False)
    assert r.status_code == 303
    inc = store.incident(iid)
    assert inc["status"] == "resolved" and "PR #57" in inc["resolution"]
    assert client.get("/api/workflows/eod-heartbeat/status").json()["enabled"] is True
    assert store.latest_attestations()[("eod-heartbeat", "SEC-04")]["verdict"] == "confirmed"
    kinds = [l["kind"] for l in store.incident_log(iid)]
    assert kinds[:3] == ["opened", "shutdown", "notified"] and kinds[-1] == "reenabled" and "investigation" in kinds

    # a new violation after resolution opens a new incident
    assert client.post("/api/events", json=[unsafe()]).json()["incidents"] != [iid]


def test_settings_decide_what_happens(client, store):
    from govconsole import escalation

    # medium issue: email by default, but no shutdown
    r = client.post("/api/events", json=[event(flags=["injection_detected", "escalated"])]).json()
    inc = store.incident(r["incidents"][0])
    assert inc["severity"] == "medium" and not inc["auto_shutdown"]
    assert store.notifications(inc["incident_id"])[0]["status"] == "no-recipients"   # nobody configured, kept in outbox

    # admin turns shutdown off for eod and drops the dq rule
    rules = [k for k in escalation.rules() if k != "data-quality-gate"]
    assert client.post("/settings/escalation/eod-heartbeat", data={"alerts_enabled": "1", "recipients": "a@x.com, b@y.org",
                       "notify_at": "high", "auto_shutdown_at": "never", "rules": rules}, follow_redirects=False).status_code == 303
    assert client.post("/settings/escalation/eod-heartbeat", data={"recipients": "not-an-email"}).status_code == 422
    r = client.post("/api/events", json=[unsafe()]).json()
    inc = store.incident(r["incidents"][0])
    assert not inc["auto_shutdown"] and client.get("/api/workflows/eod-heartbeat/status").json()["enabled"] is True
    assert store.notifications(inc["incident_id"])[0]["recipients"] == "a@x.com, b@y.org"
    assert client.post("/api/events", json=[event(workflow="eod-heartbeat", flags=["dq_gate_failed"])]).json()["incidents"] == []
    assert "a@x.com" in client.get("/settings").text


def test_shadow_ai_is_escalated_by_the_periodic_check(client, store):
    from govconsole import app as appmod, escalation

    client.post("/api/events", json=[event(workflow="notes-bot", event_type="run")])
    out = escalation.check_aggregates(store, appmod.get_catalog(), "http://c")
    assert any(i["rule_id"] == "shadow-ai" and i["workflow"] == "notes-bot" for i in out)
    assert escalation.check_aggregates(store, appmod.get_catalog(), "http://c")[0].get("repeat")


def test_public_demo_masks_recipients_and_locks_settings(client, store, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_ALERT_EMAIL", "ruairi@example.com")
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("GOVERNANCE_ADMIN_TOKEN", "secret")
    r = client.post("/api/events", json=[unsafe()]).json()
    st = client.get("/api/workflows/eod-heartbeat/status").json()
    assert st["enabled"] is False and st["expires_at"]               # demo: the auto switch-off lapses on its own
    assert client.post("/settings/escalation/eod-heartbeat", data={"recipients": "me@evil.com"}).status_code == 403
    out = client.get("/outbox").text
    assert "ruairi@example.com" not in out and "r•••@example.com" in out
    # visitors can work the incident, with their name on it
    iid = r["incidents"][0]
    assert client.post(f"/incidents/{iid}/note", data={"kind": "investigation", "text": "looking"}).status_code == 422
    assert client.post(f"/incidents/{iid}/note", data={"kind": "investigation", "text": "looking", "name": "Vi"},
                       follow_redirects=False).status_code == 303
    assert store.incident_log(iid)[-1]["actor"] == "Vi (demo visitor)"


def test_ticket_payloads():
    from govconsole.notify import ticket_payload

    inc = {"incident_id": "INC-0007", "workflow": "eod-heartbeat", "rule_id": "unsafe-action", "severity": "high",
           "title": "AI proposed an action outside the approved runbook", "control_id": "SEC-04", "summary": "s",
           "auto_shutdown": 1}
    pd = ticket_payload("pagerduty", inc, "EOD heartbeat", "https://c/incidents/INC-0007")
    assert pd["dedup_key"] == "INC-0007" and pd["payload"]["severity"] == "error" and pd["links"][0]["href"].endswith("INC-0007")
    sn = ticket_payload("servicenow", inc, "EOD heartbeat", "https://c/incidents/INC-0007")
    assert sn["correlation_id"] == "INC-0007" and sn["impact"] == "1" and re.search(r"\[INC-0007\]", sn["short_description"])


def test_resent_event_is_not_a_new_violation(client, store):
    e = unsafe()
    first = client.post("/api/events", json=[e]).json()["incidents"]
    assert client.post("/api/events", json=[e]).json()["incidents"] == []
    assert store.incident(first[0])["occurrences"] == 1
