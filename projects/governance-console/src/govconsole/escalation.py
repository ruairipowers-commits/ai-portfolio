"""Governance escalation: detect an issue, open an incident, switch the workflow off if it's serious, tell a person.

    event arrives ─▶ event rules (flags) ─┐
    every 5 min  ─▶ aggregate rules ──────┴─▶ raise_issue()
                       budget · spend anomaly · unregistered workflow       │
        ┌────────────────────────────────────────────────────────────────┘
        ├─ an open incident for this workflow + rule already? → count the repeat, add the evidence, stop
        ├─ open INC-nnnn with the evidence and the rule's guidance
        ├─ severity ≥ the workflow's auto-shutdown level → kill switch off ("governance-console (auto)")
        └─ severity ≥ its notify level → email to its recipients (outbox first, then SMTP)

One open incident per workflow and rule is the throttle: a workflow that keeps tripping the same rule produces
one email until someone resolves the incident. Resolving it (in the console) records root cause, fix and
documentation, and can switch the workflow back on in the same step.

Rules and defaults: config/escalation.yaml. Per-workflow choices: the Settings page (escalation_settings table).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import metrics as M
from . import notify
from .store import now_iso

CONFIG = Path(__file__).resolve().parents[2] / "config" / "escalation.yaml"
AUTO_ACTOR = "governance-console (auto)"


def load() -> dict:
    return yaml.safe_load(CONFIG.read_text())


CFG = load()
SEVERITIES = CFG["severities"]


def rank(sev: str) -> int:
    return SEVERITIES.index(sev) if sev in SEVERITIES else len(SEVERITIES)   # "never" ranks above everything


def rules() -> dict[str, dict]:
    return {r["id"]: r for r in CFG["rules"]}


def demo_mode() -> bool:
    return os.getenv("PORTFOLIO_DEMO") == "1"


def settings_for(store, slug: str, stored: dict | None = None) -> dict:
    """Defaults from config, overlaid with what was saved on the Settings page."""
    s = {**CFG["defaults"], **((stored if stored is not None else store.escalation_settings()).get(slug) or {})}
    s["rule_ids"] = list(rules()) if s.get("rules", "all") == "all" else [r for r in s["rules"] if r in rules()]
    s["effective_recipients"] = list(dict.fromkeys([*s.get("recipients", []), *notify.default_recipients()]))
    return s


# ---------------------------------------------------------------- detection
def match_event(ev: dict) -> list[dict]:
    flags = set(ev.get("flags") or [])
    return [r for r in CFG["rules"] if "match" in r and flags & set(r["match"].get("flags", []))]


def _evidence(ev: dict) -> dict:
    keep = ("event_id", "ts", "workflow", "event_type", "status", "actor", "actor_type", "run_id", "model", "flags",
            "session_id", "environment", "cost_usd", "records_in", "records_out")
    out = {k: ev.get(k) for k in keep if ev.get(k) not in (None, "", [])}
    out["detail"] = {k: v for k, v in list((ev.get("detail") or {}).items())[:12]}
    return out


def _event_summary(rule: dict, ev: dict, wf_name: str) -> str:
    who = ev.get("actor") or "someone"
    what = (ev.get("detail") or {}).get("action") or ev.get("event_type", "run")
    flags = ", ".join(f for f in ev.get("flags") or [] if f in rule["match"]["flags"])
    run = f" (run {ev['run_id']})" if ev.get("run_id") else ""
    return (f"{wf_name}: the {what} by {who}{run} raised {flags}. The workflow's own guardrails reported it; the "
            f"console treats '{rule['title'].lower()}' as {rule['severity']} severity under control "
            f"{rule.get('control', '—')}.")


def on_events(store, catalog: dict, events: list[dict], console_url: str) -> list[dict]:
    """Check freshly ingested live events against the event rules. Returns incidents opened or updated."""
    names = {w["slug"]: w["name"] for w in catalog["workflows"]}
    out = []
    for ev in events:
        if ev.get("source", "live") != "live" or ev.get("event_type") in ("register", "visit"):
            continue
        for rule in match_event(ev):
            name = names.get(ev["workflow"], ev["workflow"])
            out.append(raise_issue(store, catalog, ev["workflow"], rule, _evidence(ev),
                                   _event_summary(rule, ev, name), console_url))
    return [i for i in out if i]


def check_aggregates(store, catalog: dict, console_url: str) -> list[dict]:
    """Budget threshold, spend anomaly today, unregistered workflows — over live events only."""
    out = []
    rs = rules()
    for row in M.workflow_table(store, catalog, include_simulated=False):
        if not row["registered"] and row["runs_30d"]:
            out.append(raise_issue(store, catalog, row["slug"], rs["shadow-ai"],
                                   {"workflow": row["slug"], "runs_30d": row["runs_30d"], "cost_30d": row["cost_30d"],
                                    "users_30d": row["users_30d"], "declared": row["declared"]},
                                   f"'{row['slug']}' sent {row['runs_30d']} AI runs (${row['cost_30d']:.2f}) in the last 30 "
                                   f"days but is not in the workflow catalog, so it has no owner, risk tier or control mapping.",
                                   console_url))
        if row["registered"] and row["budget_warn"]:
            out.append(raise_issue(store, catalog, row["slug"], rs["budget-threshold"],
                                   {"workflow": row["slug"], "cost_30d": row["cost_30d"], "budget": row["budget"],
                                    "budget_pct": row["budget_pct"]},
                                   f"{row['name']} spent ${row['cost_30d']:.2f} in the trailing 30 days — "
                                   f"{row['budget_pct']:.0f}% of its ${row['budget']:.0f} monthly budget.", console_url))
    today = datetime.now(timezone.utc).date().isoformat()
    for a in M.detect_anomalies(store, days=1, include_simulated=False):
        if a["day"] == today:
            out.append(raise_issue(store, catalog, a["workflow"], rs["spend-anomaly"], a,
                                   f"{a['workflow']} spent ${a['cost']:.2f} today, {a['factor']}× its trailing "
                                   f"14-day median of ${a['median']:.2f}.", console_url))
    return [i for i in out if i]


# ---------------------------------------------------------------- response
def raise_issue(store, catalog: dict, slug: str, rule: dict, evidence: dict, summary: str,
                console_url: str) -> dict | None:
    cfg = settings_for(store, slug)
    if rule["id"] not in cfg["rule_ids"]:
        return None
    now = now_iso()
    existing = store.open_incident(slug, rule["id"])
    if existing:   # throttle: one open incident (and one email) per workflow and rule
        ev = (existing["evidence"] + [evidence])[-10:]
        store.update_incident(existing["incident_id"], occurrences=existing["occurrences"] + 1, last_seen=now, evidence=ev)
        store.log_incident(existing["incident_id"], "repeat", "", f"Happened again ({existing['occurrences'] + 1} times). "
                           f"{evidence.get('actor', '')} {evidence.get('run_id', '')}".strip())
        return {**existing, "occurrences": existing["occurrences"] + 1, "repeat": True}

    inc = store.create_incident({"opened_at": now, "workflow": slug, "rule_id": rule["id"], "severity": rule["severity"],
                                 "title": rule["title"], "control_id": rule.get("control"), "summary": summary,
                                 "evidence": [evidence]})
    store.log_incident(inc["incident_id"], "opened", AUTO_ACTOR, summary)
    registered = slug in {w["slug"] for w in catalog["workflows"]}
    shutdown_note = "Still running (below this workflow's auto-shutdown level)."
    if registered and rank(rule["severity"]) >= rank(cfg["auto_shutdown_at"]):
        state = store.effective_state().get(slug)
        if not state or state["enabled"]:
            mins = CFG["limits"]["demo_shutdown_minutes"]
            exp = (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat(timespec="seconds") if demo_mode() else None
            store.set_enabled(slug, False, f"Automatic: {inc['incident_id']} — {rule['title']}", AUTO_ACTOR, expires_at=exp)
            shutdown_note = ("Switched off automatically" +
                             (f" (public demo: lapses after {mins} minutes)." if exp else "."))
        else:
            shutdown_note = "Already switched off."
        store.update_incident(inc["incident_id"], auto_shutdown=1)
        inc["auto_shutdown"] = 1
        store.log_incident(inc["incident_id"], "shutdown", AUTO_ACTOR, shutdown_note)
    elif not registered:
        shutdown_note = "Not in the catalog, so the console has no switch for it."

    if cfg["alerts_enabled"] and rank(rule["severity"]) >= rank(cfg["notify_at"]):
        _notify(store, catalog, inc, rule, cfg, console_url, shutdown_note)
    return inc


def _notify(store, catalog, inc, rule, cfg, console_url, shutdown_note) -> None:
    wf = next((w for w in catalog["workflows"] if w["slug"] == inc["workflow"]), {"name": inc["workflow"]})
    url = f"{console_url.rstrip('/')}/incidents/{inc['incident_id']}"
    from .links import for_slug
    mail = notify.incident_email(inc, rule, wf["name"], M.wf_config(inc["workflow"])["owner"], url, shutdown_note,
                                 for_slug(inc["workflow"]).get("demo", ""))
    recips = cfg["effective_recipients"]
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    if not recips:
        status = "no-recipients"
    elif not notify.smtp_configured():
        status = "outbox-only"
    elif store.emails_sent_since(day_ago) >= CFG["limits"]["emails_per_day"]:
        status = "rate-limited"
    else:
        status = "queued"
    nid = store.add_notification({"incident_id": inc["incident_id"], "channel": "email", "recipients": recips,
                                  "subject": mail["subject"], "body_text": mail["text"], "body_html": mail["html"],
                                  "status": status})
    store.log_incident(inc["incident_id"], "notified", AUTO_ACTOR,
                       f"Email to {', '.join(recips) or 'nobody (no recipients set)'}"
                       + ("." if status == "queued" else f" — {status}."))
    if status == "queued":
        notify.deliver(store, nid, recips, mail)


# ---------------------------------------------------------------- resolution
def resolve(store, incident_id: str, actor: str, root_cause: str, fix: str, documentation: str,
            reenable: bool, attest: bool) -> dict:
    inc = store.incident(incident_id)
    if not inc or inc["status"] == "resolved":
        raise ValueError("unknown or already resolved incident")
    now = now_iso()
    text = f"Root cause: {root_cause}\nFix: {fix}\nDocumented: {documentation}"
    store.update_incident(incident_id, status="resolved", resolved_at=now, resolved_by=actor, resolution=text)
    store.log_incident(incident_id, "resolved", actor, text)
    if attest and inc.get("control_id"):
        store.attest(inc["workflow"], inc["control_id"], "confirmed", actor,
                     f"Re-confirmed after {incident_id}: {fix}"[:300])
        store.log_incident(incident_id, "attested", actor, f"{inc['control_id']} re-confirmed.")
    if reenable:
        store.set_enabled(inc["workflow"], True, f"{incident_id} resolved: {fix}"[:300], actor)
        store.log_incident(incident_id, "reenabled", actor, "Workflow switched back on.")
    return store.incident(incident_id)


# ---------------------------------------------------------------- background checker
def start_checker(get_store, get_catalog, console_url_fn) -> threading.Thread:
    """Aggregate rules every `check_interval_minutes` (daemon thread; one per process)."""
    global _checker
    if _checker is not None:
        return _checker

    def loop():
        while True:
            time.sleep(60 * CFG["limits"]["check_interval_minutes"])
            try:
                check_aggregates(get_store(), get_catalog(), console_url_fn())
            except Exception as e:  # noqa: BLE001 — the checker must never take the console down
                print(f"escalation check failed: {type(e).__name__}: {e}")
    _checker = threading.Thread(target=loop, daemon=True, name="escalation-checker")
    _checker.start()
    return _checker


_checker: threading.Thread | None = None
