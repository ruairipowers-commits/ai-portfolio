"""FastAPI service: search and chat over the blog, plus the visit/search log behind the daily engagement email.

Public (called from the blog, CORS-limited to the site's origin):
  GET  /api/search?q=…          ranked passages with snippets and links (logged)
  POST /api/chat                {question, history, page} → NDJSON stream: sources, text deltas, done (logged)
  POST /api/track               {kind: pageview | site-search, path, title, referrer, q} (sendBeacon; logged)
  GET  /widget.js, /widget.css  the Ask button and panel the blog loads
  GET  /                        a standalone "Ask the portfolio" page
Owner (ASSISTANT_ADMIN_TOKEN, or GOVERNANCE_ADMIN_TOKEN):
  GET  /stats?token=…           the last 14 days, top searches and questions, digest history
  POST /digest/send?token=…     build and email the engagement summary now
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import digest, index, llm, telemetry
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


def allowed_origins() -> list[str]:
    o = urlparse(site_url())
    extra = [x.strip() for x in os.getenv("ASSISTANT_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    return [f"{o.scheme}://{o.netloc}", "http://localhost:8000", "http://127.0.0.1:8000", *extra]


# ---------------------------------------------------------------- background jobs
def _refresher() -> None:
    while True:
        try:
            index.refresh(S.store, index_source(), site_url(), SETTINGS["index"]["min_words"])
        except Exception as e:  # noqa: BLE001
            print(f"index refresh failed: {e}")
        S.store.purge(SETTINGS["privacy"]["retention_days"])
        time.sleep(60 * SETTINGS["index"]["refresh_minutes"])


def create_app(store: Store | None = None, background: bool = True) -> FastAPI:
    S.store = store or Store()
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
    def api_search(request: Request, q: str = "", page: str = ""):
        q = q.strip()[: SETTINGS["search"]["max_query_chars"]]
        if len(q) < 2:
            return {"query": q, "results": []}
        who = visitor(request)
        limit("search", who, SETTINGS["limits"]["searches_per_hour"])
        t0 = time.perf_counter()
        rows = index.search(S.store, q, SETTINGS["search"]["max_results"])
        S.store.log("search", who, page_path(page), q, len(rows), "ok" if rows else "no_results",
                    latency_ms=llm.time_ms(t0))
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
                        meta.get("input_tokens", 0), meta.get("output_tokens", 0), ms, flags=flags)
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
