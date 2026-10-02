"""Governance telemetry client: report usage to the governance console and obey its kill switch.

The same file ships in every workflow (only PROJECT differs; scripts/check_telemetry_client.py in the portfolio
repo keeps the copies identical). Every visit and every action becomes one event: who, which model, tokens,
cost, latency, records in/out, outcome and safety flags. Never prompts, questions, documents or answers —
only counts, hashes and flags (DATA-03).

Where events go:
  GOVERNANCE_URL set     → POST {url}/api/events from a background thread (Bearer GOVERNANCE_INGEST_TOKEN);
                           if the console can't be reached the event is appended to the spool file instead.
  not set                → appended to the spool file: GOVERNANCE_SPOOL, default ~/.ai-portfolio/governance/events.jsonl.
                           A console running on the same machine imports it (`govconsole import-spool`).
  GOVERNANCE_TELEMETRY=off → nothing is recorded.
Apps hold an append-only ingest token, never database credentials, so a compromised app can't rewrite history
or flip a kill switch.

Kill switch: `status()` asks the console whether this workflow is enabled (cached 15 s). If the console can't be
reached the workflow fails open (runs, and says so) unless GOVERNANCE_FAIL_CLOSED=1. Callers enforce it in the
code path with `require_enabled()`, not only by greying out buttons.

Self-registration: `register(root)` sends the workflow's declared metadata (risk tier, owner, budgets, models,
control mapping from docs/governance.md, links) at most every 10 minutes, so the console shows what is actually
deployed. Registration is a declaration, not an approval: only the console's catalog marks a workflow approved.
"""
from __future__ import annotations

import atexit
import getpass
import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
import urllib.request
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

PROJECT = "trade-ops-exceptions"
CLIENT_VERSION = "1"
log = logging.getLogger(__name__)

_actor: ContextVar[tuple[str, str] | None] = ContextVar(f"{PROJECT}-actor", default=None)
_session: ContextVar[str] = ContextVar(f"{PROJECT}-session", default="")
_queue: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
_worker: threading.Thread | None = None
_state_cache: tuple[float, "Status | None"] = (0.0, None)
_registered = 0.0


class WorkflowDisabled(RuntimeError):
    """Raised when governance has switched this workflow off."""


class Status:
    """Kill-switch state. Unpacks as (enabled, reason) for brevity: `enabled, why = telemetry.status()`."""

    def __init__(self, enabled: bool, reason: str = "", changed_by: str = "", source: str = "default"):
        self.enabled, self.reason, self.changed_by, self.source = enabled, reason, changed_by, source

    def __iter__(self):
        return iter((self.enabled, self.reason))

    def __repr__(self):
        return f"Status(enabled={self.enabled}, reason={self.reason!r}, source={self.source!r})"


# ---------------------------------------------------------------- configuration
def active() -> bool:
    return os.getenv("GOVERNANCE_TELEMETRY", "on").lower() not in ("off", "0", "false")


def environment() -> str:
    if os.getenv("GOVERNANCE_ENV"):
        return os.environ["GOVERNANCE_ENV"]
    if os.getenv("PORTFOLIO_DEMO") == "1":
        return "demo"
    return "ci" if os.getenv("CI") else "local"


def _url() -> str:
    return os.getenv("GOVERNANCE_URL", "").rstrip("/")


def spool_path() -> Path:
    return Path(os.getenv("GOVERNANCE_SPOOL") or Path.home() / ".ai-portfolio" / "governance" / "events.jsonl")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- identity
def set_actor(actor: str, actor_type: str = "named") -> None:
    """Who is acting in this script run / request. actor_type: named | visitor | service."""
    _actor.set((actor, actor_type))


def set_session(session_id: str) -> None:
    _session.set(session_id)


def visitor_id(session_id: str) -> str:
    """Pseudonymous id for an anonymous demo visitor (stable for the browser session)."""
    return f"visitor-{sha(session_id)[:8]}"


def current_actor() -> tuple[str, str]:
    a = _actor.get()
    if a:
        return a
    try:
        return f"local:{getpass.getuser()}", "named"
    except Exception:   # no login name in some containers
        return "local:unknown", "service"


def _actor_type(actor: str) -> str:
    return "visitor" if actor.startswith("visitor-") else "service" if actor in ("ci", "scheduler", "airflow") else "named"


# ---------------------------------------------------------------- events
def emit(event_type: str, *, status: str = "ok", actor: str | None = None, actor_type: str | None = None,
         model: str = "", input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0, latency_ms: int = 0,
         records_in: int = 0, records_out: int = 0, flags: list[str] | None = None, detail: dict | None = None,
         run_id: str = "") -> dict | None:
    """Record one event. Never raises: telemetry must not break the workflow."""
    if not active():
        return None
    try:
        a, at = current_actor()
        if actor:
            a, at = actor, actor_type or _actor_type(actor)
        ev = {"event_id": uuid.uuid4().hex, "ts": now(), "workflow": PROJECT, "event_type": event_type,
              "status": status, "actor": a, "actor_type": actor_type or at, "session_id": _session.get(),
              "environment": environment(), "app_version": CLIENT_VERSION, "run_id": run_id, "model": model or "",
              "input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0),
              "cost_usd": round(float(cost_usd or 0), 6), "latency_ms": int(latency_ms or 0),
              "records_in": int(records_in or 0), "records_out": int(records_out or 0),
              "flags": sorted(set(flags or [])), "detail": json.loads(json.dumps(detail or {}, default=str))}
        if _url():
            _start_worker()
            _queue.put_nowait(ev)
        else:
            _append_spool(ev)
        return ev
    except Exception as e:
        log.warning("governance event failed: %s", e)
        return None


_STATUS_MAP = {"pass": "ok", "fail": "failed"}


def record(action: str, *, event_type: str = "run", actor: str = "", status: str = "ok", run_id: str = "",
           model: str = "", input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0, latency_ms: int = 0,
           items: int = 0, rows_in: int = 0, flags: list[str] | None = None, detail: dict | None = None) -> dict | None:
    """Action-style wrapper: record("ask", items=1, rows_in=5, ...). `items` = outputs, `rows_in` = inputs read."""
    et = event_type if event_type in ("visit", "feedback", "eval") else action
    if et == "feedback" and status in ("wrong", "not_useful"):
        flags = [*(flags or []), "marked_wrong"]
    return emit(et, status=_STATUS_MAP.get(status, status), actor=actor or None, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd, latency_ms=latency_ms,
                records_in=rows_in, records_out=items, flags=flags, run_id=run_id,
                detail={"action": action, **(detail or {})})


def _append_spool(ev: dict) -> None:
    p = spool_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(ev) + "\n")


def _post(events: list[dict]) -> None:
    req = urllib.request.Request(f"{_url()}/api/events", data=json.dumps(events).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {os.getenv('GOVERNANCE_INGEST_TOKEN', '')}"})
    urllib.request.urlopen(req, timeout=5).read()


def _run_worker() -> None:
    while True:
        batch = [_queue.get()]
        while not _queue.empty() and len(batch) < 100:
            batch.append(_queue.get_nowait())
        try:
            _post(batch)
        except Exception as e:
            log.warning("governance console unreachable (%s); spooling %d event(s)", e, len(batch))
            for ev in batch:
                try:
                    _append_spool(ev)
                except Exception:
                    pass
        finally:
            for _ in batch:
                _queue.task_done()


def _start_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run_worker, name="governance-events", daemon=True)
        _worker.start()
        atexit.register(flush)   # short-lived CLI commands still deliver their events


def flush(timeout: float = 5.0) -> None:
    """Wait for queued events to be delivered (end of a CLI command, tests)."""
    end = time.time() + timeout
    while _queue.unfinished_tasks and time.time() < end:
        time.sleep(0.05)


# ---------------------------------------------------------------- self-registration
def _controls(root: Path) -> list[dict]:
    p = root / "docs" / "governance.md"
    if not p.exists():
        return []
    rows = re.findall(r"(?m)^\|\s*([A-Z]+-\d+)\s+([^|]*?)\s*\|\s*(✅|🟡|⚪|🔷)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", p.read_text())
    return [{"id": i, "name": n.strip(), "status": s, "how": h.strip()[:400], "config": c.strip()[:200]}
            for i, n, s, h, c, _ in rows]


def _models(root: Path) -> list[dict]:
    import yaml

    p = root / "config" / "models.yaml"
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text())
    used: dict[str, list[str]] = {}
    for alias, name in (raw.get("aliases") or {}).items():
        used.setdefault(name, []).append(alias)
    return [{"name": n, "provider": m.get("provider"), "model_id": str(m.get("model_id")), "kind": m.get("kind", "chat"),
             "approved": bool(m.get("approved")), "priced": m.get("input_per_mtok") is not None,
             "deprecation_date": str(m["deprecation_date"]) if m.get("deprecation_date") else None,
             "aliases": used.get(n, [])} for n, m in (raw.get("models") or {}).items()]


def metadata(root: Path) -> dict:
    import yaml

    s = yaml.safe_load((root / "config" / "settings.yaml").read_text())
    links = json.loads((root / "portfolio_links.json").read_text()) if (root / "portfolio_links.json").exists() else {}
    return {"workflow": s.get("workflow", {}), "risk_tier": s.get("risk_tier", ""), "budgets": s.get("cost", {}),
            "models": _models(root),
            "controls": _controls(root), "links": links, "client_version": CLIENT_VERSION}


def register(root: Path) -> None:
    """Declare this workflow's metadata to the console (at most every 10 minutes per process)."""
    global _registered
    if not active() or time.time() - _registered < 600:
        return
    try:
        emit("register", actor="service:" + PROJECT, actor_type="service", detail=metadata(Path(root)))
        _registered = time.time()
    except Exception as e:
        log.warning("governance register failed: %s", e)


# ---------------------------------------------------------------- kill switch
def status(max_age_s: float = 15.0) -> Status:
    global _state_cache
    if not active() or not _url():
        return Status(True, "", source="default")
    if _state_cache[1] is not None and time.time() - _state_cache[0] < max_age_s:
        return _state_cache[1]
    try:
        with urllib.request.urlopen(f"{_url()}/api/workflows/{PROJECT}/status", timeout=3) as r:
            d = json.loads(r.read())
        reason = d.get("reason", "")
        if not d.get("enabled", True) and d.get("changed_by"):
            reason = f"{reason or 'no reason given'} (by {d['changed_by']}" + \
                     (f", until {d['expires_at'][11:16]} UTC)" if d.get("expires_at") else ")")
        s = Status(bool(d.get("enabled", True)), reason, d.get("changed_by", ""), "console")
    except Exception as e:
        closed = os.getenv("GOVERNANCE_FAIL_CLOSED") == "1"
        s = Status(not closed, f"governance console unreachable ({type(e).__name__}); "
                               f"failing {'closed' if closed else 'open'}", source="unreachable")
    _state_cache = (time.time(), s)
    return s


def require_enabled(action: str = "run", actor: str = "") -> Status:
    """Call before any model call. Raises WorkflowDisabled (and logs the blocked attempt) when switched off."""
    s = status()
    if not s.enabled:
        emit(action, status="blocked", actor=actor or None, flags=["kill_switch"], detail={"reason": s.reason})
        raise WorkflowDisabled(f"{PROJECT} is switched off by governance: {s.reason or 'no reason given'}")
    return s


check = require_enabled


# ---------------------------------------------------------------- Streamlit helper
def start_streamlit_session(st, root: Path | None = None, actor: str | None = None) -> Status:
    """Identify the session, record one visit, register the workflow, and show the kill-switch state."""
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    ctx = get_script_run_ctx()
    sid = ctx.session_id if ctx else "anon"
    set_session(sid)
    if actor:
        set_actor(actor, _actor_type(actor))
    elif environment() == "demo":
        set_actor(visitor_id(sid), "visitor")   # anonymous public visitor; SSO identity in production
    if root is not None:
        register(root)
    if not st.session_state.get("_governance_visit"):
        st.session_state["_governance_visit"] = True
        emit("visit")
    s = status()
    if not s.enabled:
        st.error(f"⛔ **Switched off by governance** — {s.reason or 'no reason given'}. Runs are blocked until the "
                 "workflow is re-enabled in the governance console.")
    elif s.source == "unreachable":
        st.caption(f"⚠️ {s.reason}")
    return s
