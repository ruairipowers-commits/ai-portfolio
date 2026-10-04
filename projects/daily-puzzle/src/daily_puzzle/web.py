"""The player site (FastAPI + Jinja + HTMX) and the operator page. Runs the scheduler in-process.

    puzzle serve            → http://localhost:8800  (ROOT_PATH=/daily-puzzle behind the demos proxy)

Integrity rules enforced here, not only in the templates:
  - an answer is served only from the `reveal_*` columns, which are empty until the reveal step runs after close;
    /p/{id}/answer.json returns 403 before then;
  - draft, escalated, reserve, scheduled and pack puzzles are never shown to players;
  - a player's answer goes to code (game.submit), never to a model.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import assets, cycle, demo, game, generate, grading, mailer, packs, telemetry
from .config import PKG, TRACK_LABEL, TRACKS, Settings, root
from .store import acceptances, engine, fetch_all, fetch_one, jobs, players, puzzle_for_day, puzzles as P

ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
COOKIE = "dp_session"


# ---------------------------------------------------------------- small helpers
class Limiter:
    """In-memory sliding-window rate limits (one process; per IP or per account)."""

    def __init__(self):
        self.hits: dict[tuple, deque] = defaultdict(deque)

    def allow(self, bucket: str, key: str, n: int, per_s: int) -> bool:
        q, t = self.hits[(bucket, key)], time.time()
        while q and q[0] < t - per_s:
            q.popleft()
        if len(q) >= n:
            return False
        q.append(t)
        return True


def _sign(value: str) -> str:
    key = hashlib.sha256(("session:" + grading._secret("PUZZLE_KEY_SECRET")).encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:32]


def session_value(pid: int, days: int = 30) -> str:
    exp = int(time.time()) + days * 86400
    return f"{pid}.{exp}.{_sign(f'{pid}.{exp}')}"


def session_pid(v: str | None) -> int | None:
    try:
        pid, exp, sig = (v or "").split(".")
        if hmac.compare_digest(sig, _sign(f"{pid}.{exp}")) and int(exp) > time.time():
            return int(pid)
    except ValueError:
        pass
    return None


def client_ip(req: Request) -> str:
    return (req.headers.get("cf-connecting-ip") or req.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (req.client.host if req.client else "?"))


def fmt_local(dt: datetime | None, s: Settings) -> str:
    if not dt:
        return ""
    return dt.astimezone(cycle.tz(s)).strftime("%a %d %b, %H:%M %Z")


def scoring_line(s: Settings) -> str:
    sc, mx = s.puzzles["scoring"], int(s.puzzles["attempts"]["max_per_puzzle"])
    return " / ".join(str(grading.points(n, True, sc)) for n in range(1, mx + 1)) + f" for 1–{mx} attempts"


# ---------------------------------------------------------------- app
def create_app(scheduler: bool | None = None) -> FastAPI:
    s0 = Settings.load()
    eng = engine(s0)
    limiter = Limiter()
    run_scheduler = (os.getenv("PUZZLE_SCHEDULER", "1") == "1") if scheduler is None else scheduler

    @asynccontextmanager
    async def lifespan(app):
        telemetry.register(root())
        sched = None
        if run_scheduler:
            from apscheduler.schedulers.background import BackgroundScheduler

            def job():
                try:
                    s = Settings.load()
                    with eng.begin() as c:
                        cycle.maintain(c, s)
                    with eng.begin() as c:
                        cycle.tick(c, s)
                except Exception as e:  # noqa: BLE001
                    print(f"tick failed: {type(e).__name__}: {e}")
            sched = BackgroundScheduler(timezone="UTC")
            sched.add_job(job, "interval", seconds=60, next_run_time=datetime.now(), max_instances=1, coalesce=True)
            sched.start()
        yield
        if sched:
            sched.shutdown(wait=False)

    app = FastAPI(title="Daily puzzle", root_path=ROOT_PATH, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=PKG / "static"), name="static")
    from .packs import env as jenv
    links = demo.links(root())
    bar = demo.banner_html(root(), "Daily puzzle")
    if bar:   # the shared banner is styled for Streamlit; here the page itself makes room for it
        bar = re.sub(r"/\* make room for the bar.*?(?=</style>)", "", bar, flags=re.S)

    def page(req: Request, name: str, nav: str = "", status: int = 200, **ctx) -> HTMLResponse:
        s = Settings.load()
        with eng.connect() as c:
            me = me_of(c, req)
        html = jenv.get_template(name).render(base=ROOT_PATH, nav=nav, me=me, links=links, bar=bar,
                                              packs_open=s.puzzles["packs"]["who"] == "players", **ctx)
        resp = HTMLResponse(html, status_code=status)
        _visit(req, resp)
        return resp

    def _visit(req: Request, resp: Response) -> None:
        if not req.cookies.get("dp_v"):
            telemetry.set_session(secrets.token_hex(8))
            telemetry.emit("visit", actor=telemetry.visitor_id(client_ip(req)), actor_type="visitor")
            resp.set_cookie("dp_v", "1", max_age=86400, httponly=True, samesite="lax")

    def me_of(c, req: Request) -> dict | None:
        pid = session_pid(req.cookies.get(COOKIE))
        return fetch_one(c, select(players).where(players.c.id == pid)) if pid else None

    def base_url(req: Request) -> str:
        return os.getenv("PUZZLE_PUBLIC_URL", "").rstrip("/") or str(req.base_url).rstrip("/")

    def outbox_note() -> str:
        return "" if os.getenv("RESEND_API_KEY") else \
            "Email is in offline mode on this server: messages are written to output/outbox/ instead of being sent."

    def public_puzzle(c, puzzle_id: int) -> dict | None:
        p = fetch_one(c, select(P).where(P.c.id == puzzle_id))
        return p if p and p["status"] in ("open", "closed", "revealed") and p["day"] else None

    def play_ctx(s, c, p, me, fb=None):
        state = game.my_state(c, me["id"] if me else None, p["id"])
        return {"p": p, "state": state, "fb": fb, "max_attempts": int(s.puzzles["attempts"]["max_per_puzzle"])}

    # ------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def index(req: Request):
        s = Settings.load()
        with eng.connect() as c:
            me = me_of(c, req)
            today = datetime.now(cycle.tz(s)).date().isoformat()
            p = fetch_one(c, select(P).where(P.c.status == "open").order_by(P.c.opens_at.desc()))
            prev = fetch_one(c, select(P).where(P.c.status == "revealed", P.c.day.isnot(None)).order_by(P.c.day.desc()))
            nxt = fetch_one(c, select(P).where(P.c.status == "scheduled", P.c.day >= today).order_by(P.c.opens_at))
            ctx = play_ctx(s, c, p, me) if p else {"p": None}
        if p:
            p["sandbox"] = s.is_sandbox_track(p["track"])
        return page(req, "index.html", "today", **ctx, prev=prev, closes=fmt_local(p["closes_at"], s) if p else "",
                    next_open=fmt_local(nxt["opens_at"], s) if nxt else "", open_at=s.puzzles["window"]["open_at"],
                    tzname=s.puzzles["window"]["timezone"], scoring_line=scoring_line(s))

    @app.get("/p/{puzzle_id}", response_class=HTMLResponse)
    def puzzle_page(req: Request, puzzle_id: int):
        s = Settings.load()
        with eng.connect() as c:
            p = public_puzzle(c, puzzle_id)
            if not p:
                return page(req, "message.html", heading="Not found", text="There's no such puzzle.", status=404)
            me = me_of(c, req)
            ctx = play_ctx(s, c, p, me)
            acc = fetch_all(c, select(acceptances.c.attempts, acceptances.c.solved_at).where(acceptances.c.puzzle_id == puzzle_id))
        solved = [a["attempts"] for a in acc if a["solved_at"]]
        stats = {"accepted": len(acc), "solved": len(solved), "avg_attempts": sum(solved) / len(solved) if solved else 0}
        return page(req, "puzzle.html", **ctx, open=game.is_open(p), closes=fmt_local(p["closes_at"], s), stats=stats)

    @app.get("/p/{puzzle_id}/answer.json")
    def answer_json(puzzle_id: int):
        """FR-6: refused until the reveal step has run (after close)."""
        with eng.connect() as c:
            p = public_puzzle(c, puzzle_id)
        if not p:
            return JSONResponse({"error": "not found"}, 404)
        if p["status"] != "revealed":
            telemetry.record("answer_request", status="blocked", flags=["early_answer_request"])
            return JSONResponse({"error": "The answer is published after submissions close.",
                                 "closes_at": p["closes_at"].isoformat()}, 403)
        return {"puzzle_id": p["id"], "answer": p["reveal_answer"], "solution": p["reveal_solution"],
                "code": p["reveal_code"]}

    @app.post("/accept/{puzzle_id}", response_class=HTMLResponse)
    def accept(req: Request, puzzle_id: int):
        s = Settings.load()
        with eng.begin() as c:
            me = me_of(c, req)
            p = public_puzzle(c, puzzle_id)
            if not me or not p:
                return RedirectResponse(f"{ROOT_PATH}/signin", 303)
            fb = None
            try:
                game.accept(c, me["id"], puzzle_id)
            except game.GameError:
                fb = {"status": "closed"}
            ctx = play_ctx(s, c, p, me, fb)
        return _play(req, ctx, puzzle_id)

    def _play(req, ctx, puzzle_id):
        if req.headers.get("hx-request"):
            return HTMLResponse(jenv.get_template("_play.html").render(base=ROOT_PATH, me=True, **ctx))
        return RedirectResponse(f"{ROOT_PATH}/p/{puzzle_id}", 303)

    @app.post("/submit/{puzzle_id}", response_class=HTMLResponse)
    def submit(req: Request, puzzle_id: int, answer: str = Form("")):
        s = Settings.load()
        lim = s["limits"]
        with eng.begin() as c:
            me = me_of(c, req)
            p = public_puzzle(c, puzzle_id)
            if not me or not p:
                return RedirectResponse(f"{ROOT_PATH}/signin", 303)
            if not (limiter.allow("submit-ip", client_ip(req), lim["submissions_per_minute_per_ip"], 60)
                    and limiter.allow("submit-player", str(me["id"]), lim["submissions_per_minute_per_player"], 60)):
                fb = {"status": "rate"}
                telemetry.record("submit", status="blocked", flags=["rate_limited"])
            else:
                fb = game.submit(c, s, me["id"], puzzle_id, answer)
            ctx = play_ctx(s, c, p, me, fb)
        return _play(req, ctx, puzzle_id)

    @app.get("/leaderboard", response_class=HTMLResponse)
    def board(req: Request, period: str = "all", track: str | None = None):
        s = Settings.load()
        period = period if period in ("all", "week") else "all"
        track = track if track in TRACKS else None
        with eng.connect() as c:
            rows = game.leaderboard(c, s, period, track)
        return page(req, "leaderboard.html", "board", rows=rows, period=period, track=track, tracks=s.enabled_tracks(),
                    scoring_line=scoring_line(s))

    @app.get("/archive", response_class=HTMLResponse)
    def archive(req: Request):
        with eng.connect() as c:
            rows = fetch_all(c, select(P.c.id, P.c.day, P.c.title, P.c.track, P.c.status)
                             .where(P.c.status.in_(("open", "closed", "revealed")), P.c.day.isnot(None))
                             .order_by(P.c.day.desc()).limit(400))
        return page(req, "archive.html", "archive", rows=rows)

    @app.get("/data/", response_class=HTMLResponse)
    def data_index(req: Request):
        items = [(a["id"], f) for a in assets.allow_list().values() if a["source"] == "fixture" for f in a["files"]]
        body = "".join(f'<li><a href="{ROOT_PATH}/data/{assets.short(i)}/{f}">{i}/{f}</a></li>' for i, f in items)
        return page(req, "message.html", heading="Bundled puzzle data",
                    text="Synthetic files some coding and AI puzzles use (MIT / CC0). Save them under data/<name>/ "
                         "next to your code.", extra=body)

    @app.get("/data/{name}/{file}")
    def data_file(name: str, file: str):
        for a in assets.allow_list().values():
            if a["source"] == "fixture" and assets.short(a["id"]) == name and file in a["files"]:
                return FileResponse(root() / "fixtures" / name / file, filename=file)
        return JSONResponse({"error": "not found"}, 404)

    # ------------------------------------------------ accounts
    @app.get("/subscribe", response_class=HTMLResponse)
    def subscribe_form(req: Request):
        return page(req, "subscribe.html", "subscribe", tracks=Settings.load().enabled_tracks())

    @app.post("/subscribe", response_class=HTMLResponse)
    def subscribe(req: Request, email: str = Form(""), handle: str = Form(""), tracks: list[str] = Form([])):
        s = Settings.load()
        if not limiter.allow("signup", client_ip(req), s["limits"]["signups_per_hour_per_ip"], 3600):
            return page(req, "subscribe.html", "subscribe", tracks=s.enabled_tracks(), error="Too many sign-ups from here. Try later.",
                        email=email, handle=handle, status=429)
        try:
            with eng.begin() as c:
                game.subscribe(c, s, email, handle, tracks, base_url(req))
        except game.GameError as e:
            return page(req, "subscribe.html", "subscribe", tracks=s.enabled_tracks(), error=str(e), email=email,
                        handle=handle, status=400)
        return page(req, "message.html", heading="Check your email",
                    text="If that address can subscribe, a confirmation link is on its way. Nothing is sent until you click it.",
                    outbox_note=outbox_note())

    @app.get("/confirm/{token}", response_class=HTMLResponse)
    def confirm(req: Request, token: str):
        with eng.begin() as c:
            pid = game.confirm(c, token)
        if not pid:
            return page(req, "message.html", heading="Link expired", text="That link is used or expired. Subscribe again to get a new one.", status=400)
        resp = RedirectResponse(f"{ROOT_PATH}/?welcome=1", 303)
        resp.set_cookie(COOKIE, session_value(pid), max_age=30 * 86400, httponly=True, samesite="lax",
                        secure=req.url.scheme == "https")
        return resp

    @app.get("/signin", response_class=HTMLResponse)
    def signin_form(req: Request):
        return page(req, "signin.html", "signin")

    @app.post("/signin", response_class=HTMLResponse)
    def signin(req: Request, email: str = Form("")):
        s = Settings.load()
        if limiter.allow("signin", email.strip().lower(), s["limits"]["signin_links_per_hour_per_email"], 3600) and \
                limiter.allow("signin-ip", client_ip(req), 20, 3600):
            with eng.begin() as c:
                game.request_signin(c, s, email, base_url(req))
        return page(req, "message.html", heading="Check your email",
                    text="If that address has a confirmed subscription, a sign-in link is on its way.", outbox_note=outbox_note())

    @app.get("/auth/{token}")
    def auth(req: Request, token: str):
        with eng.begin() as c:
            pid = game.use_token(c, token, "signin")
        if not pid:
            return page(req, "message.html", heading="Link expired", text="That sign-in link is used or expired.", status=400)
        resp = RedirectResponse(f"{ROOT_PATH}/", 303)
        resp.set_cookie(COOKIE, session_value(pid), max_age=30 * 86400, httponly=True, samesite="lax",
                        secure=req.url.scheme == "https")
        return resp

    @app.post("/signout")
    def signout():
        resp = RedirectResponse(f"{ROOT_PATH}/", 303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/me", response_class=HTMLResponse)
    def me_page(req: Request):
        s = Settings.load()
        with eng.connect() as c:
            me = me_of(c, req)
            if not me:
                return RedirectResponse(f"{ROOT_PATH}/signin", 303)
            mine = next((r for r in game.leaderboard(c, s, limit=10**6) if r["handle"] == me["handle"]), {})
        return page(req, "me.html", "me", tracks=s.enabled_tracks(), mine=mine, unsub=game.unsub_token(me["id"]))

    @app.post("/me")
    def me_save(req: Request, tracks: list[str] = Form([])):
        with eng.begin() as c:
            me = me_of(c, req)
            if me:
                game.set_tracks(c, me["id"], tracks)
        return RedirectResponse(f"{ROOT_PATH}/me", 303)

    @app.post("/me/delete", response_class=HTMLResponse)
    def me_delete(req: Request):
        with eng.begin() as c:
            me = me_of(c, req)
            if me:
                game.delete_account(c, me["id"])
        resp = page(req, "message.html", heading="Account deleted", text="Your account, attempts and scores are gone.")
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/u/{pid}/{token}", response_class=HTMLResponse)
    def unsub_page(req: Request, pid: int, token: str):
        if not game.check_unsub(pid, token):
            return page(req, "message.html", heading="Link not valid", text="That unsubscribe link isn't valid.", status=400)
        return page(req, "message.html", heading="Unsubscribe?", text="Stop all daily puzzle emails to this address.",
                    form_action=f"{ROOT_PATH}/u/{pid}/{token}", form_label="Unsubscribe")

    @app.post("/u/{pid}/{token}", response_class=HTMLResponse)
    def unsub(req: Request, pid: int, token: str):
        """One-click (RFC 8058): mail clients POST here directly."""
        if not game.check_unsub(pid, token):
            return page(req, "message.html", heading="Link not valid", text="That unsubscribe link isn't valid.", status=400)
        with eng.begin() as c:
            game.unsubscribe(c, pid)
        return page(req, "message.html", heading="Unsubscribed", text="You won't get any more daily puzzle emails. You can still play on the site.")

    # ------------------------------------------------ packs for players (packs.who: players)
    @app.get("/packs", response_class=HTMLResponse)
    def packs_page(req: Request, flash: str = ""):
        s = Settings.load()
        if s.puzzles["packs"]["who"] != "players":
            return page(req, "message.html", heading="Not available", text="Puzzle packs are made by the operator here.", status=404)
        with eng.connect() as c:
            me = me_of(c, req)
            mine = _player_packs(c, me["id"]) if me else []
        return page(req, "packs.html", "packs", tracks=s.enabled_tracks(), pack_cfg=s.puzzles["packs"],
                    quota=s.puzzles["packs"]["player_daily_quota"], mine=mine, flash=flash)

    def _player_packs(c, pid) -> list[str]:
        rows = fetch_all(c, select(jobs.c.detail, jobs.c.at).where(jobs.c.job == "pack").order_by(jobs.c.id.desc()).limit(500))
        return [r["detail"]["pack_id"] for r in rows if (r["detail"] or {}).get("actor") == f"player:{pid}"]

    @app.post("/packs")
    def packs_make(req: Request, count: int = Form(5), tracks: list[str] = Form([])):
        s = Settings.load()
        cfg = s.puzzles["packs"]
        if cfg["who"] != "players":
            return JSONResponse({"error": "not available"}, 404)
        with eng.begin() as c:
            me = me_of(c, req)
            if not me:
                return RedirectResponse(f"{ROOT_PATH}/signin", 303)
            since = datetime.now(cycle.tz(s)) - timedelta(days=1)
            made_today = [r for r in fetch_all(c, select(jobs.c.detail, jobs.c.at).where(jobs.c.job == "pack"))
                          if (r["detail"] or {}).get("actor") == f"player:{me['id']}" and r["at"] >= since]
            if len(made_today) >= int(cfg["player_daily_quota"]):
                return RedirectResponse(f"{ROOT_PATH}/packs?flash=Daily+limit+reached", 303)
            generate.pack(c, s, count, tracks or "random", actor=f"player:{me['id']}")
        return RedirectResponse(f"{ROOT_PATH}/packs", 303)

    @app.get("/packs/{pack_id}/{which}.pdf")
    def player_pack_pdf(req: Request, pack_id: str, which: str):
        with eng.connect() as c:
            me = me_of(c, req)
            if not me or pack_id not in _player_packs(c, me["id"]) or which not in ("questions", "answers"):
                return JSONResponse({"error": "not found"}, 404)
            return Response(packs.render(c, Settings.load(), pack_id, which), media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="{pack_id}-{which}.pdf"'})

    # ------------------------------------------------ operator
    def is_admin(req: Request) -> bool:
        tok = os.getenv("PUZZLE_ADMIN_TOKEN", "")
        return bool(tok) and hmac.compare_digest(req.cookies.get("dp_admin", ""), _sign("admin:" + tok))

    @app.get("/admin", response_class=HTMLResponse)
    def admin(req: Request, flash: str = ""):
        if not os.getenv("PUZZLE_ADMIN_TOKEN"):
            return page(req, "message.html", heading="Operator page off", text="Set PUZZLE_ADMIN_TOKEN to use it.", status=404)
        if not is_admin(req):
            return page(req, "admin_login.html")
        s = Settings.load()
        with eng.connect() as c:
            today = puzzle_for_day(c, datetime.now(cycle.tz(s)).date().isoformat())
            esc = fetch_all(c, select(P).where(P.c.status == "escalated").order_by(P.c.id.desc()).limit(20))
            for e in esc:
                e["key"] = grading.unseal(e["sealed_key"])           # operator only: needed to judge the draft
            reserve = {t: c.execute(select(func.count()).where(P.c.status == "reserve", P.c.track == t)).scalar()
                       for t in s.enabled_tracks()}
            jl = fetch_all(c, select(jobs).where(jobs.c.job != "tick").order_by(jobs.c.id.desc()).limit(15))
            pk = packs.list_packs(c)
        return page(req, "admin.html", today=today, escalated=esc, reserve=reserve, jobs=jl, packs=pk, flash=flash,
                    tracks=s.enabled_tracks(), pack_cfg=s.puzzles["packs"], warnings=generate.model_warnings(s))

    @app.post("/admin/login", response_class=HTMLResponse)
    def admin_login(req: Request, token: str = Form("")):
        tok = os.getenv("PUZZLE_ADMIN_TOKEN", "")
        if not tok or not limiter.allow("admin", client_ip(req), 10, 3600) or not hmac.compare_digest(token, tok):
            telemetry.record("admin_login", status="blocked", flags=["bad_admin_token"])
            return page(req, "admin_login.html", error="Wrong token.", status=403)
        resp = RedirectResponse(f"{ROOT_PATH}/admin", 303)
        resp.set_cookie("dp_admin", _sign("admin:" + tok), max_age=8 * 3600, httponly=True, samesite="strict",
                        secure=req.url.scheme == "https")
        return resp

    @app.post("/admin/logout")
    def admin_logout():
        resp = RedirectResponse(f"{ROOT_PATH}/", 303)
        resp.delete_cookie("dp_admin")
        return resp

    def _guard(req):
        return None if is_admin(req) else RedirectResponse(f"{ROOT_PATH}/admin", 303)

    @app.post("/admin/tick")
    def admin_tick(req: Request):
        if r := _guard(req):
            return r
        with eng.begin() as c:
            out = cycle.tick(c, Settings.load())
        return RedirectResponse(f"{ROOT_PATH}/admin?flash=" + (", ".join(a["job"] for a in out) or "nothing+due"), 303)

    @app.post("/admin/reserve")
    def admin_reserve(req: Request):
        if r := _guard(req):
            return r
        with eng.begin() as c:
            ids = generate.build_reserve(c, Settings.load(), per_track=3)
        return RedirectResponse(f"{ROOT_PATH}/admin?flash=Added+{len(ids)}+reserve+puzzles", 303)

    @app.post("/admin/review/{puzzle_id}")
    def admin_review(req: Request, puzzle_id: int, reviewer: str = Form(""), decision: str = Form(""), note: str = Form("")):
        if r := _guard(req):
            return r
        try:
            with eng.begin() as c:
                generate.review(c, puzzle_id, reviewer, decision, note)
            msg = f"#{puzzle_id} {decision}d"
        except ValueError as e:
            msg = str(e)
        return RedirectResponse(f"{ROOT_PATH}/admin?flash={msg.replace(' ', '+')}", 303)

    @app.post("/admin/pack")
    def admin_pack(req: Request, count: int = Form(5), tracks: list[str] = Form([]), difficulty: str = Form("mixed"),
                   seed: str = Form("")):
        if r := _guard(req):
            return r
        with eng.begin() as c:
            out = generate.pack(c, Settings.load(), count, tracks or "random", difficulty,
                                int(seed) if seed.strip().isdigit() else None)
        msg = f"Pack {out['pack_id']}: {len(out['puzzle_ids'])} puzzles" + (f", {len(out['dropped'])} dropped" if out["dropped"] else "")
        return RedirectResponse(f"{ROOT_PATH}/admin?flash={msg.replace(' ', '+')}", 303)

    @app.get("/admin/pack/{pack_id}/{which}.pdf")
    def admin_pack_pdf(req: Request, pack_id: str, which: str):
        if r := _guard(req):
            return r
        if which not in ("questions", "answers"):
            return JSONResponse({"error": "not found"}, 404)
        with eng.connect() as c:
            try:
                pdf = packs.render(c, Settings.load(), pack_id, which)
            except LookupError:
                return JSONResponse({"error": "not found"}, 404)
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{pack_id}-{which}.pdf"'})

    @app.get("/healthz")
    def healthz():
        with eng.connect() as c:
            n = c.execute(select(func.count()).select_from(P)).scalar()
        return {"ok": True, "puzzles": n, "governance": telemetry.status().enabled}

    return app


def app_factory() -> FastAPI:
    return create_app()
