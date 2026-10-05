"""The editorial service: public read-only queue, the owner's pick / dismiss confirmations, and the scheduler.

    GET  /                 the ranked queue (read-only, public: topics are public links)
    GET  /queue.md         the same as plain Markdown, for the weekly writer to read
    GET  /api/queue        JSON
    GET  /act?t=…          confirmation page for a signed Pick / Dismiss link from the owner's email
    POST /act              applies it (single-use; recorded with who/when — HITL-02)
    GET  /api/health

The scheduler (EDITORIAL_SCHEDULER=1, on in the image) refills the queue daily, emails the list weekly and syncs
draft / published state from the blog repo's pull requests every 30 minutes.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from html import escape as e
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import digest, github_sync, links, scout, telemetry
from .config import ROOT, link_secret, public_url, settings
from .store import Store

BASE = os.getenv("ROOT_PATH", "").rstrip("/")
CSS = ("body{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 16px;color:#222}"
       "a{color:#3f51b5}.t{padding:.7rem 0;border-bottom:1px solid #eee}.m{color:#777;font-size:.8rem}"
       ".p{color:#2e7d32;font-weight:700}button{padding:.45rem 1rem;border:0;border-radius:4px;background:#546e7a;"
       "color:#fff;font:inherit;cursor:pointer}h1{font-weight:500}")


class StripPrefix:
    """Accept requests with or without the ROOT_PATH prefix (Caddy forwards /editorial-agents/… unchanged)."""

    def __init__(self, app, prefix: str):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = {**scope, "path": path[len(self.prefix):] or "/", "raw_path": None}
        await self.app(scope, receive, send)


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                        f"<title>{e(title)}</title><style>{CSS}</style><h1>{e(title)}</h1>{body}")


def queue_rows(store: Store) -> list[dict]:
    out = []
    for i, t in enumerate(store.queue(), 1):
        a, sc = t.get("analysis") or {}, t.get("scores") or {}
        out.append({"rank": i, "id": t["id"], "status": t["status"], "title": t["title"], "url": t["url"],
                    "source": t["source"], "summary": a.get("summary", ""), "angle": a.get("angle", ""),
                    "sectors": a.get("sectors", []), "kind": a.get("kind", ""), "scores": sc,
                    "published": t.get("published", "")})
    return out


def queue_md(store: Store) -> str:
    lines = ["# Topic queue", "", "Picked topics first, then by rank. The writer drafts from the first row.", ""]
    for r in queue_rows(store):
        lines += [f"## {r['rank']}. {r['title']}", "",
                  f"- id: `{r['id']}`", f"- status: {r['status']}", f"- link: {r['url']}",
                  f"- source: {r['source']}", f"- summary: {r['summary']}", f"- angle: {r['angle']}",
                  f"- sectors: {', '.join(r['sectors'])}",
                  f"- scores: engagement {r['scores'].get('engagement', 0):.2f}, novelty "
                  f"{r['scores'].get('novelty', 0):.2f}, score {r['scores'].get('score', 0):.3f}", ""]
    return "\n".join(lines)


def _scheduler(store: Store) -> None:
    s = settings()["schedule"]
    tz = ZoneInfo(s["timezone"])
    done: set[str] = set()
    last_sync = 0.0
    while True:
        try:
            now = datetime.now(tz)
            day, hm, wd = now.date().isoformat(), now.strftime("%H:%M"), now.strftime("%a").lower()[:3]
            if hm >= s["scout"] and f"scout:{day}" not in done:
                done.add(f"scout:{day}")
                scout.run(store)
            if wd == s["digest_weekday"] and hm >= s["digest_time"] and f"digest:{day}" not in done:
                done.add(f"digest:{day}")
                digest.send(store)
            if time.time() - last_sync > 60 * s["github_sync_minutes"]:
                last_sync = time.time()
                github_sync.sync(store)
        except telemetry.WorkflowDisabled as ex:
            print(f"skipped: {ex}")
        except Exception as ex:  # noqa: BLE001 — keep the loop alive; the run table records failures
            store.run("scheduler", "error", {"error": f"{type(ex).__name__}: {ex}"})
        time.sleep(60)


def _safe_rerank(store: Store) -> None:
    try:
        scout.rerank(store)
    except Exception as ex:  # noqa: BLE001 — the next scout run re-ranks anyway
        store.run("rerank", "error", {"error": f"{type(ex).__name__}: {ex}"})


def create_app(store: Store | None = None, background: bool | None = None) -> FastAPI:
    store = store or Store()
    link_secret()                                   # refuse to start without the secret in the live service
    app = FastAPI(title="Editorial agents", docs_url=None, redoc_url=None)
    if BASE:
        app.add_middleware(StripPrefix, prefix=BASE)
    if background if background is not None else os.getenv("EDITORIAL_SCHEDULER") == "1":
        telemetry.register(ROOT)
        threading.Thread(target=_scheduler, args=(store,), daemon=True, name="editorial-scheduler").start()

    @app.get("/api/health")
    def health():
        last = store.last_run("scout")
        return {"ok": True, "queue": len(store.queue()), "last_scout": last["ts"] if last else None}

    @app.get("/api/queue")
    def api_queue():
        return JSONResponse(queue_rows(store))

    @app.get("/queue.md", response_class=PlainTextResponse)
    def md():
        return queue_md(store)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        telemetry.record("view", event_type="visit")
        rows = "".join(
            f"<div class=t><b>{r['rank']}.</b> {'<span class=p>Picked · </span>' if r['status'] == 'picked' else ''}"
            f"<a href='{e(r['url'])}'>{e(r['title'])}</a><br>{e(r['summary'])}<br><i>{e(r['angle'])}</i>"
            f"<div class=m>{e(', '.join(r['sectors']))} · {e(r['source'])} · engagement "
            f"{r['scores'].get('engagement', 0):.2f} · novelty {r['scores'].get('novelty', 0):.2f}</div></div>"
            for r in queue_rows(store)) or "<p>The queue is empty until the first scout run.</p>"
        intro = ("<p>Topics my scout agent found this week, ranked by predicted engagement, novelty against what I've "
                 "already published, and how many market sectors could use them. I pick from this list; a weekly "
                 "writer and an independent editor draft a post from my top pick, and nothing publishes until I "
                 "approve it.</p>")
        return page("Blog topic queue", intro + rows)

    @app.get("/act", response_class=HTMLResponse)
    def act_confirm(t: str = ""):
        try:
            v = links.verify(t)
        except ValueError as ex:
            return page("Link not valid", f"<p>{e(str(ex))}. Use a link from the latest topic email.</p>")
        topic = store.topic(v["topic_id"])
        if not topic:
            return page("Topic not found", "<p>It may have expired from the queue.</p>")
        verb = {"pick": "Pick this topic for a post", "dismiss": "Dismiss this topic", "unpick": "Unpick this topic"}
        return page(verb[v["action"]] + "?", f"<p><a href='{e(topic['url'])}'>{e(topic['title'])}</a></p>"
                    f"<form method=post action='{BASE}/act'><input type=hidden name=t value='{e(t)}'>"
                    f"<button>{verb[v['action']]}</button></form>")

    @app.post("/act", response_class=HTMLResponse)
    def act(t: str = Form("")):
        try:
            v = links.verify(t)
        except ValueError as ex:
            return page("Link not valid", f"<p>{e(str(ex))}.</p>")
        if not store.use_nonce(v["nonce"]):
            return page("Already done", "<p>This link has already been used.</p>")
        topic = store.topic(v["topic_id"])
        if not topic:
            return page("Topic not found", "")
        new = {"pick": "picked", "dismiss": "dismissed", "unpick": "queued"}[v["action"]]
        store.set_status(topic["id"], new, rank=None if new == "dismissed" else topic.get("rank"))
        store.action(topic["id"], v["action"], "owner (signed email link)")
        telemetry.record("owner_" + v["action"], event_type="feedback", actor="owner", items=1)
        threading.Thread(target=_safe_rerank, args=(store,), daemon=True).start()   # refill to N now
        return page("Done", f"<p>{e(topic['title'])} is now <b>{new}</b>. "
                    f"<a href='{BASE}/'>See the queue</a> · {e(public_url())}</p>")

    return app
