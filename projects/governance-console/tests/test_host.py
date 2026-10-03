"""Host tab: ingest from hostmon.sh, summary, alerts (open once, resolve), stale checker, weekly report, visibility."""
from datetime import datetime, timedelta, timezone

import pytest

from govconsole import host
from govconsole.app import SETTINGS

T0 = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
URL = "https://console.example"

PENTEST = {"ts": "2026-10-03T02:00:00Z",
           "findings": [{"severity": "high", "title": "Admin port reachable from the tunnel", "target": "caddy",
                         "fix": "Bind the admin listener to 127.0.0.1"},
                        {"severity": "medium", "title": "Missing HSTS header", "fix": "Add Strict-Transport-Security"},
                        {"severity": "low", "title": "Server banner", "fix": "header -Server"}],
           "report_md": "# Weekly scan\n\nSECRET-DETAIL in **/etc/caddy**\n\n<script>alert(1)</script>\n\n- one\n- two\n\n"
                        "| a | b |\n|---|---|\n| 1 | 2 |\n\n```\nnmap -sV 127.0.0.1\n```"}
MAINT = {"ts": "2026-10-03T03:00:00Z", "actions": [{"what": "12 package updates pending", "command": "sudo apt-get upgrade -y"},
                                                    "Reboot required after kernel update"]}


def sample(cpu=20.0, mem=40.0, disk=50.0, temp=55.0, containers=None, **extra) -> dict:
    s = {"v": 1, "ts": "2026-10-03T12:00:00Z",
         "host": {"hostname": "evo-x1", "cpu_pct": cpu, "load1": 1.5, "load5": 1.2, "load15": 1.0, "cpu_count": 32,
                  "mem_total_gb": 123.4, "mem_used_pct": mem, "swap_used_pct": 0, "uptime_s": 90061, "temp_c": temp,
                  "disks": [{"mount": "/", "used_pct": disk, "free_gb": 800.0},
                            {"mount": "/var/lib/docker", "used_pct": 30.0, "free_gb": 1200.0}]},
         "containers": containers if containers is not None else [
             {"name": "ai-portfolio-demos-web-1", "service": "web", "state": "running", "health": "healthy", "restarts": 0,
              "cpu_pct": 3.5, "mem_mb": 300, "mem_limit_mb": 2048},
             {"name": "ai-portfolio-demos-caddy-1", "service": "caddy", "state": "running", "health": "none", "restarts": 0,
              "cpu_pct": 0.2, "mem_mb": 20, "mem_limit_mb": None}],
         "deploy": {"deployed": "abc123def4567890", "failed": ""}}
    return {**s, **extra}


def put(store, s: dict, at: datetime) -> dict:
    """Ingest a sample as if received at `at` (the API path uses the server clock; same code)."""
    return host.ingest(store, host.Sample(**s).model_dump(), SETTINGS, URL, now=at)


def open_kinds(store):
    return sorted(a["kind"] for a in store.host_alerts(open_only=True))


@pytest.fixture()
def mail(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOVERNANCE_ALERT_EMAIL", "owner@example.com")


def host_mails(store, kind="host:alert"):
    return [m for m in store.notifications(limit=500) if m["incident_id"] == kind]


# ---------------------------------------------------------------- ingest API
def test_ingest_requires_token_validates_and_limits_size(client, monkeypatch):
    assert client.post("/api/host", json=sample()).status_code == 202          # local: no token configured
    monkeypatch.setenv("GOVERNANCE_INGEST_TOKEN", "s3cret")
    assert client.post("/api/host", json=sample()).status_code == 401
    assert client.post("/api/host", json=sample(), headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.post("/api/host", json=sample(), headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202 and ok.json()["stored"] is True
    auth = {"Authorization": "Bearer s3cret"}
    assert client.post("/api/host", json=sample(cpu=150), headers=auth).status_code == 422
    assert client.post("/api/host", json=[sample()], headers=auth).status_code == 422
    assert client.post("/api/host", json={"host": "x"}, headers=auth).status_code == 422
    big = sample(pentest={"ts": "x", "report_md": "a" * 410_000})
    assert client.post("/api/host", json=big, headers=auth).status_code == 413


def test_storing_and_public_summary(client, store):
    r = client.post("/api/host", json=sample(backup={"ts": datetime.now(timezone.utc).isoformat(), "ok": True,
                                                     "path": "/srv/backups/x.tar"},
                                             maintenance=MAINT, pentest=PENTEST))
    assert r.status_code == 202 and r.json()["report_sent"] is True          # a new scan sends the report at once
    s = client.get("/api/host/summary").json()
    assert s["reporting"] and s["host"] == "EVO-X1" and s["now"]["cpu_pct"] == 20.0 and s["now"]["disk_used_pct"] == 50.0
    assert s["containers"] == {"up": 2, "total": 2, "unhealthy": 0, "down": []}
    assert s["backup"]["ok"] is True and s["backup"]["stale"] is False and s["backup"]["age_h"] < 1
    assert s["pentest"]["counts"] == {"critical": 0, "high": 1, "medium": 1, "low": 1, "info": 0}
    assert s["maintenance"]["actions"] == 2 and s["deploy"]["deployed"] == "abc123d"
    assert s["last_24h"]["cpu_peak"] == 20.0 and s["last_24h"]["samples"] == 1
    assert [a["kind"] for a in s["alerts_open"]] == ["pentest"]
    blob = r.text + client.get("/api/host/summary").text
    for secret in ("SECRET-DETAIL", "apt-get", "/srv/backups", "Admin port reachable"):
        assert secret not in blob                                              # counts only, never details
    assert store.latest_host_sample()["doc"].get("pentest") is None           # report text kept out of per-minute rows
    h = client.get("/api/host/history?range=1h").json()
    assert h["range"] == "1h" and h["cpu"] == [20.0] and len(h["labels"]) == 1
    assert client.get("/api/host/history?range=30d").json()["cpu"] == [20.0]  # hourly rollup


def test_summary_and_page_with_no_data(client):
    s = client.get("/api/host/summary").json()
    assert s["reporting"] is False and s["last_seen"] is None and s["containers"]["total"] == 0
    page = client.get("/host")
    assert page.status_code == 200 and "No host data yet" in page.text and "hostmon.sh" in page.text


# ---------------------------------------------------------------- alerts
def test_threshold_alerts_open_once_email_and_resolve(store, mail):
    put(store, sample(), T0)
    assert open_kinds(store) == []
    for i in range(3):                                   # three hot minutes: one alert each, one email each
        put(store, sample(cpu=97, mem=95, disk=88, temp=93), T0 + timedelta(minutes=11 + i))
    assert open_kinds(store) == ["cpu", "disk", "memory", "temperature"]
    assert len(host_mails(store)) == 4 and all(m["status"] == "outbox-only" for m in host_mails(store))
    assert store.open_host_alert("memory")["occurrences"] == 3
    put(store, sample(cpu=5), T0 + timedelta(minutes=14))  # 10-min CPU average (97*3+5)/4 = 74
    assert open_kinds(store) == []
    mails = host_mails(store)
    assert len(mails) == 8 and sum(m["subject"].startswith("[RESOLVED]") for m in mails) == 4
    assert any("CPU averaged" in m["subject"] for m in mails)


def test_cpu_alert_uses_the_ten_minute_average(store, mail):
    put(store, sample(cpu=10), T0)
    put(store, sample(cpu=100), T0 + timedelta(minutes=1))       # one spike: average 55 → no alert
    assert "cpu" not in open_kinds(store)
    for i in range(2, 12):
        put(store, sample(cpu=95), T0 + timedelta(minutes=i))
    assert "cpu" in open_kinds(store)


def test_container_down_unhealthy_and_restart_detection(store, mail):
    web = {"name": "web-1", "service": "web", "state": "running", "health": "healthy", "restarts": 3}
    put(store, sample(containers=[web]), T0)
    assert open_kinds(store) == []                       # a restart count seen first is not a restart
    put(store, sample(containers=[{**web, "restarts": 5}]), T0 + timedelta(minutes=1))
    assert open_kinds(store) == ["restart:web-1"]
    put(store, sample(containers=[{**web, "restarts": 6}]), T0 + timedelta(minutes=2))   # same alert, counted
    assert store.open_host_alert("restart:web-1")["occurrences"] == 2 and len(host_mails(store)) == 1
    put(store, sample(containers=[{**web, "restarts": 6, "health": "unhealthy"}]), T0 + timedelta(minutes=3))
    assert open_kinds(store) == ["container:web-1", "restart:web-1"]
    put(store, sample(containers=[{**web, "restarts": 6, "state": "exited"}]), T0 + timedelta(minutes=4))
    assert open_kinds(store) == ["container:web-1", "restart:web-1"]
    assert "unhealthy" in store.open_host_alert("container:web-1")["message"]
    put(store, sample(containers=[{**web, "restarts": 6}]), T0 + timedelta(minutes=5))
    assert open_kinds(store) == ["restart:web-1"]       # running again; restart alert waits for a quiet period
    put(store, sample(containers=[{**web, "restarts": 0}]), T0 + timedelta(minutes=40))   # recreated by a deploy
    assert open_kinds(store) == []
    put(store, sample(containers=[]), T0 + timedelta(minutes=41))
    assert open_kinds(store) == []


def test_removed_container_alert_resolves(store, mail):
    put(store, sample(containers=[{"name": "old-1", "state": "exited", "restarts": 0}]), T0)
    assert open_kinds(store) == ["container:old-1"]
    put(store, sample(containers=[]), T0 + timedelta(minutes=1))
    assert open_kinds(store) == []
    assert "no longer part of the stack" in store.host_alerts()[0]["resolution"]


def test_stale_report_alert_from_the_background_check(store, mail):
    put(store, sample(), T0)
    assert host.check(store, SETTINGS, URL, now=T0 + timedelta(minutes=5))["opened"] == []
    out = host.check(store, SETTINGS, URL, now=T0 + timedelta(minutes=12))
    assert [a["kind"] for a in out["opened"]] == ["stale"] and "EVO-X1 stopped reporting" in out["opened"][0]["message"]
    assert host.check(store, SETTINGS, URL, now=T0 + timedelta(minutes=13))["opened"] == []   # deduplicated
    assert host_mails(store)[0]["subject"].startswith("[CRITICAL] EVO-X1 stopped reporting")
    assert "may never leave" in host_mails(store)[0]["body_text"]
    put(store, sample(), T0 + timedelta(minutes=14))
    assert open_kinds(store) == [] and [m["subject"][:10] for m in host_mails(store)].count("[RESOLVED]") == 1


def test_backup_and_pentest_alerts(store, mail):
    old = (T0 - timedelta(hours=40)).isoformat()
    put(store, sample(backup={"ts": old, "ok": True}), T0)
    assert open_kinds(store) == ["backup"] and "40 h old" in store.open_host_alert("backup")["message"]
    put(store, sample(backup={"ts": T0.isoformat(), "ok": False}), T0 + timedelta(minutes=1))
    assert store.open_host_alert("backup") and len(host_mails(store)) == 1
    put(store, sample(backup={"ts": T0.isoformat(), "ok": True}), T0 + timedelta(minutes=2))
    assert open_kinds(store) == []

    r = put(store, sample(pentest=PENTEST), T0 + timedelta(minutes=3))
    assert r["alerts_opened"] == ["pentest"] and r["report_sent"]
    r = put(store, sample(pentest=PENTEST), T0 + timedelta(minutes=4))       # same scan again: nothing new
    assert r["alerts_opened"] == [] and not r["report_sent"]
    assert len(host_mails(store, "host:report")) == 1
    clean = {"ts": "2026-10-10T02:00:00Z", "counts": {"critical": 0, "high": 0, "medium": 1}}
    r = put(store, sample(pentest=clean), T0 + timedelta(days=7))
    assert r["alerts_resolved"] == ["pentest"] and r["report_sent"] and open_kinds(store) == []
    worse = {**PENTEST, "ts": "2026-10-17T02:00:00Z", "findings": [{"severity": "critical", "title": "x"}]}
    put(store, sample(pentest=worse), T0 + timedelta(days=14))
    assert store.open_host_alert("pentest")["severity"] == "critical"


def test_maintenance_actions_do_not_alert(store, mail):
    put(store, sample(maintenance=MAINT), T0)
    assert open_kinds(store) == [] and host_mails(store) == []


# ---------------------------------------------------------------- weekly report
def test_weekly_report_contents_and_schedule(store, mail):
    web = {"name": "web-1", "service": "web", "state": "running", "health": "healthy", "restarts": 1}
    put(store, sample(containers=[web], maintenance=MAINT, backup={"ts": T0.isoformat(), "ok": True}), T0)
    assert not host.report_due(store, SETTINGS, T0 + timedelta(days=6))      # clock started at the first sample
    put(store, sample(cpu=97, temp=91, containers=[{**web, "restarts": 4}]), T0 + timedelta(hours=2))
    put(store, sample(cpu=40, containers=[{**web, "restarts": 4}]), T0 + timedelta(hours=3))
    store.set_host_status("pentest", PENTEST)
    rep = host.build_report(store, SETTINGS, URL, "weekly", T0 + timedelta(days=1))
    t, h = rep["text"], rep["html"]
    assert rep["subject"].startswith("EVO-X1 health & security report") and "1 high" in rep["subject"]
    assert "peak 97%" in t and "web-1: running / healthy, restarts this week 3 (total 4)" in t
    assert "BACKUP: OK" in t and "$ sudo apt-get upgrade -y" in t and "Reboot required" in t
    assert "[HIGH] Admin port reachable from the tunnel (caddy)" in t and "fix: Bind the admin listener" in t
    assert f"{URL}/host" in t and f"{URL}/host/security" in t
    assert "<code" in h and "apt-get upgrade" in h and "Missing HSTS header" in h and "temperature" in t.lower()
    assert "opened" in t and "Temperature 91" in t
    # due after 7 days: the background check sends it and records it
    assert host.report_due(store, SETTINGS, T0 + timedelta(days=7, minutes=1))
    host.check(store, SETTINGS, URL, now=T0 + timedelta(days=7, minutes=1))
    assert len(host_mails(store, "host:report")) == 1
    assert not host.report_due(store, SETTINGS, T0 + timedelta(days=8))


def test_report_on_demand_is_admin_only(client, store, monkeypatch, mail):
    client.post("/api/host", json=sample())
    r = client.post("/host/report/send", follow_redirects=False)              # local: admin
    assert r.status_code == 303 and len(host_mails(store, "host:report")) == 1
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("GOVERNANCE_ADMIN_TOKEN", "adm1n")
    assert client.post("/host/report/send").status_code == 403


def test_retention_rollup_and_prune(store):
    put(store, sample(cpu=10), T0 - timedelta(days=40))
    put(store, sample(cpu=30), T0 - timedelta(days=40) + timedelta(minutes=1))
    assert store.host_hourly("2000")[0]["cpu_avg"] == 20.0
    put(store, sample(cpu=50), T0)                         # new hour: prune minute rows older than 30 days
    assert [r["cpu_pct"] for r in store.host_samples("2000")] == [50.0]
    assert len(store.host_hourly("2000")) == 2             # the old hour lives on in the rollup


# ---------------------------------------------------------------- who sees what
def test_public_sees_load_and_counts_admin_sees_findings_and_commands(client, store, monkeypatch, mail):
    client.post("/api/host", json=sample(maintenance=MAINT, pentest=PENTEST, backup={"ts": "2026-10-03T01:00:00Z", "ok": True}))
    admin_page = client.get("/host").text                  # local mode = admin
    assert "sudo apt-get upgrade -y" in admin_page and "Admin port reachable" in admin_page
    sec = client.get("/host/security").text
    assert "SECRET-DETAIL" in sec and "<b>/etc/caddy</b>" in sec and "<table>" in sec
    assert "<script>alert(1)</script>" not in sec and "&lt;script&gt;" in sec    # report Markdown is escaped
    report_id = host_mails(store, "host:report")[0]["notification_id"]

    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("GOVERNANCE_ADMIN_TOKEN", "adm1n")
    page = client.get("/host").text
    assert "web" in page and "running" in page and "1 high" in page and "Host · EVO-X1" in page
    for secret in ("apt-get", "Admin port reachable", "SECRET-DETAIL", "hostmon.sh", "/etc/caddy"):
        assert secret not in page, secret
    assert "sign in" in page
    sec = client.get("/host/security")
    assert sec.status_code == 200 and "1 high" in sec.text and "SECRET-DETAIL" not in sec.text and "Admin port" not in sec.text
    assert client.get(f"/outbox/{report_id}").status_code == 403              # the email carries findings too
    client.post("/admin/login", data={"token": "adm1n", "name": "owner"})
    assert "SECRET-DETAIL" in client.get("/host/security").text
    assert client.get(f"/outbox/{report_id}").status_code == 200


def test_host_tab_in_nav_and_outbox_links(client, store, mail):
    page = client.get("/").text
    assert page.index(">Content<") < page.index(">Host<") < page.index(">Settings<")
    client.post("/api/host", json=sample(mem=99))
    assert "Host alert" in client.get("/outbox").text


def test_markdown_renderer_is_safe():
    html = host.md_to_html('## T\n[x](javascript:alert(1)) [ok](https://e.com) `a<b>`\n\n1. one\n2. two\n\n> quote')
    assert "<h3>T</h3>" in html and 'href="https://e.com"' in html and 'href="javascript' not in html
    assert "<code>a&lt;b&gt;</code>" in html and "<ol><li>one</li><li>two</li></ol>" in html and "<blockquote>" in html
