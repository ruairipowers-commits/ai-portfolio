"""Host monitoring: the self-host box's load, containers, backups, maintenance and security scans.

    deploy/selfhost/hostmon.sh (on the host, every minute) ── POST /api/host ──▶ ingest()
        ├─ host_metrics      one row per minute (30 days), rolled up into host_hourly (1 year)
        ├─ host_status       latest backup · maintenance · pentest · containers · deploy document
        ├─ evaluate()        alerts: CPU (10-min average), memory, disk, temperature, containers down / unhealthy /
        │                    restarted, backup stale or failed, new scan with critical / high findings
        └─ report due?       weekly health & security email, or at once when a new pentest result arrives
    background thread (every minute) ── check() ── no sample for `stale_minutes` → "EVO-X1 stopped reporting"

One open alert per kind (`cpu`, `memory`, `container:<name>` …) is the throttle: an alert emails when it opens and
when it resolves, never while it stays open. Every email goes to the outbox first (Settings → Outbox), so with no
SMTP configured everything still works, just without leaving the machine. Thresholds: config/settings.yaml `host:`.

Retention (documented in the README): per-minute samples are deleted after `minute_retention_days` (30); the hourly
rollup (avg and peak per hour) is kept `hourly_retention_days` (365). The 1 h and 24 h charts read minutes; 7 d and
30 d read the rollup.

What the public sees: load, history, container states and counts. Not findings, commands, file paths or the
report text — those are for an admin (the page and /api/host/summary only ever expose counts).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from html import escape

from pydantic import BaseModel, ConfigDict, Field

from . import notify
from .store import now_iso

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEVERITIES = list(SEV_RANK)


# ---------------------------------------------------------------- the sample hostmon.sh sends
class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Disk(_M):
    mount: str = Field(max_length=200)
    used_pct: float | None = Field(None, ge=0, le=100)
    free_gb: float | None = Field(None, ge=0, le=1_000_000)


class HostInfo(_M):
    hostname: str = Field("", max_length=100)
    cpu_pct: float | None = Field(None, ge=0, le=100)
    load1: float | None = Field(None, ge=0, le=10_000)
    load5: float | None = Field(None, ge=0, le=10_000)
    load15: float | None = Field(None, ge=0, le=10_000)
    cpu_count: int | None = Field(None, ge=1, le=4096)
    mem_total_gb: float | None = Field(None, ge=0, le=100_000)
    mem_used_pct: float | None = Field(None, ge=0, le=100)
    swap_used_pct: float | None = Field(None, ge=0, le=100)
    uptime_s: float | None = Field(None, ge=0)
    temp_c: float | None = Field(None, ge=-50, le=200)
    disks: list[Disk] = Field(default_factory=list, max_length=10)


class Container(_M):
    name: str = Field(max_length=200)
    service: str = Field("", max_length=200)
    state: str = Field("", max_length=40)
    health: str = Field("", max_length=40)
    restarts: int | None = Field(None, ge=0, le=10_000_000)
    cpu_pct: float | None = Field(None, ge=0, le=100_000)
    mem_mb: float | None = Field(None, ge=0, le=10_000_000)
    mem_limit_mb: float | None = Field(None, ge=0, le=10_000_000)


class Deploy(_M):
    deployed: str = Field("", max_length=80)
    failed: str = Field("", max_length=80)


class Sample(_M):
    v: int = 1
    ts: str = Field("", max_length=40)              # the host's clock; the console stores its own receive time
    host: HostInfo
    containers: list[Container] = Field(default_factory=list, max_length=200)
    deploy: Deploy | None = None
    backup: dict | None = None
    maintenance: dict | None = None
    pentest: dict | None = None


# ---------------------------------------------------------------- settings + small helpers
def cfg(settings: dict) -> dict:
    return {"name": "EVO-X1", "max_body_bytes": 400_000, "stale_minutes": 10, "cpu_pct": 90, "cpu_window_minutes": 10,
            "mem_used_pct": 90, "disk_used_pct": 85, "temp_c": 90, "restart_quiet_minutes": 30,
            "backup_max_age_hours": 36, "report_every_days": 7, "minute_retention_days": 30,
            "hourly_retention_days": 365, **(settings.get("host") or {})}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(ts) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _age_h(ts, now: datetime) -> float | None:
    d = _parse(ts)
    return round((now - d).total_seconds() / 3600, 1) if d else None


def _r(v, dp=1):
    return None if v is None else round(float(v), dp)


# ---------------------------------------------------------------- reading the status documents
def pentest_ts(p: dict | None) -> str:
    p = p or {}
    return str(p.get("ts") or p.get("finished") or p.get("finished_at") or p.get("started") or "")


def pentest_findings(p: dict | None) -> list[dict]:
    out = []
    for f in (p or {}).get("findings") or []:
        if isinstance(f, dict):
            sev = str(f.get("severity") or "info").lower()
            out.append({"severity": sev if sev in SEV_RANK else "info",
                        "title": str(f.get("title") or f.get("name") or f.get("id") or "finding"),
                        "where": str(f.get("target") or f.get("where") or f.get("location") or ""),
                        "fix": str(f.get("fix") or f.get("remediation") or f.get("recommendation") or "")})
    return sorted(out, key=lambda f: SEV_RANK[f["severity"]])


def pentest_counts(p: dict | None) -> dict:
    p = p or {}
    src = p.get("counts") or p.get("summary")
    counts = {s: 0 for s in SEVERITIES}
    if isinstance(src, dict):
        for k, v in src.items():
            if str(k).lower() in counts and isinstance(v, (int, float)):
                counts[str(k).lower()] = int(v)
    else:
        for f in pentest_findings(p):
            counts[f["severity"]] += 1
    return counts


def backup_view(b: dict | None, now: datetime) -> dict:
    if not b:
        return {"reported": False, "ok": None, "ts": None, "age_h": None}
    ts = b.get("ts") or b.get("finished") or b.get("finished_at") or b.get("last_success")
    ok = b.get("ok")
    if not isinstance(ok, bool):
        ok = str(b.get("status", "")).lower() in ("ok", "success", "succeeded")
    return {"reported": True, "ok": ok, "ts": ts, "age_h": _age_h(ts, now)}


def maintenance_actions(m: dict | None) -> list[dict]:
    out = []
    for a in (m or {}).get("actions") or []:
        if isinstance(a, str):
            out.append({"what": a, "command": ""})
        elif isinstance(a, dict):
            out.append({"what": str(a.get("what") or a.get("title") or a.get("description") or a.get("action") or ""),
                        "command": str(a.get("command") or a.get("cmd") or "")})
    return out


def _disk_used(host: dict) -> float | None:
    vals = [d["used_pct"] for d in host.get("disks") or [] if d.get("used_pct") is not None]
    return max(vals) if vals else None


# ---------------------------------------------------------------- ingest
def ingest(store, sample: dict, settings: dict, console_url: str, now: datetime | None = None) -> dict:
    """Store one validated sample (Sample.model_dump()), evaluate alerts, send the report if it's due."""
    c, now = cfg(settings), _now(now)
    ts = _iso(now)
    prev = store.latest_host_sample()
    host = sample["host"]
    row = {"hostname": host.get("hostname"), "cpu_pct": host.get("cpu_pct"), "load1": host.get("load1"),
           "mem_used_pct": host.get("mem_used_pct"), "disk_used_pct": _disk_used(host), "temp_c": host.get("temp_c")}
    store.add_host_sample(ts, row, {"v": sample.get("v", 1), "host_ts": sample.get("ts"), "host": host,
                                    "containers": sample.get("containers") or []})

    status = store.host_status()
    old_pentest = (status.get("pentest") or {}).get("doc")
    new_pentest = bool(sample.get("pentest")) and pentest_ts(sample["pentest"]) != pentest_ts(old_pentest)
    for key in ("backup", "maintenance", "pentest", "deploy"):
        doc = sample.get(key)
        if doc and json.dumps(doc, sort_keys=True) != json.dumps((status.get(key) or {}).get("doc"), sort_keys=True):
            store.set_host_status(key, doc, ts)
    store.set_host_status("containers", sample.get("containers") or [], ts)

    hour = ts[:13]
    store.rollup_host_hour(hour)
    if prev and prev["ts"][:13] != hour:            # first sample of a new hour: finish the last one, prune
        store.rollup_host_hour(prev["ts"][:13])
        store.prune_host(_iso(now - timedelta(days=c["minute_retention_days"])),
                         _iso(now - timedelta(days=c["hourly_retention_days"]))[:13])

    out = evaluate(store, sample, prev, settings, console_url, now, new_pentest)
    report = None
    if new_pentest:
        report = send_report(store, settings, console_url, "a new security scan arrived", now)
    elif report_due(store, settings, now):
        report = send_report(store, settings, console_url, "weekly", now)
    return {"stored": True, "received_at": ts, "alerts_opened": [a["kind"] for a in out["opened"]],
            "alerts_resolved": [a["kind"] for a in out["resolved"]], "report_sent": bool(report)}


# ---------------------------------------------------------------- alerts
def _set(store, settings, console_url, out, kind, active, severity, message, ts, resolution="back to normal",
         notify_open=True, notify_resolve=True):
    a = store.open_host_alert(kind)
    if active and a:
        store.touch_host_alert(a["alert_id"], ts)
    elif active:
        a = store.create_host_alert(kind, severity, message, ts)
        out["opened"].append(a)
        if notify_open:
            alert_email(store, settings, console_url, a, "opened")
    elif a:
        store.resolve_host_alert(a["alert_id"], ts, resolution)
        a = {**a, "resolved_ts": ts, "resolution": resolution}
        out["resolved"].append(a)
        if notify_resolve:
            alert_email(store, settings, console_url, a, "resolved")


def evaluate(store, sample: dict, prev: dict | None, settings: dict, console_url: str,
             now: datetime | None = None, new_pentest: bool = False) -> dict:
    c, now = cfg(settings), _now(now)
    ts, name = _iso(now), c["name"]
    out = {"opened": [], "resolved": []}
    s = lambda *a, **k: _set(store, settings, console_url, out, *a, **k)  # noqa: E731
    host = sample["host"]

    s("stale", False, "critical", "", ts, resolution=f"{name} is reporting again")

    win = store.host_samples(_iso(now - timedelta(minutes=c["cpu_window_minutes"])))
    cpus = [r["cpu_pct"] for r in win if r["cpu_pct"] is not None]
    avg = sum(cpus) / len(cpus) if cpus else None
    s("cpu", avg is not None and avg >= c["cpu_pct"], "medium",
      f"CPU averaged {avg or 0:.0f}% over the last {c['cpu_window_minutes']} minutes (threshold {c['cpu_pct']}%)", ts)
    mem = host.get("mem_used_pct")
    s("memory", mem is not None and mem >= c["mem_used_pct"], "high",
      f"Memory {mem or 0:.0f}% used (threshold {c['mem_used_pct']}%)", ts)
    worst = max((d for d in host.get("disks") or [] if d.get("used_pct") is not None),
                key=lambda d: d["used_pct"], default=None)
    s("disk", worst is not None and worst["used_pct"] >= c["disk_used_pct"], "high",
      f"Disk {worst['used_pct'] if worst else 0:.0f}% full (threshold {c['disk_used_pct']}%)", ts)
    t = host.get("temp_c")
    s("temperature", t is not None and t >= c["temp_c"], "high", f"Temperature {t or 0:.0f} °C (threshold {c['temp_c']} °C)", ts)

    # containers: down or unhealthy; restarted since the previous sample
    seen = set()
    before = {x["name"]: x for x in ((prev or {}).get("doc") or {}).get("containers") or []}
    for ct in sample.get("containers") or []:
        n = ct["name"]
        seen.add(n)
        bad = ct.get("state") != "running" or ct.get("health") == "unhealthy"
        what = "unhealthy" if ct.get("state") == "running" else (ct.get("state") or "not running")
        s(f"container:{n}", bad, "high", f"Container {n} is {what}", ts, resolution=f"{n} is running again")
        was = (before.get(n) or {}).get("restarts")
        grew = was is not None and ct.get("restarts") is not None and ct["restarts"] > was
        kind = f"restart:{n}"
        a = store.open_host_alert(kind)
        if grew and a:
            store.touch_host_alert(a["alert_id"], ts, f"Container {n} restarted (restart count {ct['restarts']})")
        elif grew:
            s(kind, True, "medium", f"Container {n} restarted (restart count {was} → {ct['restarts']})", ts)
        elif a and _parse(a["last_seen"]) <= now - timedelta(minutes=c["restart_quiet_minutes"]):
            s(kind, False, "medium", "", ts, resolution=f"no further restarts for {c['restart_quiet_minutes']} minutes")
    for a in store.host_alerts(open_only=True):    # a service removed from the stack is no longer an alert
        n = a["kind"].split(":", 1)[-1]
        if a["kind"].startswith(("container:", "restart:")) and n not in seen:
            s(a["kind"], False, "", "", ts, resolution=f"{n} is no longer part of the stack")

    if sample.get("backup"):
        b = backup_view(sample["backup"], now)
        stale = b["age_h"] is None or b["age_h"] > c["backup_max_age_hours"]
        msg = ("Last backup failed" if not b["ok"] else
               f"Last backup is {b['age_h']:.0f} h old (limit {c['backup_max_age_hours']} h)" if b["age_h"] is not None
               else "Backup status has no timestamp")
        s("backup", (not b["ok"]) or stale, "high", msg, ts, resolution="backup OK")

    if new_pentest:
        counts = pentest_counts(sample["pentest"])
        serious = counts["critical"] + counts["high"]
        s("pentest", False, "", "", ts, resolution=f"superseded by the scan of {pentest_ts(sample['pentest'])[:16]}",
          notify_resolve=not serious)
        if serious:
            s("pentest", True, "critical" if counts["critical"] else "high",
              f"Security scan found {counts['critical']} critical and {counts['high']} high findings", ts)
    return out


def check(store, settings: dict, console_url: str, now: datetime | None = None) -> dict:
    """Background: no sample for `stale_minutes` → alert; the weekly report if it's due (even with nothing new)."""
    c, now = cfg(settings), _now(now)
    out = {"opened": [], "resolved": []}
    last = store.latest_host_sample()
    if not last:
        return out
    age = (now - _parse(last["ts"])).total_seconds() / 60
    if age >= c["stale_minutes"]:
        _set(store, settings, console_url, out, "stale", True, "critical",
             f"{c['name']} stopped reporting: no sample for {age:.0f} minutes (last at {last['ts'][:16].replace('T', ' ')} UTC)",
             _iso(now))
    if report_due(store, settings, now):
        send_report(store, settings, console_url, "weekly", now)
    return out


def start_checker(get_store, get_settings, console_url_fn) -> threading.Thread:
    global _checker
    if _checker is not None:
        return _checker

    def loop():
        while True:
            time.sleep(60)
            try:
                check(get_store(), get_settings(), console_url_fn())
            except Exception as e:  # noqa: BLE001 — the checker must never take the console down
                print(f"host check failed: {type(e).__name__}: {e}")
    _checker = threading.Thread(target=loop, daemon=True, name="host-checker")
    _checker.start()
    return _checker


_checker: threading.Thread | None = None


# ---------------------------------------------------------------- email
def _deliver(store, kind: str, mail: dict) -> dict:
    """Outbox first, then SMTP — the same plumbing and daily cap as incident emails."""
    from .escalation import CFG
    recips = notify.default_recipients()
    day_ago = _iso(datetime.now(timezone.utc) - timedelta(days=1))
    if not recips:
        status = "no-recipients"
    elif not notify.smtp_configured():
        status = "outbox-only"
    elif store.emails_sent_since(day_ago) >= CFG["limits"]["emails_per_day"]:
        status = "rate-limited"
    else:
        status = "queued"
    nid = store.add_notification({"incident_id": kind, "channel": "email", "recipients": recips,
                                  "subject": mail["subject"], "body_text": mail["text"], "body_html": mail["html"],
                                  "status": status})
    if status == "queued":
        notify.deliver(store, nid, recips, mail)
    return {"notification_id": nid, "status": status}


def _wrap(title: str, body_html: str, footer: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#f3f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2933">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px"><tr><td align="center">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #dde3e8">
<tr><td style="background:#546e7a;color:#fff;padding:14px 20px;font-size:14px;font-weight:600">◆ AI Governance Console · Host</td></tr>
<tr><td style="padding:20px;font-size:14px;line-height:1.5"><h1 style="font-size:20px;line-height:1.3;margin:0 0 12px">{escape(title)}</h1>
{body_html}</td></tr>
<tr><td style="padding:12px 20px;background:#f7f9fa;color:#7b8794;font-size:12px">{escape(footer)}</td></tr>
</table></td></tr></table></body></html>"""


def alert_email(store, settings, console_url: str, a: dict, event: str) -> dict:
    name = cfg(settings)["name"]
    url = f"{console_url.rstrip('/')}/host"
    resolved = event == "resolved"
    what = a["message"] if a["message"].startswith(name) else f"{name}: {a['message']}"
    subject = f"[RESOLVED] {what}" if resolved else f"[{a['severity'].upper()}] {what}"
    lines = [f"{name} host alert {'resolved' if resolved else 'opened'}: {a['message']}", "",
             f"Kind: {a['kind']}", f"Severity: {a['severity']}", f"Opened: {a['ts'][:16].replace('T', ' ')} UTC"]
    if resolved:
        lines.append(f"Resolved: {a['resolved_ts'][:16].replace('T', ' ')} UTC — {a.get('resolution') or ''}")
    if a["kind"] == "stale":
        lines += ["", "If the box itself is down this console is down with it and this email may never leave; "
                      "the external uptime check covers that case."]
    lines += ["", f"Host tab: {url}"]
    color = notify.SEVERITY_COLOR.get(a["severity"], "#546e7a") if not resolved else "#2e7d32"
    html = _wrap(f"{'Resolved' if resolved else 'Alert'}: {a['message']}",
                 f'<p><span style="display:inline-block;background:{color};color:#fff;font-size:12px;font-weight:700;'
                 f'padding:3px 8px;border-radius:4px">{"RESOLVED" if resolved else escape(a["severity"].upper())}</span></p>'
                 + "".join(f"<p style='margin:4px 0'>{escape(x)}</p>" for x in lines[2:] if x and not x.startswith("Host tab"))
                 + f'<p style="margin:18px 0 0"><a href="{escape(url)}" style="background:#546e7a;color:#fff;text-decoration:none;'
                   f'padding:10px 16px;border-radius:6px;font-weight:600;display:inline-block">Open the Host tab</a></p>',
                 "Host alerts email once when they open and once when they resolve. Thresholds: config/settings.yaml host:.")
    return _deliver(store, "host:alert", {"subject": subject, "text": "\n".join(lines), "html": html})


# ---------------------------------------------------------------- weekly health & security report
def report_due(store, settings: dict, now: datetime | None = None) -> bool:
    now = _now(now)
    last = store.host_status().get("report")
    if not last:     # first sample ever: start the clock rather than email an empty week
        if store.latest_host_sample():
            store.set_host_status("report", {"baseline": True}, _iso(now))
        return False
    return now - _parse(last["ts"]) >= timedelta(days=cfg(settings)["report_every_days"])


def report_data(store, settings: dict, now: datetime | None = None) -> dict:
    c, now = cfg(settings), _now(now)
    week = now - timedelta(days=7)
    hours = store.host_hourly(_iso(week)[:13])

    def agg(avg_key, max_key):
        vals = [(h[avg_key], h["samples"]) for h in hours if h[avg_key] is not None]
        peaks = [h[max_key] for h in hours if h[max_key] is not None]
        n = sum(w for _, w in vals)
        return {"avg": _r(sum(v * w for v, w in vals) / n) if n else None, "peak": _r(max(peaks)) if peaks else None}
    stats = {"cpu": agg("cpu_avg", "cpu_max"), "mem": agg("mem_avg", "mem_max"), "load1": agg("load1_avg", "load1_max"),
             "temp": agg("temp_avg", "temp_max"),
             "disk": {"avg": None, "peak": _r(max((h["disk_max"] for h in hours if h["disk_max"] is not None), default=None))}}
    first = store.query("select doc from host_metrics where ts >= ? order by ts limit 1", (_iso(week),))
    latest = store.latest_host_sample()
    start = {x["name"]: x.get("restarts") for x in (json.loads(first[0]["doc"]).get("containers") if first else [])}
    containers = []
    for ct in (latest or {}).get("doc", {}).get("containers") or []:
        s0 = start.get(ct["name"])
        containers.append({**ct, "restarts_7d": max(0, (ct.get("restarts") or 0) - s0) if s0 is not None else None})
    alerts = store.host_alerts(since=_iso(week), limit=500)
    status = store.host_status()
    pt = (status.get("pentest") or {}).get("doc")
    mt = (status.get("maintenance") or {}).get("doc")
    return {"name": c["name"], "from": _iso(week), "to": _iso(now), "samples": sum(h["samples"] for h in hours),
            "stats": stats, "containers": containers, "latest": latest,
            "alerts_opened": [a for a in alerts if a["ts"] >= _iso(week)],
            "alerts_resolved": [a for a in alerts if a["resolved_ts"] and a["resolved_ts"] >= _iso(week)],
            "alerts_open": [a for a in alerts if not a["resolved_ts"]],
            "backup": {**backup_view((status.get("backup") or {}).get("doc"), now),
                       "doc": (status.get("backup") or {}).get("doc")},
            "maintenance": {"ts": (mt or {}).get("ts"), "actions": maintenance_actions(mt), "reported": bool(mt)},
            "pentest": {"reported": bool(pt), "ts": pentest_ts(pt), "counts": pentest_counts(pt),
                        "top": pentest_findings(pt)[:8], "has_report": bool((pt or {}).get("report_md"))},
            "deploy": (status.get("deploy") or {}).get("doc") or {}}


def build_report(store, settings: dict, console_url: str, reason: str = "weekly", now: datetime | None = None) -> dict:
    d = report_data(store, settings, now)
    base = console_url.rstrip("/")
    name, st = d["name"], d["stats"]
    f = lambda v, u="": "—" if v is None else f"{v:g}{u}"  # noqa: E731
    pc = d["pentest"]["counts"]
    sev_line = ", ".join(f"{pc[s]} {s}" for s in SEVERITIES if pc[s]) or "no findings"
    b = d["backup"]
    backup_line = ("not reported" if not b["reported"] else
                   f"{'OK' if b['ok'] else 'FAILED'}, last {b['ts'] or '?'}" + (f" ({b['age_h']:g} h ago)" if b["age_h"] is not None else ""))
    text = [f"{name} health & security report — {d['from'][:10]} to {d['to'][:10]} ({reason})", "",
            "LOAD (7 days, hourly averages; peak = highest minute)",
            f"  CPU          avg {f(st['cpu']['avg'], '%')}  peak {f(st['cpu']['peak'], '%')}",
            f"  Memory       avg {f(st['mem']['avg'], '%')}  peak {f(st['mem']['peak'], '%')}",
            f"  Load (1 min) avg {f(st['load1']['avg'])}  peak {f(st['load1']['peak'])}",
            f"  Disk         peak {f(st['disk']['peak'], '%')}",
            f"  Temperature  avg {f(st['temp']['avg'], ' °C')}  peak {f(st['temp']['peak'], ' °C')}",
            f"  Samples      {d['samples']}", "", "CONTAINERS"]
    text += [f"  {ct['name']}: {ct.get('state')}{' / ' + ct['health'] if ct.get('health') not in ('', 'none', None) else ''}, "
             f"restarts this week {ct['restarts_7d'] if ct['restarts_7d'] is not None else '?'} (total {ct.get('restarts')})"
             for ct in d["containers"]] or ["  no container data"]
    text += ["", f"ALERTS: {len(d['alerts_opened'])} opened, {len(d['alerts_resolved'])} resolved, {len(d['alerts_open'])} still open"]
    text += [f"  {a['ts'][:16].replace('T', ' ')} [{a['severity']}] {a['message']}"
             + (f" — resolved {a['resolved_ts'][:16].replace('T', ' ')}" if a["resolved_ts"] else " — OPEN")
             for a in d["alerts_opened"][:20]]
    text += ["", f"BACKUP: {backup_line}", "", f"UPDATES & MAINTENANCE ({len(d['maintenance']['actions'])} actions)"]
    text += [f"  - {a['what']}" + (f"\n      $ {a['command']}" if a["command"] else "") for a in d["maintenance"]["actions"]] or ["  none"]
    text += ["", f"SECURITY SCAN: {d['pentest']['ts'] or 'not reported'} — {sev_line}"]
    text += [f"  [{x['severity'].upper()}] {x['title']}" + (f" ({x['where']})" if x["where"] else "")
             + (f"\n      fix: {x['fix']}" if x["fix"] else "") for x in d["pentest"]["top"]]
    text += ["", f"Host tab: {base}/host", f"Full security report: {base}/host/security (admin sign-in)"]

    def tr(cells, th=False):
        tag = "th" if th else "td"
        return "<tr>" + "".join(f'<{tag} style="padding:4px 10px 4px 0;text-align:left;border-bottom:1px solid #eef1f4;'
                                f'vertical-align:top{";color:#5f6b76;font-weight:500" if th else ""}">{c}</{tag}>' for c in cells) + "</tr>"
    E = lambda v: escape(str(v))  # noqa: E731
    h = [f'<p style="color:#5f6b76;margin:0 0 14px">{E(d["from"][:10])} to {E(d["to"][:10])} · {E(reason)} · {d["samples"]} samples</p>',
         '<h2 style="font-size:16px;margin:16px 0 6px">Load</h2><table style="border-collapse:collapse;font-size:14px">',
         tr(["", "7-day avg", "Peak"], True)]
    for label, k, u in (("CPU", "cpu", "%"), ("Memory", "mem", "%"), ("Load (1 min)", "load1", ""), ("Disk", "disk", "%"),
                        ("Temperature", "temp", " °C")):
        h.append(tr([label, E(f(st[k]["avg"], u)), E(f(st[k]["peak"], u))]))
    h.append('</table><h2 style="font-size:16px;margin:16px 0 6px">Containers</h2><table style="border-collapse:collapse;font-size:14px">')
    h.append(tr(["Container", "State", "Restarts this week", "Total"], True))
    h += [tr([E(ct["name"]), E((ct.get("state") or "") + (" / " + ct["health"] if ct.get("health") not in ("", "none", None) else "")),
              E(ct["restarts_7d"] if ct["restarts_7d"] is not None else "?"), E(ct.get("restarts"))]) for ct in d["containers"]]
    h.append("</table>")
    h.append(f'<h2 style="font-size:16px;margin:16px 0 6px">Alerts</h2><p style="margin:0 0 6px">{len(d["alerts_opened"])} opened · '
             f'{len(d["alerts_resolved"])} resolved · <b>{len(d["alerts_open"])} still open</b></p><ul style="margin:0;padding-left:18px">')
    h += [f"<li>{E(a['ts'][:16].replace('T', ' '))} <b>{E(a['severity'])}</b> {E(a['message'])}"
          + (f" — resolved {E(a['resolved_ts'][:16].replace('T', ' '))}" if a["resolved_ts"] else " — <b>open</b>") + "</li>"
          for a in d["alerts_opened"][:20]] or ["<li>None.</li>"]
    h.append(f'</ul><h2 style="font-size:16px;margin:16px 0 6px">Backup</h2><p style="margin:0">{E(backup_line)}</p>')
    h.append(f'<h2 style="font-size:16px;margin:16px 0 6px">Updates &amp; maintenance</h2><ul style="margin:0;padding-left:18px">')
    h += [f"<li>{E(a['what'])}" + (f'<br><code style="background:#f3f5f7;padding:1px 4px;border-radius:3px">{E(a["command"])}</code>'
                                   if a["command"] else "") + "</li>" for a in d["maintenance"]["actions"]] or ["<li>None.</li>"]
    h.append(f'</ul><h2 style="font-size:16px;margin:16px 0 6px">Security scan</h2><p style="margin:0 0 6px">'
             f'{E(d["pentest"]["ts"] or "not reported")} — {E(sev_line)}</p><ul style="margin:0;padding-left:18px">')
    h += [f"<li><b>{E(x['severity'].upper())}</b> {E(x['title'])}" + (f" <span style='color:#5f6b76'>({E(x['where'])})</span>" if x["where"] else "")
          + (f"<br>Fix: {E(x['fix'])}" if x["fix"] else "") + "</li>" for x in d["pentest"]["top"]]
    h.append(f'</ul><p style="margin:20px 0 0"><a href="{E(base)}/host" style="background:#546e7a;color:#fff;text-decoration:none;'
             f'padding:10px 16px;border-radius:6px;font-weight:600;display:inline-block">Open the Host tab</a> &nbsp; '
             f'<a href="{E(base)}/host/security" style="color:#37474f">Full security report</a></p>')
    subject = f"{name} health & security report — week to {d['to'][:10]}" + (f" ({sev_line})" if d["pentest"]["reported"] else "")
    return {"subject": subject, "text": "\n".join(text),
            "html": _wrap(f"{name} health & security report", "".join(h),
                          "Sent weekly and whenever a new security scan arrives. Contains security findings: don't forward."),
            "data": d}


def send_report(store, settings: dict, console_url: str, reason: str = "weekly", now: datetime | None = None) -> dict:
    mail = build_report(store, settings, console_url, reason, now)
    res = _deliver(store, "host:report", mail)
    store.set_host_status("report", {"reason": reason, **res}, _iso(_now(now)))
    return res


# ---------------------------------------------------------------- read side: summary + history
def summary(store, settings: dict, console_url: str = "", now: datetime | None = None) -> dict:
    """Public, no secrets: numbers, counts and states only. The site assistant's daily email reads this."""
    c, now = cfg(settings), _now(now)
    latest = store.latest_host_sample()
    status = store.host_status()
    out = {"ok": True, "host": c["name"], "url": f"{console_url.rstrip('/')}/host" if console_url else "",
           "reporting": False, "last_seen": None, "age_s": None, "now": None, "last_24h": None,
           "containers": {"up": 0, "total": 0, "unhealthy": 0, "down": []}}
    if latest:
        h = latest["doc"]["host"]
        age = (now - _parse(latest["ts"])).total_seconds()
        out.update(reporting=age < c["stale_minutes"] * 60, last_seen=latest["ts"], age_s=int(age),
                   now={k: h.get(k) for k in ("hostname", "cpu_pct", "load1", "load5", "load15", "cpu_count", "mem_total_gb",
                                              "mem_used_pct", "swap_used_pct", "temp_c", "uptime_s")}
                   | {"disk_used_pct": latest["disk_used_pct"],
                      "disks": [{"used_pct": d.get("used_pct"), "free_gb": d.get("free_gb"),
                                 "which": "root" if d.get("mount") == "/" else "docker"} for d in h.get("disks") or []]})
        day = store.host_samples(_iso(now - timedelta(hours=24)))
        def avgmax(k):
            v = [r[k] for r in day if r[k] is not None]
            return (_r(sum(v) / len(v)) if v else None), (_r(max(v)) if v else None)
        (ca, cm), (ma, mm), (_, tm), (la, lm) = avgmax("cpu_pct"), avgmax("mem_used_pct"), avgmax("temp_c"), avgmax("load1")
        out["last_24h"] = {"samples": len(day), "cpu_avg": ca, "cpu_peak": cm, "mem_avg": ma, "mem_peak": mm,
                           "load1_avg": la, "load1_peak": lm, "temp_peak": tm}
        cts = latest["doc"].get("containers") or []
        out["containers"] = {"up": sum(1 for x in cts if x.get("state") == "running"), "total": len(cts),
                             "unhealthy": sum(1 for x in cts if x.get("health") == "unhealthy"),
                             "down": [x["name"] for x in cts if x.get("state") != "running"]}
    b = backup_view((status.get("backup") or {}).get("doc"), now)
    out["backup"] = {"reported": b["reported"], "ok": b["ok"], "last": b["ts"], "age_h": b["age_h"],
                     "stale": b["reported"] and (b["age_h"] is None or b["age_h"] > c["backup_max_age_hours"])}
    pt = (status.get("pentest") or {}).get("doc")
    out["pentest"] = {"reported": bool(pt), "ts": pentest_ts(pt) or None, "counts": pentest_counts(pt)}
    mt = (status.get("maintenance") or {}).get("doc")
    out["maintenance"] = {"reported": bool(mt), "ts": (mt or {}).get("ts"), "actions": len(maintenance_actions(mt))}
    dep = (status.get("deploy") or {}).get("doc") or {}
    out["deploy"] = {"deployed": (dep.get("deployed") or "")[:7] or None, "failed": (dep.get("failed") or "")[:7] or None,
                     "at": (status.get("deploy") or {}).get("ts")}
    out["alerts_open"] = [{"kind": a["kind"], "severity": a["severity"], "message": a["message"], "since": a["ts"]}
                          for a in store.host_alerts(open_only=True)]
    rep = status.get("report")
    out["last_report"] = rep["ts"] if rep and not rep["doc"].get("baseline") else None
    return out


RANGES = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def history(store, rng: str, now: datetime | None = None) -> dict:
    """Chart series. 1 h: every minute; 24 h: 10-minute averages; 7 d and 30 d: the hourly rollup."""
    now = _now(now)
    rng = rng if rng in RANGES else "24h"
    since = _iso(now - RANGES[rng])
    out = {"range": rng, "labels": [], "cpu": [], "mem": [], "load1": [], "temp": [], "cpu_peak": []}
    if rng in ("7d", "30d"):
        for h in store.host_hourly(since[:13]):
            out["labels"].append(h["hour"] + ":00:00+00:00")
            for k, src in (("cpu", "cpu_avg"), ("mem", "mem_avg"), ("load1", "load1_avg"), ("temp", "temp_avg"),
                           ("cpu_peak", "cpu_max")):
                out[k].append(_r(h[src]))
        return out
    rows = store.host_samples(since)
    width = 16 if rng == "1h" else 15             # bucket by minute or by 10 minutes (ts[:15] = 'YYYY-MM-DDTHH:M')
    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(r["ts"][:width], []).append(r)
    for key, rs in buckets.items():
        out["labels"].append(key + ("0" if width == 15 else "") + ":00+00:00")
        for k, src in (("cpu", "cpu_pct"), ("mem", "mem_used_pct"), ("load1", "load1"), ("temp", "temp_c")):
            v = [x[src] for x in rs if x[src] is not None]
            out[k].append(_r(sum(v) / len(v)) if v else None)
        v = [x["cpu_pct"] for x in rs if x["cpu_pct"] is not None]
        out["cpu_peak"].append(_r(max(v)) if v else None)
    return out


# ---------------------------------------------------------------- the pentest report: Markdown → safe HTML
def _inline(s: str) -> str:
    s = escape(s, quote=True)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener noreferrer">\1</a>', s)
    return s


def md_to_html(md: str) -> str:
    """A small, safe subset (headings, paragraphs, lists, fenced code, tables, quotes, `code`, **bold**, http links).
    Everything is escaped first, so the report can't inject markup or script."""
    out, para, lst, tbl = [], [], None, []
    lines = (md or "").replace("\r\n", "\n").split("\n")

    def flush():
        nonlocal para, lst, tbl
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
        if lst:
            out.append(f"<{lst[0]}>" + "".join(f"<li>{_inline(x)}</li>" for x in lst[1]) + f"</{lst[0]}>")
        if tbl:
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl
                    if not re.fullmatch(r"\|?[\s:|-]+\|?", r.strip())]
            if rows:
                out.append('<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in rows[0])
                           + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                                                             for r in rows[1:]) + "</tbody></table></div>")
        para, lst, tbl = [], None, []

    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append("<pre><code>" + escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        if m := re.match(r"^(#{1,6})\s+(.*)$", ln):
            flush()
            lvl = min(len(m.group(1)) + 1, 6)        # the page already has an h1
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
        elif ln.strip().startswith("|"):
            if para or lst:
                flush()
            tbl.append(ln)
        elif m := re.match(r"^\s*([-*]|\d+[.)])\s+(.*)$", ln):
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if para or tbl or (lst and lst[0] != kind):
                flush()
            lst = lst or (kind, [])
            lst[1].append(m.group(2))
        elif ln.startswith(">"):
            flush()
            out.append("<blockquote>" + _inline(ln.lstrip("> ")) + "</blockquote>")
        elif not ln.strip():
            flush()
        elif lst and ln.startswith("  "):
            lst[1][-1] += " " + ln.strip()
        else:
            if lst or tbl:
                flush()
            para.append(ln.strip())
        i += 1
    flush()
    return "\n".join(out)
