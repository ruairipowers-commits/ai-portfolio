"""The learner site (FastAPI + Jinja + Alpine.js, no build step) and the owner's approval pages.

    course serve            → http://localhost:8810   (ROOT_PATH=/crash-course behind the demos proxy)

Rules enforced here and in the modules it calls, not only in templates:
  - no model call on any learner request; builds and revisions run in the background worker
  - quiz pages carry a token, prompts and shuffled options only — never which option is correct (NFR-1)
  - materials, quizzes and project check-offs need the level to be unlocked for the signed-in learner
  - owner decisions need a valid, unexpired signature AND a POST from the confirmation page (no GET side effects)
  - every form is rate-limited; free text is escaped by Jinja and capped in length
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt

from . import accounts, ai, builder, catalog, checks, demo, jobs, mailer, moderation, quiz, revise, telemetry, tracker
from .config import LEVELS, PKG, Settings, root
from .schemas import Assessment
from .store import connect, insert, now, one, rows
from .tracker import NotAllowed

ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
COOKIE = "cc_session"
MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
LEVEL_BLURB = {
    "familiar": "The concept, its history, where it fits in a business, use cases, pros and cons, a hello-world "
                "project, a 10-question quiz and how to talk about it in an interview.",
    "beginner": "Core terms, setup, a 30-minute guided project with checkpoints, common mistakes, a cheat sheet and a "
                "15-question quiz.",
    "intermediate": "Deep dives on the core pieces with a scored check on each, production concerns, alternatives, a "
                    "capstone project and a 25-question final test.",
}


class Limiter:
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


def client_ip(req: Request) -> str:
    return (req.headers.get("cf-connecting-ip") or req.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (req.client.host if req.client else "?"))


def create_app(start_worker: bool = False) -> FastAPI:
    s = Settings.load()
    limiter = Limiter()

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            jobs.start_worker(s)
        telemetry.register(root())
        yield

    app = FastAPI(title="Crash course", lifespan=lifespan, docs_url=None, redoc_url=None, root_path=ROOT_PATH)
    app.mount("/static", StaticFiles(directory=PKG / "static"), name="static")
    tpl = Jinja2Templates(directory=PKG / "templates")
    tpl.env.filters["md"] = lambda text: MD.render(text or "")
    tpl.env.filters["dur"] = lambda m: f"{m} min" if m < 60 else f"{m // 60} hour" + ("s" if m >= 120 else "")
    tpl.env.globals.update(R=ROOT_PATH, LEVELS=LEVELS, BLURB=LEVEL_BLURB)

    def me(req: Request) -> dict | None:
        lid = accounts.session_learner(req.cookies.get(COOKIE))
        if not lid:
            return None
        with connect() as conn:
            u = one(conn, "SELECT id, name, email, is_owner FROM learners WHERE id=?", lid)
        if u:   # the owner is whoever holds COURSE_OWNER_EMAIL now, not whoever had it at sign-up
            u["is_owner"] = int(accounts.is_owner_email(s, u["email"]))
        return u

    def same_origin(req: Request) -> bool:
        """Owner actions are POSTs from our own pages (cookies are SameSite=Lax; this is a second check)."""
        origin = req.headers.get("origin") or req.headers.get("referer") or ""
        if not origin:
            return True
        host = req.headers.get("x-forwarded-host") or req.headers.get("host") or ""
        return origin.split("://", 1)[-1].split("/", 1)[0] == host

    def page(req: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        ctx.setdefault("user", me(req))
        ctx["links"] = demo.links(root())
        ctx["banner"] = demo.banner_html(root(), "Crash course")
        ctx["s"] = s
        resp = tpl.TemplateResponse(req, name, ctx, status_code=status)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def message(req: Request, title: str, text: str, status: int = 200, link: tuple[str, str] | None = None):
        return page(req, "message.html", status=status, title=title, text=text, link=link)

    def go(path: str) -> RedirectResponse:
        return RedirectResponse(ROOT_PATH + path, status_code=303)

    def need_user(req: Request, nxt: str):
        u = me(req)
        return u, (None if u else go(f"/signin?next={quote(nxt)}"))

    # ------------------------------------------------------------ public pages
    @app.get("/", response_class=HTMLResponse)
    def home(req: Request):
        with connect() as conn:
            courses = catalog.all_courses(conn)
        cats = sorted({c.category for c in courses.values()})
        telemetry.record("visit", event_type="visit")
        return page(req, "home.html", count=len(courses), cats=cats)

    @app.get("/catalog", response_class=HTMLResponse)
    def catalog_page(req: Request, q: str = "", cat: str = ""):
        with connect() as conn:
            courses = list(catalog.all_courses(conn).values())
            u = me(req)
            mine = {r["course"] for r in rows(conn, "SELECT course FROM enrollments WHERE learner_id=?", u["id"])} if u else set()
        ql = q.strip().lower()[:60]
        shown = [c for c in courses if (not cat or c.category == cat)
                 and (not ql or ql in c.title.lower() or ql in c.summary.lower() or ql in c.category.lower())]
        groups: dict[str, list] = {}
        for c in sorted(shown, key=lambda c: (c.category, c.title.lower())):
            groups.setdefault(c.category, []).append(c)
        return page(req, "catalog.html", groups=groups, q=q[:60], cat=cat, mine=mine, total=len(courses),
                    cats=sorted({c.category for c in courses}), user=u)

    @app.get("/course/{slug}", response_class=HTMLResponse)
    def course_page(req: Request, slug: str):
        with connect() as conn:
            c = catalog.all_courses(conn).get(slug)
            u = me(req)
            enrolled = bool(u and one(conn, "SELECT 1 FROM enrollments WHERE learner_id=? AND course=?", u["id"], slug))
        if not c:
            return message(req, "Course not found", "There's no course at that address.", 404)
        return page(req, "course.html", c=c, lvstatus=catalog.level_status(slug), enrolled=enrolled, user=u)

    # ------------------------------------------------------------ sign-in
    @app.get("/signin", response_class=HTMLResponse)
    def signin_form(req: Request, next: str = "/tracker"):
        return page(req, "signin.html", next=_safe_next(next), invite_only=not s["registration"]["open"])

    @app.post("/signin", response_class=HTMLResponse)
    def signin(req: Request, email: str = Form(""), name: str = Form(""), invite: str = Form(""),
               next: str = Form("/tracker")):
        if not limiter.allow("signin", client_ip(req), 5, 600) or not limiter.allow("signin-e", email.lower(), 3, 600):
            return message(req, "Slow down", "Too many sign-in requests. Try again in a few minutes.", 429)
        try:
            with connect() as conn:
                link = accounts.request_link(conn, s, email[:254], name[:40], invite[:64])
        except accounts.SignupClosed as e:
            return message(req, "Invitation needed", str(e).capitalize() + ".", 403)
        except ValueError as e:
            return page(req, "signin.html", error=str(e), next=_safe_next(next), email=email[:254], name=name[:40],
                        invite_only=not s["registration"]["open"], status=400)
        link += f"&next={quote(_safe_next(next))}"
        show = os.getenv("COURSE_SHOW_LINKS") == "1" and not os.getenv("RESEND_API_KEY")
        return page(req, "check_email.html", link=link if show else None)

    @app.get("/auth")
    def auth(req: Request, t: str = "", next: str = "/tracker"):
        with connect() as conn:
            lid = accounts.consume(conn, t)
        if not lid:
            return message(req, "Link expired", "That sign-in link has expired or was already used. Ask for a new one.",
                           400, ("/signin", "Get a new link"))
        resp = go(_safe_next(next))
        resp.set_cookie(COOKIE, accounts.session_value(lid, s["registration"]["session_days"]), httponly=True,
                        samesite="lax", secure=mailer.public_url().startswith("https"),
                        max_age=s["registration"]["session_days"] * 86400, path=ROOT_PATH or "/")
        return resp

    @app.post("/signout")
    def signout():
        resp = go("/")
        resp.delete_cookie(COOKIE, path=ROOT_PATH or "/")
        return resp

    # ------------------------------------------------------------ learner pages
    @app.post("/enroll")
    def enroll(req: Request, course: str = Form(...)):
        u, redirect = need_user(req, f"/course/{course}")
        if redirect:
            return redirect
        try:
            with connect() as conn:
                tracker.enroll(conn, s, u["id"], course)
        except NotAllowed as e:
            return message(req, "Can't sign up", str(e).capitalize() + ".", 404)
        telemetry.record("enroll", items=1)
        return go(f"/tracker#c-{course}")

    @app.get("/tracker", response_class=HTMLResponse)
    def tracker_page(req: Request):
        u, redirect = need_user(req, "/tracker")
        if redirect:
            return redirect
        with connect() as conn:
            st = tracker.state(conn, s, u["id"])
            mine = rows(conn, "SELECT id, text, status, created_at, course_slug FROM suggestions WHERE learner_id=? "
                              "ORDER BY id DESC LIMIT 10", u["id"])
        return page(req, "tracker.html", courses=st, suggestions=mine, user=u)

    @app.get("/learn/{slug}/{level}", response_class=HTMLResponse)
    def learn(req: Request, slug: str, level: str):
        u, redirect = need_user(req, f"/learn/{slug}/{level}")
        if redirect:
            return redirect
        try:
            with connect() as conn:
                lv = tracker.require_open(conn, u["id"], slug, level)
                p = tracker.progress(conn, u["id"], slug, level)
                c = catalog.all_courses(conn)[slug]
                attempts = rows(conn, "SELECT part, score, total, passed, submitted_at FROM attempts WHERE learner_id=? "
                                      "AND course=? AND level=? AND submitted_at IS NOT NULL ORDER BY id DESC LIMIT 10",
                                u["id"], slug, level)
        except NotAllowed as e:
            return message(req, "Not available yet", f"{str(e).capitalize()}. Your tracker shows what's unlocked.",
                           403, ("/tracker", "Go to my tracker"))
        passed = set(json.loads(p["modules_passed"] or "[]")) | ({"final"} if p["quiz_passed_at"] else set())
        telemetry.record("learn", items=1, detail={"level": level})
        return page(req, "learn.html", lv=lv, p=p, c=c, passed=passed, attempts=attempts, user=u,
                    parts=tracker.quiz_parts(lv), label=s.level(level)["label"], cfg=s.level(level))

    @app.post("/project/{slug}/{level}")
    def project_done(req: Request, slug: str, level: str):
        u, redirect = need_user(req, f"/learn/{slug}/{level}")
        if redirect:
            return redirect
        try:
            with connect() as conn:
                tracker.mark_project(conn, s, u["id"], slug, level)
        except NotAllowed as e:
            return message(req, "Not available", str(e).capitalize() + ".", 403)
        return go(f"/learn/{slug}/{level}#project")

    @app.get("/quiz/{slug}/{level}", response_class=HTMLResponse)
    def quiz_page(req: Request, slug: str, level: str, part: str = "final"):
        u, redirect = need_user(req, f"/learn/{slug}/{level}")
        if redirect:
            return redirect
        if not limiter.allow("quiz", str(u["id"]), 30, 3600):
            return message(req, "Slow down", "Too many quiz attempts in an hour. Take a break and come back.", 429)
        try:
            with connect() as conn:
                a = quiz.start(conn, s, u["id"], slug, level, part[:40])
                c = catalog.all_courses(conn)[slug]
        except NotAllowed as e:
            return message(req, "Quiz not available", str(e).capitalize() + ".", 403, ("/tracker", "My tracker"))
        return page(req, "quiz.html", a=a, c=c, label=s.level(level)["label"], user=u)

    @app.post("/quiz/submit", response_class=HTMLResponse)
    async def quiz_submit(req: Request):
        u, redirect = need_user(req, "/tracker")
        if redirect:
            return redirect
        form = await req.form()
        answers = {}
        for k, v in form.items():
            if k.startswith("a_"):
                try:
                    answers[k[2:]] = int(v)
                except ValueError:
                    pass
        try:
            with connect() as conn:
                res = quiz.submit(conn, s, u["id"], str(form.get("token", ""))[:64], answers)
                c = catalog.all_courses(conn)[res["course"]]
                nxt = s.next_level(res["level"])
                nxt_state = tracker.progress(conn, u["id"], res["course"], nxt) if nxt else None
        except NotAllowed as e:
            return message(req, "Couldn't score that", str(e).capitalize() + ".", 400, ("/tracker", "My tracker"))
        return page(req, "result.html", r=res, c=c, label=s.level(res["level"])["label"], nxt=nxt,
                    nxt_unlocked=bool(nxt_state), user=u)

    @app.post("/feedback/{slug}/{level}", response_class=HTMLResponse)
    def feedback(req: Request, slug: str, level: str, rating: int = Form(0), unclear: str = Form(""),
                 add: str = Form("")):
        u, redirect = need_user(req, f"/learn/{slug}/{level}")
        if redirect:
            return redirect
        if not limiter.allow("feedback", str(u["id"]), s["registration"]["feedback_per_day"], 86400):
            return message(req, "Thanks — that's plenty for today", "You've sent the daily maximum of feedback.", 429)
        try:
            with connect() as conn:
                lv = tracker.require_open(conn, u["id"], slug, level)
                insert(conn, "feedback", learner_id=u["id"], course=slug, level=level, version=lv.version,
                       rating=max(0, min(5, rating)), unclear=unclear.strip()[:1000], add_text=add.strip()[:1000],
                       created_at=now())
                n = one(conn, "SELECT COUNT(*) n FROM feedback WHERE course=? AND level=? AND status='new'",
                        slug, level)["n"]
                if n >= s["revisions"]["min_feedback"]:
                    jobs.enqueue(conn, "revise", slug, level)
        except NotAllowed as e:
            return message(req, "Not available", str(e).capitalize() + ".", 403)
        telemetry.record("feedback", event_type="feedback", items=1,
                         status="not_useful" if 0 < rating <= 2 else "ok")
        return message(req, "Thank you", "Your feedback is stored with this version of the level and goes into the next "
                       "revision. Every change is reviewed before it's published.", 200,
                       (f"/learn/{slug}/{level}", "Back to the level"))

    @app.get("/suggest", response_class=HTMLResponse)
    def suggest_form(req: Request):
        u, redirect = need_user(req, "/suggest")
        if redirect:
            return redirect
        return page(req, "suggest.html", user=u)

    @app.post("/suggest", response_class=HTMLResponse)
    def suggest(req: Request, topic: str = Form("")):
        u, redirect = need_user(req, "/suggest")
        if redirect:
            return redirect
        if not limiter.allow("suggest", client_ip(req), 10, 86400):
            return message(req, "Slow down", "Too many suggestions from here today.", 429)
        try:
            with connect() as conn:
                moderation.suggest(conn, s, u["id"], topic[: s["moderation"]["max_chars"] + 50])
        except ValueError as e:
            return page(req, "suggest.html", error=str(e), topic=topic[:200], user=u, status=400)
        except telemetry.WorkflowDisabled:
            return message(req, "Paused", "Suggestions are paused right now. Please try later.", 503)
        return message(req, "Thanks — it's with the reviewer",
                       "Every suggested topic is checked and then approved or declined by a person before any course "
                       "is created. You'll get an email either way, and it's listed on your tracker.", 200,
                       ("/tracker", "My tracker"))

    @app.get("/me", response_class=HTMLResponse)
    def me_page(req: Request):
        u, redirect = need_user(req, "/me")
        if redirect:
            return redirect
        return page(req, "me.html", user=u)

    @app.post("/me/delete", response_class=HTMLResponse)
    def me_delete(req: Request, confirm: str = Form("")):
        u, redirect = need_user(req, "/me")
        if redirect:
            return redirect
        if confirm.strip().lower() != "delete":
            return page(req, "me.html", user=u, error="Type DELETE to confirm.", status=400)
        with connect() as conn:
            accounts.delete(conn, u["id"])
        resp = message(req, "Deleted", "Your account, progress, quiz attempts, feedback and suggestions are deleted.",
                       200, ("/", "Home"))
        resp.delete_cookie(COOKIE, path=ROOT_PATH or "/")
        return resp

    # ------------------------------------------------------------ owner (signed links → confirm → POST)
    @app.get("/owner/decide", response_class=HTMLResponse)
    def owner_confirm(req: Request, k: str = "", r: str = "", d: str = "", e: str = "", sig: str = ""):
        if not mailer.verify(k, r, d, e, sig):
            return message(req, "Link not valid", "This approval link is invalid or has expired.", 403)
        with connect() as conn:
            if k == "suggestion":
                row = one(conn, "SELECT * FROM suggestions WHERE id=?", int(r) if r.isdigit() else -1)
                if not row:
                    return message(req, "Not found", "That suggestion no longer exists.", 404)
                parsed = moderation.parse(row)
                parsed["approvable"] = moderation.approvable(Assessment.model_validate(parsed["assessment"]), s)
                return page(req, "owner_decide.html", kind=k, ref=r, decision=d, e=e, sig=sig, row=parsed, user=None)
            if k == "level":
                slug, level = (r.split(":") + [""])[:2]
                lv = catalog.load_level(slug, level, include_drafts=True)
                return page(req, "owner_decide.html", kind=k, ref=r, decision=d, e=e, sig=sig, lv=lv, user=None,
                            preview=mailer.preview_link(slug, level, 1) if lv else "")
        return message(req, "Unknown action", "That link doesn't match anything.", 400)

    @app.post("/owner/decide", response_class=HTMLResponse)
    def owner_decide(req: Request, k: str = Form(""), r: str = Form(""), d: str = Form(""), e: str = Form(""),
                     sig: str = Form(""), title: str = Form(""), docs: str = Form(""), notes: str = Form("")):
        if not mailer.verify(k, r, d, e, sig):
            return message(req, "Link not valid", "This approval link is invalid or has expired.", 403)
        actor = s["owner"]
        try:
            with connect() as conn:
                if k == "suggestion":
                    row = moderation.decide(conn, s, int(r), d, actor, title=title[:80], docs=docs.strip()[:300],
                                            notes=notes[:4000])
                    text = (f"Approved: course '{row['course_slug']}' created; its Familiar level is being drafted and "
                            "you'll get an email to review it before it's published." if row["status"] == "approved"
                            else f"Suggestion #{r} is {row['status']}.")
                    return message(req, "Done", text)
                if k == "level":
                    slug, level = r.split(":")
                    if d == "publish":
                        ok, problems = builder.publish(conn, s, slug, level, actor)
                        return message(req, "Published" if ok else "Not published",
                                       "Learners who have unlocked it can open it now." if ok else
                                       "Checks failed: " + "; ".join(problems[:5]), 200 if ok else 400)
                    builder.reject(conn, s, slug, level, actor, notes[:300])
                    return message(req, "Rejected", "The draft is rejected; unlocking it again queues a new draft.")
        except ValueError as ex:
            return message(req, "Couldn't do that", str(ex), 400)
        return message(req, "Unknown action", "Nothing was changed.", 400)

    @app.get("/owner/preview/{slug}/{level}", response_class=HTMLResponse)
    def owner_preview(req: Request, slug: str, level: str, e: str = "", sig: str = ""):
        if not mailer.verify("preview", slug, level, e, sig):
            u = me(req)
            if not (u and u["is_owner"]):
                return message(req, "Not allowed", "Preview links are for the course owner.", 403)
        with connect() as conn:
            c = catalog.all_courses(conn).get(slug)
        lv = catalog.load_level(slug, level, include_drafts=True)
        if not (c and lv):
            return message(req, "Not found", "No such draft.", 404)
        rep = checks.check_level(lv, c, s)
        return page(req, "learn.html", lv=lv, p=None, c=c, passed=set(), attempts=[], preview=True, report=rep,
                    parts=tracker.quiz_parts(lv), label=s.level(level)["label"], cfg=s.level(level))

    # ------------------------------------------------------------ owner page (signed in as COURSE_OWNER_EMAIL)
    def owner_state(conn) -> dict:
        courses = catalog.all_courses(conn)
        drafts = []
        for slug in sorted(courses):
            for name in LEVELS:
                if catalog.has_pending_draft(slug, name):
                    lv = catalog.load_level(slug, name, include_drafts=True)
                    rep = checks.check_level(lv, courses[slug], s)
                    drafts.append({"course": slug, "title": courses[slug].title, "level": name, "version": lv.version,
                                   "ok": rep.ok, "problems": rep.problems[:3], "minutes": rep.stats["minutes"],
                                   "questions": rep.stats["questions"], "by": lv.provenance.written_by,
                                   "note": lv.provenance.note})
        sugg = [moderation.parse(r) for r in rows(conn, "SELECT * FROM suggestions ORDER BY (status='pending') DESC, "
                                                        "id DESC LIMIT 30")]
        for g in sugg:
            g["approvable"] = moderation.approvable(Assessment.model_validate(g["assessment"]), s)
        props = []
        for p in rows(conn, "SELECT * FROM proposals WHERE status='pending' ORDER BY id"):
            props.append({**p, "payload": json.loads(p["payload"])})
        fb = rows(conn, "SELECT f.*, l.name FROM feedback f LEFT JOIN learners l ON l.id=f.learner_id "
                        "ORDER BY f.id DESC LIMIT 20")
        stats = {"learners": one(conn, "SELECT COUNT(*) n FROM learners")["n"],
                 "enrolments": one(conn, "SELECT COUNT(*) n FROM enrollments")["n"],
                 "attempts": one(conn, "SELECT COUNT(*) n FROM attempts WHERE submitted_at IS NOT NULL")["n"],
                 "completed": one(conn, "SELECT COUNT(*) n FROM progress WHERE completed_at IS NOT NULL")["n"],
                 "published": sum(1 for slug in courses for name in LEVELS if catalog.load_level(slug, name))}
        # levels a learner has unlocked that have neither a published version nor a draft: what they are waiting on
        waiting = []
        for r in rows(conn, "SELECT course, level, COUNT(*) n FROM progress GROUP BY course, level ORDER BY course"):
            if r["course"] in courses and catalog.level_status(r["course"])[r["level"]] == "missing":
                last = one(conn, "SELECT status, detail FROM jobs WHERE kind='build' AND course=? AND level=? "
                                 "ORDER BY id DESC LIMIT 1", r["course"], r["level"])
                why = (json.loads(last["detail"] or "{}").get("error", "") if last and last["status"] == "failed" else "")
                waiting.append({"course": r["course"], "title": courses[r["course"]].title, "level": r["level"],
                                "learners": r["n"], "job": last["status"] if last else "", "why": why[:200]})
        return {"drafts": drafts, "suggestions": sugg, "proposals": props, "feedback": fb, "stats": stats,
                "jobs": jobs.recent(conn, 10), "waiting": waiting, "no_writer": ai.placeholder_writer_blocked(s)}

    @app.get("/owner", response_class=HTMLResponse)
    def owner_page(req: Request, done: str = ""):
        u, redirect = need_user(req, "/owner")
        if redirect:
            return redirect
        if not u["is_owner"]:
            return message(req, "Owner only", "This page is for the course owner.", 403)
        with connect() as conn:
            st = owner_state(conn)
        return page(req, "owner.html", user=u, done=done[:200], **st)

    @app.post("/owner/action")
    async def owner_action(req: Request):
        u = me(req)
        if not (u and u["is_owner"]) or not same_origin(req):
            return message(req, "Owner only", "This action is for the course owner.", 403)
        f = await req.form()
        kind, actor = str(f.get("kind", "")), s["owner"]
        try:
            with connect() as conn:
                if kind == "suggestion":
                    row = moderation.decide(conn, s, int(f.get("id", -1)), "approve" if f.get("decision") == "approve"
                                            else "reject", actor, title=str(f.get("title", ""))[:80],
                                            docs=str(f.get("docs", "")).strip()[:300], notes=str(f.get("notes", ""))[:4000])
                    done = f"Suggestion #{row['id']} {row['status']}" + (f": course {row['course_slug']} created, "
                           "its Familiar level is queued" if row["course_slug"] else "")
                elif kind == "level":
                    slug, level = str(f.get("course", "")), str(f.get("level", ""))
                    if f.get("decision") == "publish":
                        ok, problems = builder.publish(conn, s, slug, level, actor)
                        done = f"{slug}/{level} published" if ok else f"{slug}/{level} not published: {problems[0]}"
                    else:
                        builder.reject(conn, s, slug, level, actor, str(f.get("notes", ""))[:300])
                        done = f"{slug}/{level} draft rejected"
                elif kind == "build":
                    slug, level = str(f.get("course", "")), str(f.get("level", ""))
                    if slug not in catalog.all_courses(conn) or level not in LEVELS:
                        raise ValueError("unknown course or level")
                    if ai.placeholder_writer_blocked(s):
                        done = "No writer model is set: add COURSE_WRITER_MODEL (e.g. local-qwen) and restart first"
                    else:
                        jid = jobs.enqueue(conn, "build", slug, level)
                        done = (f"{slug}/{level} queued: the draft appears here when it's written (a local model "
                                "can take several minutes)") if jid else f"{slug}/{level} is already being drafted"
                elif kind == "publish_all":
                    n, bad = 0, 0
                    for slug in sorted(catalog.all_courses(conn)):
                        for level in LEVELS:
                            if catalog.has_pending_draft(slug, level):
                                ok, _ = builder.publish(conn, s, slug, level, actor)
                                n, bad = n + ok, bad + (not ok)
                    done = f"Published {n} level(s)" + (f"; {bad} failed their checks and stay as drafts" if bad else "")
                elif kind == "proposal":
                    pid = int(f.get("id", -1))
                    accepted = [int(x) for x in f.getlist("accept")]
                    res = revise.decide(conn, s, pid, accepted, actor)
                    done = f"Proposal #{pid}: {res['status']}, {res['applied']} edit(s) applied to a new draft"
                else:
                    done = "Nothing changed"
        except (ValueError, NotAllowed) as e:
            done = f"Couldn't do that: {e}"
        except telemetry.WorkflowDisabled:
            done = "The workflow is paused by the governance console"
        return go(f"/owner?done={quote(done[:200])}")

    # ------------------------------------------------------------ health
    @app.get("/api/health")
    def health():
        with connect() as conn:
            pending = one(conn, "SELECT COUNT(*) n FROM jobs WHERE status='pending'")["n"]
            n = one(conn, "SELECT COUNT(*) n FROM learners")["n"]
        return JSONResponse({"ok": True, "courses": len(catalog.bundled()), "learners": n, "pending_jobs": pending,
                             "email": "resend" if os.getenv("RESEND_API_KEY") else "outbox"})

    return app


def _safe_next(nxt: str) -> str:
    """Only same-site paths (no open redirect)."""
    return nxt if re.match(r"^/[A-Za-z0-9/_\-#?=&.]*$", nxt or "") and not nxt.startswith("//") else "/tracker"
