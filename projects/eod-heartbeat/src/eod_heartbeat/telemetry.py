"""Governance telemetry: report every run to the organisation's governance hub and obey its kill switch.

The same small module ships in every portfolio project, so a new workflow shows up in the hub as soon as
it runs (it registers its title, risk tier, budgets, models and control mapping from its own files).

Where events go (first match):
  GOVERNANCE_DATABASE_URL   postgresql://…  shared store for hosted demos / production
  GOVERNANCE_DB             path to a SQLite file
  default                   ~/.ai-governance/governance.sqlite (shared by every project on this machine)
Set GOVERNANCE_TELEMETRY=off to disable. This is first-party telemetry to *your* hub — unrelated to
Streamlit's usage stats, which stay off.

What is recorded: workflow, action, actor (a name the user typed, or an anonymous visitor id), model, tokens,
cost, latency, items and rows processed, outcome flags. Never prompts, questions, documents or answers —
only counts and hashes (DATA-03).

Telemetry is best-effort: a failure is logged and never breaks the workflow. The kill switch fails open
when the store is unreachable unless GOVERNANCE_FAIL_CLOSED=1.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT = "eod-heartbeat"
log = logging.getLogger(__name__)

SCHEMA = [
    """create table if not exists gov_workflows (workflow text primary key, title text, risk_tier text, owner text,
       version text, env text, registered_at text, last_seen text, meta text)""",
    """create table if not exists gov_events (event_id text primary key, ts text not null, workflow text not null,
       env text, event_type text, action text, run_id text, actor text, status text, model text,
       input_tokens integer, output_tokens integer, cost_usd real, latency_ms integer, items integer,
       rows_in integer, flags text, detail text)""",
    "create index if not exists gov_events_ts on gov_events (ts)",
    "create index if not exists gov_events_wf on gov_events (workflow, ts)",
    """create table if not exists gov_workflow_state (workflow text primary key, enabled integer not null,
       reason text, changed_by text, changed_at text)""",
]


class WorkflowDisabled(RuntimeError):
    """Raised when the governance hub has switched this workflow off."""


def active() -> bool:
    return os.getenv("GOVERNANCE_TELEMETRY", "on").lower() not in ("off", "0", "false")


def environment() -> str:
    if os.getenv("GOVERNANCE_ENV"):
        return os.environ["GOVERNANCE_ENV"]
    if os.getenv("PORTFOLIO_DEMO") == "1":
        return "demo"
    return "ci" if os.getenv("CI") else "local"


def store() -> str:
    return (os.getenv("GOVERNANCE_DATABASE_URL") or os.getenv("GOVERNANCE_DB")
            or str(Path.home() / ".ai-governance" / "governance.sqlite"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- storage (SQLite or Postgres, same SQL)
_ready: set[str] = set()


def _connect():
    url = store()
    if url.startswith(("postgres://", "postgresql://")):
        import psycopg  # pip install 'psycopg[binary]'

        con = psycopg.connect(url, connect_timeout=3, autocommit=True)
        pg = True
    else:
        Path(url).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(url, timeout=5)
        con.execute("pragma journal_mode=wal")
        pg = False
    if url not in _ready:
        for ddl in SCHEMA:
            con.execute(ddl)
        if not pg:
            con.commit()
        _ready.add(url)
    return con, pg


def _execute(sql: str, params: tuple = (), fetch: bool = False):
    con, pg = _connect()
    try:
        cur = con.execute(sql.replace("?", "%s") if pg else sql, params)
        rows = cur.fetchall() if fetch else None
        if not pg:
            con.commit()
        return rows
    finally:
        con.close()


# ---------------------------------------------------------------- self-registration
def _controls(root: Path) -> list[dict]:
    """Every control row of docs/governance.md: id, status, how it's done, where it's configured."""
    p = root / "docs" / "governance.md"
    if not p.exists():
        return []
    rows = re.findall(r"(?m)^\|\s*([A-Z]+-\d+)\s+([^|]*?)\s*\|\s*(✅|🟡|⚪|🔷)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", p.read_text())
    return [{"id": i, "name": n.strip(), "status": s, "how": h.strip(), "config": c.strip(), "options": o.strip()}
            for i, n, s, h, c, o in rows]


def _models(root: Path) -> list[dict]:
    p = root / "config" / "models.yaml"
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text())
    used = {}
    for alias, name in raw.get("aliases", {}).items():
        used.setdefault(name, []).append(alias)
    return [{"name": n, "provider": m.get("provider"), "model_id": str(m.get("model_id")), "kind": m.get("kind", "chat"),
             "approved": bool(m.get("approved")), "priced": m.get("input_per_mtok") is not None,
             "deprecation_date": str(m["deprecation_date"]) if m.get("deprecation_date") else None,
             "aliases": used.get(n, [])} for n, m in raw.get("models", {}).items()]


def metadata(root: Path) -> dict:
    s = yaml.safe_load((root / "config" / "settings.yaml").read_text())
    wf = s.get("workflow", {})
    links = {}
    if (root / "portfolio_links.json").exists():
        links = json.loads((root / "portfolio_links.json").read_text())
    return {"title": wf.get("title", PROJECT), "owner": wf.get("owner", ""), "description": wf.get("description", ""),
            "risk_tier": s.get("risk_tier", ""), "budgets": s.get("cost", {}), "controls": _controls(root),
            "models": _models(root), "links": links}


_registered = 0.0


def register(root: Path, version: str = "") -> None:
    """Upsert this workflow's metadata into the hub (at most every 10 minutes per process)."""
    global _registered
    if not active() or time.time() - _registered < 600:
        return
    try:
        m = metadata(root)
        ts = now()
        _execute("delete from gov_workflows where workflow = ?", (PROJECT,))
        _execute("""insert into gov_workflows (workflow, title, risk_tier, owner, version, env, registered_at, last_seen, meta)
                    values (?,?,?,?,?,?,?,?,?)""",
                 (PROJECT, m["title"], m["risk_tier"], m["owner"], version, environment(), ts, ts, json.dumps(m)))
        _registered = time.time()
    except Exception as e:  # never break the app
        log.warning("governance register failed: %s", e)


# ---------------------------------------------------------------- events
def record(action: str, *, event_type: str = "run", actor: str = "", status: str = "ok", run_id: str = "",
           model: str = "", input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0,
           latency_ms: int = 0, items: int = 0, rows_in: int = 0, flags: list[str] | None = None,
           detail: dict | None = None) -> None:
    if not active():
        return
    try:
        _execute("""insert into gov_events (event_id, ts, workflow, env, event_type, action, run_id, actor, status, model,
                    input_tokens, output_tokens, cost_usd, latency_ms, items, rows_in, flags, detail)
                    values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (uuid.uuid4().hex, now(), PROJECT, environment(), event_type, action, run_id, actor or "unknown", status,
                  model, int(input_tokens), int(output_tokens), float(cost_usd), int(latency_ms), int(items),
                  int(rows_in), json.dumps(sorted(set(flags or []))), json.dumps(detail or {}, default=str)))
    except Exception as e:
        log.warning("governance event failed: %s", e)


# ---------------------------------------------------------------- kill switch
_state_cache: tuple[float, bool, str] = (0.0, True, "")


def status() -> tuple[bool, str]:
    """(enabled, reason) as set in the governance hub. Cached for 15 seconds."""
    global _state_cache
    if not active():
        return True, ""
    if time.time() - _state_cache[0] < 15:
        return _state_cache[1], _state_cache[2]
    try:
        rows = _execute("select enabled, reason, changed_by from gov_workflow_state where workflow = ?", (PROJECT,),
                        fetch=True)
        enabled, reason = (True, "") if not rows else (bool(rows[0][0]),
                                                       f"{rows[0][1] or 'no reason given'} (by {rows[0][2]})")
    except Exception as e:
        log.warning("governance status check failed: %s", e)
        closed = os.getenv("GOVERNANCE_FAIL_CLOSED") == "1"
        enabled, reason = (not closed), ("governance hub unreachable" if closed else "")
    _state_cache = (time.time(), enabled, reason)
    return enabled, reason


def require_enabled(action: str, actor: str = "") -> None:
    """Call before any model call. Raises WorkflowDisabled (and logs the blocked attempt) when switched off."""
    enabled, reason = status()
    if not enabled:
        record(action, event_type="blocked", actor=actor, status="blocked", flags=["kill_switch"])
        raise WorkflowDisabled(f"{PROJECT} is switched off in the governance hub: {reason}")


def visitor_id(session_id: str) -> str:
    """Anonymous, stable id for a browser session (no IPs, no cookies of our own)."""
    return "visitor-" + sha(session_id)[:8]
