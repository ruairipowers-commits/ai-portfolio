"""FastAPI service: search and chat over the blog, plus the visit/search log behind the daily engagement email.

Public (called from the blog, CORS-limited to the site's origin):
  GET  /api/search?q=…&via=…    ranked passages with snippets and links; logged as a search unless via=ask (the
                                pages shown beside an answer are part of that ask, not a separate search)
  POST /api/chat                {question, history, page} → NDJSON stream: sources, text deltas, done (logged)
  POST /api/rolematch           {role, description, contact?} → NDJSON stream like chat: a cited fit read. The role
                                text and the read are saved for the owner (role_reads) and listed in the daily email
  POST /api/track               {kind: pageview | site-search, path, title, referrer, q} (sendBeacon; logged)
  POST /api/suggest             {idea, name?, contact?} → a project suggestion (pending until approved; daily email)
  GET  /api/suggestions         published suggestions with votes;  POST /api/suggestions/{id}/vote  one per day
  POST /api/like {path}         thumbs up on a post;  GET /api/likes?paths=a,b  counts
  POST /api/unhelpful {path, note?}  thumbs down, with an optional "what was missing" (never published)
  POST /api/subscribe {email, roles?}  new posts by email, optionally only posts for some roles: double opt-in
                                (subscribers.py); GET /subscribe/confirm?t=…; GET|POST /subscribe/roles?t=… change roles
  GET|POST /unsubscribe?t=…     one click (RFC 8058), deletes the address
  GET  /widget.js, /widget.css  the Ask button and panel the blog loads
  GET  /                        a standalone "Ask the portfolio" page
Owner (ASSISTANT_ADMIN_TOKEN, or GOVERNANCE_ADMIN_TOKEN):
  GET  /stats?token=…           the last 14 days, top searches and questions, role matches, digest history
  POST /digest/send?token=…     build and email the engagement summary now
  GET  /admin/content           top-rated posts and every suggestion (the governance console's Content tab)
  POST /admin/suggestions/{id}  {status: pending | published | hidden | done, actor}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import digest, index, llm, subscribers, telemetry
from .digest import kickoff_links
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = os.getenv("ROOT_PATH", "").rstrip("/")


def load_settings() -> dict:
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())


SETTINGS = load_settings()


def site_url() -> str:
    return (os.getenv("PORTFOLIO_SITE_URL") or os.getenv("SITE_URL") or "http://localhost:8000").rstrip("/")


def index_source() -> str:
    return os.getenv("SITE_INDEX") or SETTINGS["index"]["source"] or f"{site_url()}/search/search_index.json"


class StripPrefix:
    """Accept requests with or without the ROOT_PATH prefix (same as the governance console)."""

    def __init__(self, app, prefix: str):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = {**scope, "path": path[len(self.prefix):] or "/", "raw_path": None}
        await self.app(scope, receive, send)


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=12)
    page: str = Field("", max_length=300)


class SuggestIn(BaseModel):
    idea: str = Field(min_length=10, max_length=1500)
    name: str = Field("", max_length=80)
    contact: str = Field("", max_length=120)        # optional: how to reply (email or LinkedIn), only ever emailed to Ruairi
    page: str = Field("", max_length=300)
    website: str = Field("", max_length=200)        # honeypot: hidden in the form; bots fill it in


class LikeIn(BaseModel):
    path: str = Field(min_length=1, max_length=300)


class UnhelpfulIn(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    note: str = Field("", max_length=500)


class SubscribeIn(BaseModel):
    email: str = Field("", max_length=254)
    roles: list[str] = Field(default_factory=list, max_length=20)    # empty: every post
    website: str = Field("", max_length=200)          # honeypot: people leave it empty, bots fill it in


class RoleIn(BaseModel):
    role: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=40, max_length=8000)
    contact: str = Field("", max_length=160)          # optional: how Ruairi can reply; only ever emailed to him
    page: str = Field("", max_length=300)
    website: str = Field("", max_length=200)          # honeypot


class StatusIn(BaseModel):
    status: str = Field(max_length=20)
    actor: str = Field("", max_length=80)


class State:
    store: Store
    salt: tuple[str, str] = ("", "")


S = State()


# ---------------------------------------------------------------- helpers
def visitor(request: Request) -> str:
    """Anonymous, daily-rotating visitor key: hash(salt of the day + IP + browser). The IP is never stored."""
    day = datetime.now(timezone.utc).date().isoformat()
    if S.salt[0] != day:
        S.salt = (day, os.getenv("ASSISTANT_SALT", "") + secrets.token_hex(16))
    ip = (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else ""))
    ua = request.headers.get("user-agent", "")[:200]
    return hashlib.sha256(f"{S.salt[1]}|{ip}|{ua}".encode()).hexdigest()[:16]


def limit(kind: str, who: str, per_hour: int) -> None:
    if S.store.count_since(kind, who, 60) >= per_hour:
        raise HTTPException(429, "Too many requests — please try again in a few minutes.")


def admin_ok(request: Request) -> bool:
    tok = os.getenv("ASSISTANT_ADMIN_TOKEN") or os.getenv("GOVERNANCE_ADMIN_TOKEN") or ""
    given = request.query_params.get("token") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if not tok:
        return os.getenv("PORTFOLIO_DEMO") != "1"      # local development only
    return hmac.compare_digest(given, tok)


def page_path(url: str) -> str:
    p = urlparse(url or "")
    return (p.path or "/")[:300] if p.scheme else (url or "")[:300]


def post_key(path: str) -> str:
    """A post's page path or URL → its key in the site's page list ("blog/eod-heartbeat/")."""
    p = urlparse(path).path if "://" in path else path
    base = urlparse(site_url()).path.rstrip("/")            # e.g. /ai-portfolio on GitHub Pages
    if base and p.startswith(base + "/"):
        p = p[len(base):]
    p = p.strip("/")
    return (p + "/") if p else ""


def allowed_origins() -> list[str]:
    o = urlparse(site_url())
    extra = [x.strip() for x in os.getenv("ASSISTANT_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    return [f"{o.scheme}://{o.netloc}", "http://localhost:8000", "http://127.0.0.1:8000", *extra]


# ---------------------------------------------------------------- background jobs
def corpus_source() -> str | None:
    return os.getenv("ASSISTANT_CORPUS") or SETTINGS["index"].get("corpus") or None


def _refresher() -> None:
    warmed = None
    while True:
        try:
            index.refresh(S.store, index_source(), site_url(), SETTINGS["index"]["min_words"], corpus_source())
        except Exception as e:  # noqa: BLE001
            print(f"index refresh failed: {e}")
        card = index.profile_passage(S.store, site_url())
        key = (card or {}).get("text", "") + llm.model_config(SETTINGS["chat"]["model_alias"])["model"]
        if key != warmed and llm.ollama_ready(llm.model_config(SETTINGS["chat"]["model_alias"])["model"]):
            llm.warm_up(SETTINGS, [card] if card else [])     # load the model and cache the prompt prefix
            warmed = key
        S.store.purge(SETTINGS["privacy"]["retention_days"])
        try:                                     # announce posts that went live since the last refresh
            subscribers.notify(S.store, S.store.get_kv("pages", {}) or {}, site_url(),
                               SETTINGS["subscriptions"]["max_posts_per_run"])
            subscribers.purge_pending(S.store, SETTINGS["subscriptions"]["pending_days"])
        except Exception as e:  # noqa: BLE001
            print(f"subscriber emails failed: {type(e).__name__}: {e}")
        time.sleep(60 * (SETTINGS["index"]["refresh_minutes"] if warmed else 5))   # retry sooner while the model downloads


def _migrate_old_suggestions(store: Store) -> None:
    """Suggestions sent before they had their own table were kept in the activity log: move them over once."""
    if store.query("select 1 from suggestions limit 1"):
        return
    for r in store.query("select visitor, page, query, answer, ts from activity where kind = 'suggestion' and answer "
                         "is not null and answer like '{%' order by ts"):
        who = json.loads(r["answer"] or "{}")
        sid = store.add_suggestion(r["query"], who.get("name", ""), who.get("contact", ""), r["visitor"], r["page"],
                                   "pending")
        store.execute("update suggestions set ts = ?, day = ? where id = ?", (r["ts"], r["ts"][:10], sid))


def create_app(store: Store | None = None, background: bool = True) -> FastAPI:
    S.store = store or Store()
    subscribers.init(S.store)
    _migrate_old_suggestions(S.store)
    app = FastAPI(title="Site assistant", docs_url="/api/docs", redoc_url=None)
    if BASE:
        app.add_middleware(StripPrefix, prefix=BASE)
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], max_age=3600)
    if background:
        threading.Thread(target=_refresher, daemon=True, name="index-refresh").start()
        llm.pull_in_background(llm.model_config(SETTINGS["chat"]["model_alias"])["model"])
        digest.start_scheduler(lambda: S.store, SETTINGS)
        telemetry.register(ROOT)
    _routes(app)
    return app


# ---------------------------------------------------------------- routes
def _routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health():
        m = llm.model_config(SETTINGS["chat"]["model_alias"])
        return {"ok": True, "passages": S.store.passage_count(), "index": S.store.last_index(),
                "model": m["model"], "model_ready": llm.ollama_ready(m["model"]) if m["provider"] == "ollama" else False,
                "enabled": telemetry.status().enabled}

    @app.get("/api/search")
    def api_search(request: Request, q: str = "", page: str = "", via: str = "search"):
        q = q.strip()[: SETTINGS["search"]["max_query_chars"]]
        if len(q) < 2:
            return {"query": q, "results": []}
        who = visitor(request)
        lookup = via == "ask"          # the pages listed under an answer: the ask is logged, this isn't a search
        limit("lookup" if lookup else "search", who, SETTINGS["limits"]["searches_per_hour"])
        t0 = time.perf_counter()
        rows = index.search(S.store, q, SETTINGS["search"]["max_results"], site_url(), site_first=not lookup)
        S.store.log("lookup" if lookup else "search", who, page_path(page), q, len(rows),
                    "ok" if rows else "no_results", latency_ms=llm.time_ms(t0))
        telemetry.emit("search", actor=f"visitor-{who[:8]}", actor_type="visitor", records_in=S.store.passage_count(),
                       records_out=len(rows), latency_ms=llm.time_ms(t0), status="ok" if rows else "no_results",
                       detail={"query_chars": len(q), "query_sha": telemetry.sha(q)})
        return {"query": q, "results": [{"title": r["page_title"], "section": r["section"], "url": r["url"],
                                         "snippet": r["snippet"]} for r in rows]}

    @app.post("/api/chat")
    def api_chat(body: ChatIn, request: Request):
        who = visitor(request)
        q = body.question.strip()[: SETTINGS["chat"]["max_question_chars"]]
        st = telemetry.status()
        if not st.enabled:      # kill switch from the governance console — search keeps working
            telemetry.emit("ask", status="blocked", actor=f"visitor-{who[:8]}", actor_type="visitor",
                           flags=["kill_switch"], detail={"reason": st.reason})
            S.store.log("ask", who, page_path(body.page), q, 0, "blocked")
            raise HTTPException(503, f"The assistant is switched off by governance: {st.reason or 'no reason given'}. "
                                     "Search still works.")
        limit("ask", who, SETTINGS["limits"]["chats_per_hour"])
        if S.store.count_since("ask", None, 24 * 60) >= SETTINGS["limits"]["chats_per_day_total"] or \
                S.store.tokens_today() >= SETTINGS["cost"]["daily_budget_tokens"]:
            S.store.log("ask", who, page_path(body.page), q, 0, "budget")
            telemetry.emit("ask", status="blocked", actor=f"visitor-{who[:8]}", actor_type="visitor",
                           flags=["budget_blocked"])
            raise HTTPException(429, "The assistant has answered its daily allowance — search still works.")
        flags = ["injection_suspected"] if llm.INJECTION.search(q) else []
        passages = index.context_for(S.store, q, site_url(), SETTINGS["chat"]["top_k"])
        history = body.history[-2 * SETTINGS["chat"]["history_turns"]:]

        def stream():
            t0 = time.perf_counter()
            yield json.dumps({"type": "sources", "sources": [
                {"n": i, "title": p["page_title"], "section": p["section"], "url": p["url"]}
                for i, p in enumerate(passages, 1)]}) + "\n"
            meta, text = {}, []
            for piece in llm.answer(q, passages, history, SETTINGS):
                if isinstance(piece, dict):
                    meta = piece
                else:
                    text.append(piece)
                    yield json.dumps({"type": "delta", "text": piece}) + "\n"
            ms = llm.time_ms(t0)
            status = meta.get("status", "ok")
            S.store.log("ask", who, page_path(body.page), q, len(passages), status, meta.get("model", ""),
                        meta.get("input_tokens", 0), meta.get("output_tokens", 0), ms, flags=flags,
                        answer="".join(text))
            rate = SETTINGS["cost"]["usd_per_1k_tokens"]
            telemetry.emit("ask", actor=f"visitor-{who[:8]}", actor_type="visitor", model=meta.get("model", ""),
                           input_tokens=meta.get("input_tokens", 0), output_tokens=meta.get("output_tokens", 0),
                           cost_usd=rate * (meta.get("input_tokens", 0) + meta.get("output_tokens", 0)) / 1000,
                           latency_ms=ms, records_in=len(passages), records_out=1, status=status,
                           flags=flags + (["no_evidence"] if not passages else []),
                           detail={"question_chars": len(q), "question_sha": telemetry.sha(q),
                                   "answer_chars": len("".join(text))})
            yield json.dumps({"type": "done", "model": meta.get("model", ""), "status": status, "ms": ms}) + "\n"
        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/api/rolematch")
    def api_rolematch(body: RoleIn, request: Request):
        """A hiring manager pastes a role; they get a cited fit read to download, and the owner gets a copy."""
        who = visitor(request)
        rm = SETTINGS.get("role_match", {})
        role, desc = " ".join(body.role.split())[:120], body.description.strip()[: rm.get("max_chars", 8000)]
        if body.website.strip():                       # a bot: accept quietly, keep nothing
            raise HTTPException(422, "Please try again.")
        st = telemetry.status()
        if not st.enabled:
            S.store.log("role-match", who, page_path(body.page), role, 0, "blocked")
            raise HTTPException(503, f"The assistant is switched off by governance: {st.reason or 'no reason given'}.")
        limit("role-match", who, rm.get("per_hour", 4))
        if S.store.count_since("role-match", None, 24 * 60) >= rm.get("per_day_total", 60) or \
                S.store.tokens_today() >= SETTINGS["cost"]["daily_budget_tokens"]:
            S.store.log("role-match", who, page_path(body.page), role, 0, "budget")
            raise HTTPException(429, "Role matching has reached its daily allowance. Please try again tomorrow, or "
                                     "use Ask.")
        flags = ["injection_suspected"] if llm.INJECTION.search(role + "\n" + desc) else []
        passages = index.role_context(S.store, role, desc, site_url(), rm.get("top_k", 8))
        sources = [{"n": i, "title": p["page_title"], "section": p["section"], "url": p["url"]}
                   for i, p in enumerate(passages, 1)]
        key = secrets.token_urlsafe(18)       # lets this browser fetch its read again if the visitor navigates away
        rid = S.store.add_role_read(who, page_path(body.page), role, desc, " ".join(body.contact.split()), key, sources)

        def stream():
            t0 = time.perf_counter()
            yield json.dumps({"type": "sources", "id": rid, "key": key, "sources": sources}) + "\n"
            meta, text = {}, []
            for piece in llm.role_read(role, desc, passages, SETTINGS):
                if isinstance(piece, dict):
                    meta = piece
                else:
                    text.append(piece)
                    yield json.dumps({"type": "delta", "text": piece}) + "\n"
            ms, status, read = llm.time_ms(t0), meta.get("status", "ok"), "".join(text)
            tin, tout = meta.get("input_tokens", 0), meta.get("output_tokens", 0)
            S.store.finish_role_read(rid, read, meta.get("model", ""), status, tin, tout, ms, flags)
            S.store.log("role-match", who, page_path(body.page), role, len(passages), status, meta.get("model", ""),
                        tin, tout, ms, flags=flags)
            telemetry.emit("role_match", actor=f"visitor-{who[:8]}", actor_type="visitor", model=meta.get("model", ""),
                           input_tokens=tin, output_tokens=tout, latency_ms=ms, records_in=len(passages), records_out=1,
                           status=status, flags=flags, detail={"role_sha": telemetry.sha(role), "chars": len(desc),
                                                               "has_contact": bool(body.contact.strip())})
            if rm.get("notify_owner", True):
                try:
                    digest.role_match_alert(S.store, rid, site_url())
                except Exception as e:  # noqa: BLE001 — the visitor already has their read
                    print(f"role-match alert failed: {type(e).__name__}")
            yield json.dumps({"type": "done", "id": rid, "model": meta.get("model", ""), "status": status,
                              "ms": ms}) + "\n"
        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.get("/api/rolematch/{rid}")
    def api_rolematch_get(rid: int, key: str = ""):
        """The visitor's own read again (they left the page mid-answer): needs the key their browser was given."""
        row = (S.store.query("select role, read, status, access_key, sources from role_reads where id = ?", (rid,))
               or [None])[0]
        if not row or not key or not hmac.compare_digest(row["access_key"] or "", key):
            raise HTTPException(404, "not found")
        return {"id": rid, "role": row["role"], "read": row["read"] or "", "status": row["status"],
                "sources": json.loads(row["sources"] or "[]")}

    @app.post("/api/suggest", status_code=201)
    def api_suggest(body: SuggestIn, request: Request):
        """Suggest a project for Ruairi to try. New ideas wait for approval in the governance console (unless
        suggestions.auto_publish), then appear on the Suggestions page for upvotes. All are in the daily email."""
        who = visitor(request)
        lim = SETTINGS.get("suggestions", {})
        if body.website.strip():                       # a bot: accept quietly, keep nothing
            return {"ok": True, "status": "pending"}
        limit("suggestion", who, lim.get("per_hour", 5))
        if S.store.count_since("suggestion", None, 24 * 60) >= lim.get("per_day_total", 100):
            raise HTTPException(429, "The suggestion box is full for today — please try again tomorrow.")
        idea = " ".join(body.idea.split())
        status = "published" if lim.get("auto_publish") else "pending"
        sid = S.store.add_suggestion(idea, body.name.strip(), body.contact.strip(), who, page_path(body.page), status)
        S.store.log("suggestion", who, page_path(body.page), idea[:200], sid, status)   # for rate limits
        telemetry.emit("suggest", actor=f"visitor-{who[:8]}", actor_type="visitor", records_in=1, records_out=1,
                       detail={"idea_chars": len(idea), "has_contact": bool(body.contact.strip()), "status": status})
        return {"ok": True, "status": status, "id": sid}

    @app.get("/api/suggestions")
    def api_suggestions():
        """Published suggestions for the Suggestions page: idea, votes, date, and whether it's new. No names."""
        new_days = SETTINGS.get("suggestions", {}).get("new_days", 7)
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=new_days)).isoformat()
        return {"suggestions": [{"id": r["id"], "idea": r["idea"], "votes": r["votes"], "day": r["day"],
                                 "new": r["day"] >= cutoff} for r in S.store.suggestions(("published",), 100)]}

    @app.post("/api/suggestions/{sid}/vote")
    def api_vote(sid: int, request: Request):
        who = visitor(request)
        limit("vote", who, SETTINGS.get("suggestions", {}).get("votes_per_hour", 30))
        row = S.store.suggestion(sid)
        if not row or row["status"] != "published":
            raise HTTPException(404, "That suggestion isn't open for votes.")
        counted = S.store.vote(sid, who)
        S.store.log("vote", who, "", str(sid), 1 if counted else 0)
        return {"id": sid, "votes": S.store.suggestion(sid)["votes"], "counted": counted}

    @app.post("/api/like")
    def api_like(body: LikeIn, request: Request):
        """Thumbs up on a post. Only real posts count; one per visitor per post per day."""
        who = visitor(request)
        limit("like", who, SETTINGS.get("likes", {}).get("per_hour", 60))
        path = post_key(body.path)
        if path not in (S.store.get_kv("pages", {}) or {}):
            raise HTTPException(404, "Thumbs up works on posts only.")
        counted = S.store.like(path, who)
        S.store.log("like", who, path, "", 1 if counted else 0)
        telemetry.emit("like", actor=f"visitor-{who[:8]}", actor_type="visitor", records_in=1,
                       records_out=1 if counted else 0, detail={"path": path})
        return {"path": path, "likes": S.store.like_counts([path]).get(path, 0), "counted": counted}

    @app.post("/api/unhelpful")
    def api_unhelpful(body: UnhelpfulIn, request: Request):
        """Thumbs down on a post, optionally saying what was missing. Never published; summarised in the daily email."""
        who = visitor(request)
        limit("unhelpful", who, SETTINGS.get("likes", {}).get("per_hour", 60))
        path = post_key(body.path)
        if path not in (S.store.get_kv("pages", {}) or {}):
            raise HTTPException(404, "Feedback works on posts only.")
        note = " ".join(body.note.split())
        counted = S.store.unhelpful_vote(path, who, note)
        S.store.log("unhelpful", who, path, note[:200], 1 if counted else 0)
        telemetry.emit("unhelpful", actor=f"visitor-{who[:8]}", actor_type="visitor", records_in=1,
                       records_out=1 if counted else 0, detail={"path": path, "has_note": bool(note)})
        return {"path": path, "counted": counted}

    @app.get("/api/likes")
    def api_likes(paths: str = ""):
        keys = [post_key(p) for p in paths.split(",") if p.strip()][:60]
        counts = S.store.like_counts(keys) if keys else {}
        return {"likes": {k: counts.get(k, 0) for k in keys}}

    # ------------------------------------------------------------ subscriptions (double opt-in)
    @app.post("/api/subscribe", status_code=202)
    def api_subscribe(body: SubscribeIn, request: Request):
        who = visitor(request)
        limit("subscribe", who, SETTINGS["subscriptions"]["per_hour"])
        S.store.log("subscribe", who)                    # the address is never logged
        if body.website:
            return {"ok": True, "message": "Check your inbox to confirm."}
        if subscribers.subscribe(S.store, body.email, body.roles) == "invalid":
            raise HTTPException(422, "That doesn't look like an email address.")
        return {"ok": True, "message": "Check your inbox for a confirmation link. Nothing is sent until you confirm."}

    def _page(title: str, msg: str) -> HTMLResponse:
        site = site_url()
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            f"<title>{title}</title><body style='font:16px/1.5 system-ui;max-width:560px;margin:3rem "
                            f"auto;padding:0 16px'><h1 style='font-weight:500'>{title}</h1><p>{msg}</p>"
                            f"<p><a href='{site}/'>Back to the blog</a></p></body>")

    @app.get("/subscribe/confirm", response_class=HTMLResponse)
    def subscribe_confirm(t: str = ""):
        roles = subscribers.confirm(S.store, t)
        if roles is not None:
            which = "a new post is published" if not roles else "a new post for " + ", ".join(roles) + " is published"
            return _page("You're subscribed", f"You'll get an email when {which}. Every message has a link to change "
                         "this and a one-click unsubscribe.")
        return _page("Link not valid", "This confirmation link has expired or was already used.")

    @app.get("/subscribe/roles", response_class=HTMLResponse)
    def roles_page(t: str = ""):
        """Change which posts a subscriber gets. The link carries the same signed token as unsubscribe."""
        from html import escape
        from urllib.parse import quote
        cur = subscribers.roles_for(S.store, t)
        if cur is None:
            return _page("Link not valid", "This link isn't valid. Use the link in your most recent email.")
        boxes = "".join(f"<label style='display:block;margin:4px 0'><input type=checkbox name=roles value='{escape(r)}'"
                        f"{' checked' if r in cur else ''}> {escape(r)}</label>" for r in subscribers.known_roles(S.store))
        return _page("Which posts would you like?",
                     f"<form method=post action='{BASE}/subscribe/roles?t={escape(quote(t))}'>"
                     f"<p>Tick the roles you'd like posts for. Leave them all unticked to get every post.</p>{boxes}"
                     f"<p><button style='padding:.5rem 1rem'>Save</button></p></form>")

    @app.post("/subscribe/roles", response_class=HTMLResponse)
    async def roles_save(request: Request, t: str = ""):
        from urllib.parse import parse_qs
        form = parse_qs((await request.body()).decode("utf-8", "replace")[:4000])
        if not subscribers.set_roles(S.store, t, form.get("roles", [])):
            return _page("Link not valid", "This link isn't valid. Use the link in your most recent email.")
        chosen = subscribers.roles_for(S.store, t) or []
        return _page("Saved", "You'll get " + ("every new post." if not chosen else
                                               "posts for: " + ", ".join(chosen) + "."))

    @app.get("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe_page(t: str = ""):
        # a GET only shows a button: mail scanners follow links, and must not unsubscribe people
        from html import escape
        from urllib.parse import quote
        return _page("Unsubscribe?", f"<form method=post action='{BASE}/unsubscribe?t={escape(quote(t))}'><button style='padding:"
                     f".5rem 1rem'>Unsubscribe and delete my address</button></form>")

    @app.post("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe(t: str = ""):
        if subscribers.unsubscribe(S.store, t):
            return _page("Unsubscribed", "Your address has been deleted. You won't get any more emails.")
        return _page("Link not valid", "This unsubscribe link isn't valid.")

    # ------------------------------------------------------------ owner: content moderation (the console calls these)
    @app.get("/admin/content")
    def admin_content(request: Request):
        if not admin_ok(request):
            raise HTTPException(403, "owner token required")
        pages = S.store.get_kv("pages", {}) or {}
        week = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
        recent = {r["path"]: r["likes"] for r in S.store.top_liked(100, week)}
        down = S.store.unhelpful_counts()
        title = lambda p: (pages.get(p) or {}).get("short") or p                          # noqa: E731
        paths = [r["path"] for r in S.store.top_liked(20)]
        paths += [p for p in sorted(down, key=down.get, reverse=True) if p not in paths][:10]
        likes = S.store.like_counts(paths)
        last = {r["path"]: r["last_day"] for r in S.store.top_liked(100)}
        top = sorted([{"path": p, "title": title(p), "url": f"{site_url()}/{p}", "likes": likes.get(p, 0),
                       "unhelpful": down.get(p, 0), "last_7_days": recent.get(p, 0), "last_day": last.get(p, "")}
                      for p in paths], key=lambda r: (r["likes"] - r["unhelpful"], r["likes"]), reverse=True)
        notes = [{**n, "title": title(n["path"])} for n in S.store.unhelpful_notes(None, 30)]
        return {"top_articles": top, "unhelpful_notes": notes, "suggestions": S.store.suggestions(None, 500),
                "subscribers": subscribers.counts(S.store),
                "kickoff": {str(r["id"]): kickoff_links(r) for r in S.store.suggestions(None, 500)}}

    @app.post("/admin/suggestions/{sid}")
    def admin_set_status(sid: int, body: StatusIn, request: Request):
        if not admin_ok(request):
            raise HTTPException(403, "owner token required")
        if body.status not in Store.SUGGESTION_STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(Store.SUGGESTION_STATUSES)}")
        if not S.store.suggestion(sid):
            raise HTTPException(404, "unknown suggestion")
        S.store.set_suggestion_status(sid, body.status, body.actor or "owner")
        telemetry.emit("moderate", actor=body.actor or "owner", actor_type="person", records_in=1, records_out=1,
                       detail={"suggestion": sid, "status": body.status})
        return S.store.suggestion(sid)

    @app.post("/api/track", status_code=204)
    async def api_track(request: Request):
        try:
            d = json.loads((await request.body())[:4000] or b"{}")
        except ValueError:
            return Response(status_code=204)
        kind = d.get("kind")
        if kind not in ("pageview", "site-search"):
            return Response(status_code=204)
        who = visitor(request)
        if S.store.count_since(kind, who, 60) > 600:      # a runaway client, not a reader
            return Response(status_code=204)
        ref = d.get("referrer") or ""
        ref_host = urlparse(ref).netloc if ref else ""
        if ref_host and ref_host == urlparse(site_url()).netloc:
            ref_host = ""                                    # internal navigation isn't a referrer
        S.store.log(kind, who, page_path(d.get("path", "")), str(d.get("q", ""))[:300] if kind == "site-search" else
                    str(d.get("title", ""))[:200], int(d.get("results", 0) or 0), referrer=ref_host)
        return Response(status_code=204)

    # ------------------------------------------------------------ widget + pages
    @app.get("/widget.js")
    def widget_js():
        return FileResponse(HERE / "static" / "widget.js", media_type="text/javascript",
                            headers={"Cache-Control": "public, max-age=300"})

    @app.get("/widget.css")
    def widget_css():
        return FileResponse(HERE / "static" / "widget.css", media_type="text/css",
                            headers={"Cache-Control": "public, max-age=300"})

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        page = (HERE / "static" / "home.html").read_text()
        return page.replace("{{BASE}}", BASE).replace("{{SITE_URL}}", site_url())

    @app.get("/stats", response_class=HTMLResponse)
    def stats(request: Request):
        if not admin_ok(request):
            raise HTTPException(403, "owner token required: /stats?token=…")
        return digest.stats_page(S.store, SETTINGS, BASE, request.query_params.get("token", ""))

    @app.post("/digest/send")
    def digest_send(request: Request, day: str = ""):
        if not admin_ok(request):
            raise HTTPException(403, "owner token required")
        res = digest.run(S.store, SETTINGS, day or None, send_email=True)
        return JSONResponse({k: v for k, v in res.items() if k != "html"})
