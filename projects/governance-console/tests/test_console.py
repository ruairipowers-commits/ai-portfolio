"""Governance console: ingest, kill switch, attestations, catalog discovery, metrics, spool, client round-trip."""
import importlib.util
import json
import shutil
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import ROOT, event

PAGES = ["/", "/?days=90", "/?sim=0", "/controls", "/models", "/events", "/events?actor=maya.chen", "/audit",
         "/admin/login", "/workflows/trade-ops-exceptions", "/workflows/research-qa-rag", "/api/health", "/api/summary",
         "/api/events.csv", "/api/workflows"]


def test_pages_render(client):
    for p in PAGES:
        r = client.get(p)
        assert r.status_code == 200, (p, r.text[:300])


def test_seeded_history_is_labelled_and_tells_the_story(client, store):
    assert store.query("select count(*) as n from events where source <> 'simulated'")[0]["n"] == 0
    s = client.get("/api/summary?days=90").json()
    assert s["unregistered"] == ["pm-notes-summarizer"]                       # shadow AI
    assert {"injection_detected", "kill_switch", "escalated"} <= set(s["flags"])
    changes = store.query("select workflow, action from control_changes order by ts")
    assert [c["action"] for c in changes] == ["disable", "enable"]             # research-qa-rag, day -12
    from govconsole import metrics
    assert any(a["workflow"] == "trade-ops-exceptions" for a in metrics.detect_anomalies(store, 60))   # model promotion
    assert max(r["ts"] for r in store.query("select ts from events")) <= datetime.now(timezone.utc).isoformat()


def test_ingest_validates_dedupes_and_requires_token_when_set(client, monkeypatch):
    e = event()
    assert client.post("/api/events", json=[e]).json() == {"accepted": 1, "received": 1}
    assert client.post("/api/events", json=[e]).json()["accepted"] == 0           # idempotent on event_id
    assert client.post("/api/events", json=[{**event(), "cost_usd": -1}]).status_code == 422
    assert client.post("/api/events", json=[{**event(), "workflow": "Bad Name!"}]).status_code == 422
    monkeypatch.setenv("GOVERNANCE_INGEST_TOKEN", "s3cret")
    assert client.post("/api/events", json=[event()]).status_code == 401
    ok = client.post("/api/events", json=[event()], headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202


def test_live_events_drive_the_dashboard(client):
    client.post("/api/events", json=[event(cost_usd=1.25, flags=["injection_detected"]), event(event_type="visit", cost_usd=0),
                                     event(workflow="kyc-bot", cost_usd=2.0)])
    s = client.get("/api/summary?sim=0&days=7").json()
    assert s["kpi"]["cost"] == 3.25 and s["kpi"]["runs"] == 2 and s["kpi"]["visits"] == 1
    assert s["flags"] == {"injection_detected": 1} and s["unregistered"] == ["kyc-bot"]
    assert s["cumulative_cost"][-1] == 3.25
    page = client.get("/?sim=0").text
    assert "kyc-bot" in page and "shadow AI" in page


def test_register_event_records_declared_metadata(client, store):
    meta = {"risk_tier": "high", "models": [{"name": "m"}], "controls": []}
    client.post("/api/events", json=[event(workflow="kyc-bot", event_type="register", detail=meta, cost_usd=0)])
    assert store.workflow_meta()["kyc-bot"]["risk_tier"] == "high"
    rows = {r["slug"]: r for r in client.get("/api/workflows").json()}
    assert rows["kyc-bot"]["risk_tier"] == "high (self-declared)" and not rows["kyc-bot"]["registered"]


def test_kill_switch_admin_change_is_audited(client, store, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_ADMIN_TOKEN", "adm1n")
    assert client.post("/workflows/altdata-triage/toggle", data={"enabled": "0", "reason": "x"}).status_code == 403
    client.post("/admin/login", data={"token": "wrong", "name": "cro"})
    assert client.post("/workflows/altdata-triage/toggle", data={"enabled": "0", "reason": "x"}).status_code == 403
    client.post("/admin/login", data={"token": "adm1n", "name": "cro"})
    r = client.post("/workflows/altdata-triage/toggle", data={"enabled": "0", "reason": "vendor licence review"},
                    follow_redirects=False)
    assert r.status_code == 303
    st = client.get("/api/workflows/altdata-triage/status").json()
    assert st["enabled"] is False and st["changed_by"] == "cro" and st["expires_at"] is None
    assert client.post("/workflows/altdata-triage/toggle", data={"enabled": "1", "reason": ""}).status_code == 422
    log = store.query("select * from control_changes where source = 'live'")
    assert log[0]["action"] == "disable" and log[0]["reason"] == "vendor licence review"


def test_public_demo_switch_off_is_temporary(client, store, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    client.post("/workflows/eod-heartbeat/toggle", data={"enabled": "0", "reason": "trying it", "name": "Ann"})
    st = client.get("/api/workflows/eod-heartbeat/status").json()
    assert st["enabled"] is False and st["changed_by"] == "Ann (demo visitor)" and st["expires_at"]
    store.execute("update workflow_state set expires_at = ? where workflow = 'eod-heartbeat'", ("2000-01-01T00:00:00+00:00",))
    assert client.get("/api/workflows/eod-heartbeat/status").json()["enabled"] is True
    assert client.post("/workflows/pm-notes-summarizer/toggle", data={"enabled": "0", "reason": "x"}).status_code == 404


def test_attestation(client, store, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    assert client.post("/workflows/eod-heartbeat/attest", data={"control_id": "SEC-02", "verdict": "confirmed"}).status_code == 422
    client.post("/workflows/eod-heartbeat/attest", data={"control_id": "SEC-02", "verdict": "confirmed",
                                                         "note": "ran the injected runbook case", "name": "Bo"})
    row = next(r for r in client.get("/api/workflows").json() if r["slug"] == "eod-heartbeat")
    assert row["attested"] == 1
    assert "Bo (demo visitor)" in client.get("/workflows/eod-heartbeat").text
    stale = next(r for r in client.get("/api/workflows").json() if r["slug"] == "trade-ops-exceptions")
    assert stale["attest_stale"] > 0 and stale["attested"] == 0      # seeded review is older than 90 days


def test_new_project_appears_without_console_changes(tmp_path, monkeypatch):
    portfolio = ROOT.parents[1]
    root = tmp_path / "portfolio"
    (root / "governance").mkdir(parents=True)
    shutil.copy(portfolio / "governance" / "controls.md", root / "governance")
    shutil.copytree(portfolio / "specs", root / "specs")
    shutil.copytree(portfolio / "projects" / "altdata-triage" / "docs", root / "projects" / "kyc-review" / "docs")
    (root / "specs" / "kyc-review.yaml").write_text("slug: kyc-review\ntitle: 'KYC review: document checks'\nrisk_tier: high\n")
    (root / "portfolio.yaml").write_text("projects: [altdata-triage, kyc-review, governance-console]\n")
    monkeypatch.setenv("PORTFOLIO_ROOT", str(root))
    from govconsole import catalog
    c = catalog.load()
    slugs = [w["slug"] for w in c["workflows"]]
    assert slugs == ["altdata-triage", "kyc-review"]                     # platform project skipped
    kyc = c["workflows"][1]
    assert kyc["risk_tier"] == "high" and len(kyc["controls"]) == len(c["controls"]) == 30


def test_bundled_catalog_matches_portfolio():
    """catalog/workflows.json is what a published console uses; it must be regenerated when projects change."""
    from govconsole import catalog
    live = catalog.build_from_portfolio(ROOT.parents[1])
    bundled = json.loads(catalog.BUNDLED.read_text())
    assert [w["slug"] for w in bundled["workflows"]] == [w["slug"] for w in live["workflows"]]
    assert {w["slug"]: w["controls"] for w in bundled["workflows"]} == {w["slug"]: w["controls"] for w in live["workflows"]}


def test_metric_definitions(store):
    from govconsole import metrics
    d = date(2026, 9, 30)
    evs = [event(ts=f"{d}T10:00:00+00:00", cost_usd=1.0, latency_ms=1000),
           event(ts=f"{d}T11:00:00+00:00", cost_usd=3.0, status="escalated", latency_ms=3000),
           event(ts=f"{d}T12:00:00+00:00", event_type="approve", cost_usd=0, actor="ann"),
           event(ts=f"{d}T12:30:00+00:00", status="blocked", cost_usd=0, flags=["kill_switch"]),
           event(ts=f"{d}T13:00:00+00:00", event_type="visit", cost_usd=0, actor="visitor-1", actor_type="visitor")]
    for e in evs:
        e["source"] = "live"
    store.insert_events(evs)
    s = metrics.summary(store, {"workflows": [{"slug": "altdata-triage"}]}, days=1, end=d)
    k = s["kpi"]
    assert (k["cost"], k["runs"], k["decisions"], k["blocked"], k["visits"], k["users"]) == (4.0, 2, 1, 1, 1, 3)
    assert k["escalation_rate"] == 0.5 and k["p95_latency_ms"] == 3000


def test_anomaly_detection(store):
    from govconsole import metrics
    end = date(2026, 9, 30)
    evs = [event(ts=f"{end - timedelta(days=i)}T10:00:00+00:00", cost_usd=1.0 if i else 9.0) for i in range(20)]
    store.insert_events(evs)
    a = metrics.detect_anomalies(store, days=5, end=end)
    assert a == [{"workflow": "altdata-triage", "day": str(end), "cost": 9.0, "median": 1.0, "factor": 9.0}]


def test_spool_import_is_incremental(store, tmp_path):
    from govconsole import spool
    p = tmp_path / "events.jsonl"
    p.write_text(json.dumps(event()) + "\n" + json.dumps(event()) + "\n")
    assert spool.import_spool(store, p) == 2
    with p.open("a") as f:
        f.write(json.dumps(event()) + "\n" + '{"partial": ')
    assert spool.import_spool(store, p) == 1 and spool.import_spool(store, p) == 0


def _client_module(project: str):
    spec = importlib.util.spec_from_file_location(f"telemetry_{project}", ROOT / "clients" / "python" / "telemetry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PROJECT = project
    return mod


def test_reference_client_round_trip(store, monkeypatch, tmp_path):
    """The client the workflows ship, against the real console over HTTP: events land, the kill switch bites."""
    import uvicorn

    from govconsole.app import create_app
    for k in ("PORTFOLIO_DEMO", "GOVERNANCE_ADMIN_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOVERNANCE_INGEST_TOKEN", "tok")
    server = uvicorn.Server(uvicorn.Config(create_app(store, seed=False), host="127.0.0.1", port=0, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    monkeypatch.setenv("GOVERNANCE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(tmp_path / "spool.jsonl"))
    try:
        t = _client_module("altdata-triage")
        t.set_actor("maya", "named")
        t.emit("triage", model="mock-local", cost_usd=0.02, records_in=500, records_out=5, flags=["escalated"])
        t.record("feedback", event_type="feedback", status="wrong")
        t.flush()
        rows = store.query("select event_type, actor, cost_usd, flags from events order by ts")
        assert [(r["event_type"], r["actor"]) for r in rows] == [("triage", "maya"), ("feedback", "maya")]
        assert json.loads(rows[1]["flags"]) == ["marked_wrong"]
        assert t.status().enabled
        store.set_enabled("altdata-triage", False, "incident", "cro")
        t._state_cache = (0.0, None)
        enabled, why = t.status()
        assert not enabled and "incident (by cro)" in why
        with pytest.raises(t.WorkflowDisabled):
            t.require_enabled("triage")
        t.flush()
        assert store.query("select status from events where status = 'blocked'")
    finally:
        server.should_exit = True
        th.join(5)
    t.emit("triage")                                                 # console gone → spooled, not lost
    t.flush()
    assert (tmp_path / "spool.jsonl").read_text().count("\n") == 1


def test_no_prompt_text_in_events(store):
    """NFR-5: the ingest schema has no field for free text beyond a bounded detail dict; long detail is truncated."""
    from govconsole.app import Event
    assert set(Event.model_fields) >= {"event_id", "workflow", "cost_usd"} and "prompt" not in Event.model_fields
