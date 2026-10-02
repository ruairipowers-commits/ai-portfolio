"""FastAPI app: the dashboards, the event-ingest API the workflows call, and the kill switch.

Public:  GET pages, GET /api/summary, GET /api/workflows/{slug}/status (apps poll this), GET /api/health
Apps:    POST /api/events            Bearer GOVERNANCE_INGEST_TOKEN when set (always set on a hosted console)
Admin:   POST /workflows/{slug}/toggle   needs the admin cookie, set by /admin/login with GOVERNANCE_ADMIN_TOKEN.
         With no admin token configured, admin is open only when running locally (never in the hosted demo).
         POST /settings/escalation/{slug}  who gets emailed, auto-shutdown level, which rules (admin only)
Incidents: governance issues found in incoming events (escalation.py) open INC-nnnn, may switch the workflow off and
         email its recipients with a link to /incidents/{id}, where they're investigated, documented and resolved.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from pydantic import BaseModel, Field, ValidationError

from . import catalog as cat
from . import metrics as M
from . import escalation, links, notify, simulate, spool
from .store import Store, now_iso

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
SETTINGS = M.load_settings()
# Serving under a path prefix (e.g. https://demos.example.com/governance-console behind a reverse proxy that strips it):
# set ROOT_PATH=/governance-console. Every link, redirect and fetch is built from this.
BASE = os.getenv("ROOT_PATH", "").rstrip("/")


# ---------------------------------------------------------------- ingest schema
class Event(BaseModel):
    event_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    ts: str = Field(max_length=40)
    workflow: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    event_type: str = Field(max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    status: str = Field("ok", max_length=24)
    actor: str = Field("", max_length=120)
    actor_type: str = Field("named", pattern=r"^(named|visitor|service)$")
    session_id: str = Field("", max_length=80)
    environment: str = Field("", max_length=20)
    app_version: str = Field("", max_length=20)
    run_id: str = Field("", max_length=64)
    model: str = Field("", max_length=80)
    input_tokens: int = Field(0, ge=0, le=50_000_000)
    output_tokens: int = Field(0, ge=0, le=50_000_000)
    cost_usd: float = Field(0.0, ge=0, le=10_000)
    latency_ms: int = Field(0, ge=0, le=86_400_000)
    records_in: int = Field(0, ge=0)
    records_out: int = Field(0, ge=0)
    flags: list[str] = Field(default_factory=list, max_length=20)
    detail: dict = Field(default_factory=dict)


class StripPrefix:
    """Accept requests with or without the ROOT_PATH prefix, so any proxy works whether or not it strips it."""

    def __init__(self, app, prefix: str):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = {**scope, "path": path[len(self.prefix):] or "/", "raw_path": None}
        await self.app(scope, receive, send)


class State:
    store: Store
    catalog: dict = {}
    catalog_at: float = 0.0
    hits: dict = defaultdict(deque)
    console_url: str = ""          # public URL of this console, for links in emails (learned from requests)


S = State()


def get_catalog() -> dict:
    if time.time() - S.catalog_at > 30:          # picks up new projects without a restart
        S.catalog, S.catalog_at = cat.load(), time.time()
    return S.catalog


def create_app(store: Store | None = None, seed: bool = True) -> FastAPI:
    S.store = store or Store()
    S.catalog_at = 0
    app = FastAPI(title="AI governance console", docs_url="/api/docs", redoc_url=None)
    if BASE:
        app.add_middleware(StripPrefix, prefix=BASE)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    if seed and simulate.needs_seed(S.store):
        simulate.seed(S.store, [w["slug"] for w in get_catalog()["workflows"]], SETTINGS["simulation"]["days"],
                      SETTINGS["simulation"]["seed"], get_catalog())
    _routes(app)
    if os.getenv("GOVERNANCE_ESCALATION_CHECK", "1") != "0":
        escalation.start_checker(lambda: S.store, get_catalog, lambda: S.console_url or console_url(None))
    return app


def console_url(request: Request | None) -> str:
    """Where people reach this console — for the links in alert emails. GOVERNANCE_PUBLIC_URL wins; the portfolio's
    deploy scripts set PORTFOLIO_DEMO_URL; otherwise the URL the request came in on (proxy headers honoured)."""
    url = os.getenv("GOVERNANCE_PUBLIC_URL") or os.getenv("PORTFOLIO_DEMO_URL") or ""
    if not url and request is not None:
        url = str(request.base_url).rstrip("/") + BASE
    return (url or "http://localhost:8600").rstrip("/")


# ---------------------------------------------------------------- auth helpers
def demo_mode() -> bool:
    return os.getenv("PORTFOLIO_DEMO") == "1"


def admin_token() -> str:
    return os.getenv("GOVERNANCE_ADMIN_TOKEN", "")


def _digest(token: str) -> str:
    return hashlib.sha256(("govconsole:" + token).encode()).hexdigest()


def is_admin(request: Request) -> bool:
    tok = admin_token()
    if not tok:
        return not demo_mode()     # local development only
    return hmac.compare_digest(request.cookies.get("gov_admin", ""), _digest(tok))


def switch_rights(request: Request) -> str:
    """'admin' (any change), 'temporary' (public demo: switch off for a few minutes, or switch back on), or ''."""
    if is_admin(request):
        return "admin"
    return "temporary" if demo_mode() else ""


def can_attest(request: Request) -> bool:
    return is_admin(request) or demo_mode()


def admin_name(request: Request) -> str:
    return request.cookies.get("gov_admin_name") or ("local-admin" if not admin_token() else "admin")


def _check_ingest(request: Request) -> None:
    tok = os.getenv("GOVERNANCE_INGEST_TOKEN", "")
    need = SETTINGS["ingest"]["require_token"]
    if (need is True or (need == "auto" and tok)) and not hmac.compare_digest(
            request.headers.get("Authorization", ""), f"Bearer {tok}"):
        raise HTTPException(401, "invalid ingest token")
    ip = request.client.host if request.client else "?"
    q, now = S.hits[ip], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= SETTINGS["ingest"]["rate_limit_per_minute"]:
        raise HTTPException(429, "rate limit")
    q.append(now)


def _flt(request: Request) -> dict:
    qp = request.query_params
    days = int(qp.get("days", 30)) if qp.get("days", "30").isdigit() else 30
    sim = "sim" not in qp or "1" in qp.getlist("sim")
    return {"days": max(1, min(days, 365)), "sim": sim, "wf": qp.get("wf") or None,
            "env": qp.get("env") or None}


def _ctx(request: Request, **kw) -> dict:
    f = _flt(request)
    c = get_catalog()
    return {"request": request, "f": f, "base": BASE, "admin": is_admin(request), "demo": demo_mode(), "rights": switch_rights(request),
            "can_attest": can_attest(request), "settings": SETTINGS, "links": links.console(),
            "wf_links": {w["slug"]: links.for_slug(w["slug"]) for w in c["workflows"]},
            "order": [w["slug"] for w in c["workflows"]], "names": {w["slug"]: w["name"] for w in c["workflows"]},
            "admin_configured": bool(admin_token()), "catalog": get_catalog(), "now": now_iso(),
            "open_incidents": S.store.incidents("open", include_simulated=f["sim"]), **kw}


# ---------------------------------------------------------------- routes
def _routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health():
        n = S.store.query("select count(*) as n from events")[0]["n"]
        return {"ok": True, "events": n, "workflows": len(get_catalog()["workflows"])}

    @app.post("/api/events", status_code=202)
    async def ingest(request: Request):
        _check_ingest(request)
        body = await request.body()
        if len(body) > SETTINGS["ingest"]["max_body_bytes"]:
            raise HTTPException(413, "payload too large")
        try:
            raw = json.loads(body)
            raw = raw if isinstance(raw, list) else [raw]
            if len(raw) > SETTINGS["ingest"]["max_events_per_request"]:
                raise HTTPException(413, "too many events")
            events = [Event(**e).model_dump() for e in raw]
        except (ValueError, ValidationError, TypeError) as e:
            raise HTTPException(422, f"invalid events: {str(e)[:300]}")
        for e in events:
            e["source"] = "live"
            if e["event_type"] == "register":     # self-declared metadata: latest wins, kept out of the event detail
                S.store.upsert_meta(e["workflow"], e["detail"], e["environment"], e["ts"])
                e["detail"] = {"registered": True}
            e["detail"] = {k: v for k, v in list(e["detail"].items())[:30]}
        ids = [e["event_id"] for e in events]
        seen = {r["event_id"] for r in S.store.query(
            f"select event_id from events where event_id in ({','.join('?' * len(ids))})", ids)} if ids else set()
        accepted = S.store.insert_events(events)
        S.console_url = console_url(request)
        try:   # a re-sent event (client retry) is not a new violation
            opened = escalation.on_events(S.store, get_catalog(), [e for e in events if e["event_id"] not in seen],
                                          S.console_url)
        except Exception as e:  # noqa: BLE001 — detection problems must never lose the events themselves
            opened = []
            print(f"escalation failed: {type(e).__name__}: {e}")
        return {"accepted": accepted, "received": len(events),
                "incidents": sorted({i["incident_id"] for i in opened})}

    @app.get("/api/workflows/{slug}/status")
    def wf_status(slug: str):
        st = S.store.effective_state().get(slug)
        if not st:
            return {"workflow": slug, "enabled": SETTINGS["kill_switch"]["default_enabled"], "reason": "", "changed_by": ""}
        return {"workflow": slug, "enabled": bool(st["enabled"]), "reason": st["reason"] or "",
                "changed_by": st["changed_by"] or "", "changed_at": st["changed_at"], "expires_at": st.get("expires_at")}

    @app.get("/api/workflows")
    def wf_list(request: Request):
        return M.workflow_table(S.store, get_catalog(), _flt(request)["sim"])

    @app.get("/api/summary")
    def api_summary(request: Request):
        _local_import()
        f = _flt(request)
        return M.summary(S.store, get_catalog(), f["days"], f["wf"], f["sim"], f["env"])

    @app.get("/api/events.csv")
    def events_csv(request: Request):
        f = _flt(request)
        qp = request.query_params
        rows = M.recent_events(S.store, f["wf"], 5000, f["sim"], qp.get("actor") or None, qp.get("status") or None,
                               qp.get("event_type") or None)
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["ts", "workflow", "event_type", "status", "actor", "actor_type", "model", "input_tokens",
                "output_tokens", "cost_usd", "latency_ms", "records_in", "records_out", "flags", "environment", "source"]
        w.writerow(cols)
        for r in rows:
            w.writerow([";".join(r[c]) if c == "flags" else r[c] for c in cols])
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=governance-events.csv"})

    # ------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        _local_import()
        f = _flt(request)
        rows = M.workflow_table(S.store, get_catalog(), f["sim"])
        return templates.TemplateResponse(request, "overview.html", _ctx(
            request, rows=rows, page="overview",
            events=M.recent_events(S.store, None, 12, f["sim"]), changes=_changes(5, None, f["sim"])))

    @app.get("/workflows/{slug}", response_class=HTMLResponse)
    def workflow_page(request: Request, slug: str):
        f = _flt(request)
        rows = {r["slug"]: r for r in M.workflow_table(S.store, get_catalog(), f["sim"])}
        if slug not in rows:
            raise HTTPException(404, f"unknown workflow {slug}")
        wf = next((w for w in get_catalog()["workflows"] if w["slug"] == slug), None)
        return templates.TemplateResponse(request, "workflow.html", _ctx(
            request, page="workflow", row=rows[slug], wf=wf, cfg=M.wf_config(slug),
            attestations=S.store.latest_attestations(f["sim"]),
            stale_before=(datetime.now(timezone.utc).date() - timedelta(days=SETTINGS["attestation"]["stale_after_days"])).isoformat(),
            evidence=M.control_evidence(S.store, slug, 30, f["sim"]),
            actors=M.actors(S.store, slug, f["days"], f["sim"], 25),
            events=M.recent_events(S.store, slug, 15, f["sim"]), changes=_changes(20, slug, f["sim"])))

    @app.get("/controls", response_class=HTMLResponse)
    def controls_page(request: Request):
        f = _flt(request)
        c = get_catalog()
        evidence = {w["slug"]: M.control_evidence(S.store, w["slug"], 30, f["sim"]) for w in c["workflows"]}
        return templates.TemplateResponse(request, "controls.html", _ctx(
            request, page="controls", evidence=evidence, attestations=S.store.latest_attestations(f["sim"]),
            stale_before=(datetime.now(timezone.utc).date() - timedelta(days=SETTINGS["attestation"]["stale_after_days"])).isoformat(), rows={r["slug"]: r for r in M.workflow_table(S.store, c, f["sim"])}))

    @app.get("/events", response_class=HTMLResponse)
    def events_page(request: Request):
        f, qp = _flt(request), request.query_params
        flt = {k: qp.get(k) or None for k in ("actor", "status", "event_type")}
        return templates.TemplateResponse(request, "events.html", _ctx(
            request, page="events", flt=flt, events=M.recent_events(S.store, f["wf"], 300, f["sim"], **flt),
            actors=M.actors(S.store, f["wf"], f["days"], f["sim"], 40)))

    @app.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request):
        f = _flt(request)
        return templates.TemplateResponse(request, "audit.html", _ctx(
            request, page="audit", changes=_changes(200, None, f["sim"]),
            unregistered=[r for r in M.workflow_table(S.store, get_catalog(), f["sim"]) if not r["registered"]],
            anomalies=M.detect_anomalies(S.store, 90, include_simulated=f["sim"])))

    # ------------------------------------------------------------ admin
    @app.get("/admin/login", response_class=HTMLResponse)
    def login_form(request: Request, error: str = ""):
        return templates.TemplateResponse(request, "login.html", _ctx(request, page="admin", error=error))

    @app.post("/admin/login")
    def login(request: Request, token: str = Form(...), name: str = Form("admin")):
        if not admin_token() or not hmac.compare_digest(token, admin_token()):
            return RedirectResponse(BASE + "/admin/login?error=1", status_code=303)
        r = RedirectResponse(BASE + "/", status_code=303)
        secure = request.url.scheme == "https"
        r.set_cookie("gov_admin", _digest(admin_token()), httponly=True, samesite="strict", secure=secure, max_age=8 * 3600)
        r.set_cookie("gov_admin_name", name[:60] or "admin", samesite="strict", secure=secure, max_age=8 * 3600)
        return r

    @app.post("/admin/logout")
    def logout():
        r = RedirectResponse(BASE + "/", status_code=303)
        r.delete_cookie("gov_admin"), r.delete_cookie("gov_admin_name")
        return r

    @app.post("/workflows/{slug}/toggle")
    def toggle(request: Request, slug: str, enabled: str = Form(...), reason: str = Form(""), name: str = Form("")):
        rights = switch_rights(request)
        if not rights:
            raise HTTPException(403, "admin sign-in required to change a kill switch")
        if slug not in {w["slug"] for w in get_catalog()["workflows"]}:
            raise HTTPException(404, "only registered workflows have a kill switch")
        reason = reason.strip()[:300]
        if SETTINGS["kill_switch"]["require_reason"] and not reason:
            raise HTTPException(422, "a reason is required")
        if rights == "admin":
            S.store.set_enabled(slug, enabled == "1", reason, admin_name(request))
        else:   # public demo: anyone can try it, but a switch-off lapses on its own
            who = (name.strip()[:60] or "anonymous") + " (demo visitor)"
            mins = SETTINGS["kill_switch"]["demo_expiry_minutes"]
            exp = (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat(timespec="seconds")
            S.store.set_enabled(slug, enabled == "1", reason, who, expires_at=None if enabled == "1" else exp)
        return RedirectResponse(f"{BASE}/workflows/{slug}", status_code=303)

    @app.post("/workflows/{slug}/attest")
    def attest(request: Request, slug: str, control_id: str = Form(...), verdict: str = Form(...),
               note: str = Form(""), name: str = Form("")):
        if not can_attest(request):
            raise HTTPException(403, "admin sign-in required to attest")
        wf = next((w for w in get_catalog()["workflows"] if w["slug"] == slug), None)
        if not wf or control_id not in wf["controls"] or verdict not in ("confirmed", "exception"):
            raise HTTPException(422, "unknown workflow, control or verdict")
        who = admin_name(request) if is_admin(request) else (name.strip()[:60] or "anonymous") + " (demo visitor)"
        if not is_admin(request) and not name.strip():
            raise HTTPException(422, "your name is required")
        S.store.attest(slug, control_id, verdict, who, note.strip()[:300])
        return RedirectResponse(f"{BASE}/workflows/{slug}#controls", status_code=303)

    # ------------------------------------------------------------ incidents
    @app.get("/incidents", response_class=HTMLResponse)
    def incidents_page(request: Request, status: str = "open"):
        f = _flt(request)
        status = status if status in ("open", "resolved", "all") else "open"
        return templates.TemplateResponse(request, "incidents.html", _ctx(
            request, page="incidents", status=status, rules=escalation.rules(),
            incidents=S.store.incidents(None if status == "all" else status, f["wf"], f["sim"])))

    @app.get("/incidents/{incident_id}", response_class=HTMLResponse)
    def incident_page(request: Request, incident_id: str):
        inc = S.store.incident(incident_id)
        if not inc:
            raise HTTPException(404, f"unknown incident {incident_id}")
        f = _flt(request)
        rows = {r["slug"]: r for r in M.workflow_table(S.store, get_catalog(), f["sim"])}
        others = [i for i in S.store.incidents("open", inc["workflow"]) if i["incident_id"] != incident_id]
        return templates.TemplateResponse(request, "incident.html", _ctx(
            request, page="incidents", inc=inc, rule=escalation.rules().get(inc["rule_id"], {}),
            row=rows.get(inc["workflow"]), log=S.store.incident_log(incident_id), others=others,
            mails=S.store.notifications(incident_id), wf_link=links.for_slug(inc["workflow"]),
            tickets={c: notify.ticket_payload(c, inc, rows.get(inc["workflow"], {}).get("name", inc["workflow"]),
                                              f"{console_url(request)}/incidents/{incident_id}")
                     for c in ("pagerduty", "servicenow")}))

    @app.post("/incidents/{incident_id}/note")
    def incident_note(request: Request, incident_id: str, kind: str = Form(...), text: str = Form(...),
                      name: str = Form("")):
        who = _who(request, name)
        if kind not in ("investigation", "root_cause", "fix", "documentation") or not text.strip():
            raise HTTPException(422, "kind and text are required")
        if not S.store.incident(incident_id):
            raise HTTPException(404, "unknown incident")
        S.store.log_incident(incident_id, kind, who, text.strip()[:2000])
        if kind == "investigation":
            S.store.update_incident(incident_id, status="investigating")
        return RedirectResponse(f"{BASE}/incidents/{incident_id}#timeline", status_code=303)

    @app.post("/incidents/{incident_id}/resolve")
    def incident_resolve(request: Request, incident_id: str, root_cause: str = Form(...), fix: str = Form(...),
                         documentation: str = Form(...), reenable: str = Form(""), attest: str = Form(""),
                         name: str = Form("")):
        who = _who(request, name)
        if not (root_cause.strip() and fix.strip() and documentation.strip()):
            raise HTTPException(422, "root cause, fix and documentation are all required to resolve")
        try:
            escalation.resolve(S.store, incident_id, who, root_cause.strip()[:1000], fix.strip()[:1000],
                               documentation.strip()[:1000], reenable == "1", attest == "1")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return RedirectResponse(f"{BASE}/incidents/{incident_id}", status_code=303)

    # ------------------------------------------------------------ settings + outbox
    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: str = ""):
        stored = S.store.escalation_settings()
        wfs = get_catalog()["workflows"]
        return templates.TemplateResponse(request, "settings.html", _ctx(
            request, page="settings", saved=saved, esc=escalation.CFG, rules=escalation.rules(),
            per_wf={w["slug"]: {**escalation.settings_for(S.store, w["slug"], stored), "_stored": stored.get(w["slug"])}
                    for w in wfs},
            smtp=notify.smtp_summary(), smtp_ok=notify.smtp_configured(),
            env_recipients=_mask(notify.default_recipients(), request)))

    @app.post("/settings/escalation/{slug}")
    async def settings_save(request: Request, slug: str):
        if not is_admin(request):
            raise HTTPException(403, "admin sign-in required to change escalation settings")
        if slug not in {w["slug"] for w in get_catalog()["workflows"]}:
            raise HTTPException(404, "unknown workflow")
        form = await request.form()
        sev = escalation.SEVERITIES
        recips = [a.strip() for a in str(form.get("recipients", "")).replace(";", ",").split(",") if a.strip()]
        bad = [a for a in recips if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a)]
        if bad:
            raise HTTPException(422, f"not an email address: {', '.join(bad)}")
        chosen = [r for r in form.getlist("rules") if r in escalation.rules()]
        new = {"alerts_enabled": form.get("alerts_enabled") == "1", "recipients": recips[:10],
               "auto_shutdown_at": form.get("auto_shutdown_at") if form.get("auto_shutdown_at") in [*sev, "never"] else "high",
               "notify_at": form.get("notify_at") if form.get("notify_at") in sev else "medium",
               "rules": "all" if set(chosen) == set(escalation.rules()) else chosen}
        S.store.save_escalation_settings(slug, new, admin_name(request))
        return RedirectResponse(f"{BASE}/settings?saved={slug}#wf-{slug}", status_code=303)

    @app.post("/settings/test-email")
    def settings_test_email(request: Request):
        if not is_admin(request):
            raise HTTPException(403, "admin sign-in required")
        recips = notify.default_recipients() or [os.getenv("SMTP_USER", "")]
        text = f"This is a test from the AI governance console at {console_url(request)}. Alerts will look like this."
        html = f"<p style='font-family:sans-serif'>{escape(text)}</p>"
        nid = S.store.add_notification({"incident_id": None, "channel": "email", "recipients": recips,
                                        "subject": "Test: AI governance console alerts", "body_text": text,
                                        "body_html": html, "status": "queued" if notify.smtp_configured() else "outbox-only"})
        if notify.smtp_configured():
            notify.deliver(S.store, nid, recips, {"subject": "Test: AI governance console alerts", "text": text,
                                                  "html": html}, background=False)
        return RedirectResponse(f"{BASE}/outbox", status_code=303)

    @app.get("/outbox", response_class=HTMLResponse)
    def outbox_page(request: Request):
        f = _flt(request)
        mails = [{**m, "recipients": ", ".join(_mask(m["recipients"].split(", "), request)) if m["recipients"] else ""}
                 for m in S.store.notifications(None, 200, f["sim"])]
        return templates.TemplateResponse(request, "outbox.html", _ctx(request, page="settings", mails=mails,
                                                                        smtp=notify.smtp_summary()))

    @app.get("/outbox/{nid}", response_class=HTMLResponse)
    def outbox_message(nid: str):
        m = S.store.notification(nid)
        if not m:
            raise HTTPException(404, "unknown message")
        return HTMLResponse(m["body_html"] or f"<pre>{escape(m['body_text'] or '')}</pre>")

    @app.get("/models", response_class=HTMLResponse)
    def models_page(request: Request):
        f = _flt(request)
        usage = {(r["workflow"], r["model"]): r for r in S.store.query(
            """select workflow, model, count(*) as calls, sum(cost_usd) as cost, max(ts) as last_used from events
               where model <> '' and day >= ? """ + ("" if f["sim"] else "and source = 'live' ") + "group by workflow, model",
            ((datetime.now(timezone.utc) - timedelta(days=f["days"] - 1)).date().isoformat(),))}
        return templates.TemplateResponse(request, "models.html", _ctx(
            request, page="models", usage=usage, today=datetime.now(timezone.utc).date().isoformat(),
            warn_by=(datetime.now(timezone.utc) + timedelta(days=90)).date().isoformat(), declared=S.store.workflow_meta()))


def _who(request: Request, name: str) -> str:
    """Who is writing to an incident: the admin, or (public demo) a named visitor."""
    if is_admin(request):
        return admin_name(request)
    if not demo_mode():
        raise HTTPException(403, "admin sign-in required")
    if not name.strip():
        raise HTTPException(422, "your name is required")
    return name.strip()[:60] + " (demo visitor)"


def _mask(addresses: list[str], request: Request) -> list[str]:
    """Public demo: show that alerts go somewhere without publishing the address."""
    if is_admin(request) or not demo_mode():
        return addresses
    return [a[0] + "•••@" + a.split("@", 1)[1] if "@" in a else "•••" for a in addresses]


def _local_import() -> None:
    """Running locally, pick up events apps wrote to the spool file since the last page load."""
    if not demo_mode():
        try:
            spool.import_spool(S.store)
        except OSError:
            pass


def _changes(limit: int, slug: str | None = None, include_simulated: bool = True) -> list[dict]:
    where = [w for w, on in (("workflow = ?", bool(slug)), ("source = 'live'", not include_simulated)) if on]
    sql = "select * from control_changes" + (" where " + " and ".join(where) if where else "") + \
        f" order by ts desc limit {int(limit)}"
    return S.store.query(sql, (slug,) if slug else ())


def fmt_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return ts or "—"


def md_inline(text: str) -> Markup:
    """The governance mapping is Markdown; render `code` and **bold** safely (everything else stays escaped)."""
    s = str(escape(text or ""))
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return Markup(s)


def inc_links(text: str) -> Markup:
    """Turn incident IDs in a kill-switch reason into links to the incident."""
    return Markup(re.sub(r"\b(INC-\d{4,})\b", lambda m: f'<a href="{BASE}/incidents/{m.group(1)}">{m.group(1)}</a>',
                         str(escape(text or ""))))


templates.env.filters["md"] = md_inline
templates.env.filters["inc"] = inc_links
templates.env.filters["ts"] = fmt_ts
templates.env.filters["usd"] = lambda v: (f"${float(v):,.4f}" if 0 < float(v or 0) < 0.01 else f"${float(v or 0):,.2f}")
templates.env.filters["num"] = lambda v: f"{int(v or 0):,}"
templates.env.filters["pct"] = lambda v: f"{100 * float(v or 0):.1f}%"
