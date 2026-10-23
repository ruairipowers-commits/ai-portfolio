"""The owner's API: lets the owner's own tools (JobHunt) suggest topics and read the owner's progress.

Auth: `Authorization: Bearer <COURSE_OWNER_API_TOKEN>`. If the token isn't set (or is shorter than 32 characters)
every endpoint answers 404, as if it didn't exist (fail closed). Compared in constant time.

What it can do, and what it can't:
- suggest: a topic + tags (+ optional docs link and a demand number). It goes through the SAME pipeline as a
  learner's suggestion: screen → moderator → the owner's approval email. Nothing is created until the owner
  approves on /owner (HITL-02); a flagged topic can't be approved by anyone (moderation.approvable). The only
  difference is the per-learner daily limit, replaced by `owner_api.max_suggestions_per_day`. `client_ref` makes it
  idempotent: sending the same suggestion twice returns the first one.
- status: what happened to those suggestions (pending / approved → course slug / rejected / duplicate of a course).
- progress: the OWNER's enrollments and completed levels only (never another learner's), keyed by course slug.
- catalog: slugs, titles, categories and tags (the same as the public catalog page).
Nothing here reads or returns learners' emails, answers or feedback.
"""
from __future__ import annotations

import hmac
import json
import os

from . import catalog, mailer, moderation, telemetry
from .config import LEVELS, Settings
from .store import insert, j, now, one, rows

TOKEN_ENV = "COURSE_OWNER_API_TOKEN"


def token_ok(header: str | None) -> bool | None:
    """None = API disabled (no token configured); False = wrong token; True = ok."""
    expected = os.getenv(TOKEN_ENV, "")
    if len(expected) < 32:
        return None
    got = (header or "")[7:].strip() if (header or "").lower().startswith("bearer ") else ""
    return hmac.compare_digest(got.encode(), expected.encode())


def owner_learner(conn, s: Settings) -> int:
    """The owner's learner row (created on first use, like a first sign-in)."""
    email = mailer.owner_email(s).strip().lower()
    if not email:
        raise ValueError("COURSE_OWNER_EMAIL is not set")
    r = one(conn, "SELECT id FROM learners WHERE email=?", email)
    if r:
        conn.execute("UPDATE learners SET is_owner=1 WHERE id=?", (r["id"],))
        return r["id"]
    return insert(conn, "learners", email=email, name=s["owner"], created_at=now(), last_seen=now(), is_owner=1)


def _view(row: dict) -> dict:
    scr = json.loads(row["screen"]) if row.get("screen") else {}
    a = json.loads(row["assessment"]) if row.get("assessment") else {}
    return {"id": row["id"], "client_ref": row.get("client_ref"), "status": row["status"],
            "course_slug": row.get("course_slug"), "duplicate_of": scr.get("duplicate_of") or a.get("duplicate_of"),
            "verdict": a.get("verdict"), "decided_at": row.get("decided_at")}


def suggest(conn, s: Settings, body: dict) -> tuple[int, dict]:
    """→ (http status, payload)."""
    cfg = s.get("owner_api", {})
    topic = str(body.get("topic", "")).strip()
    ref = str(body.get("client_ref", "")).strip()[:80] or None
    if not (s["moderation"]["min_chars"] <= len(topic) <= s["moderation"]["max_chars"]):
        return 422, {"error": f"topic must be {s['moderation']['min_chars']}-{s['moderation']['max_chars']} characters"}
    docs = str(body.get("docs", "") or "").strip()
    if docs and not docs.startswith("https://"):
        return 422, {"error": "docs must be an https link"}
    if ref:
        existing = one(conn, "SELECT * FROM suggestions WHERE client_ref=?", ref)
        if existing:
            return 200, {**_view(existing), "existing": True}
    lid = owner_learner(conn, s)
    today = now()[:10]
    n = one(conn, "SELECT COUNT(*) n FROM suggestions WHERE source='owner-api' AND substr(created_at,1,10)=?", today)["n"]
    if n >= cfg.get("max_suggestions_per_day", 30):
        return 429, {"error": "daily limit for API suggestions reached"}
    text = topic + (f" (docs: {docs})" if docs else "")
    a, scr = moderation.assess(conn, s, text[: s["moderation"]["max_chars"]])
    try:
        demand = round(float(body.get("demand") or 0), 3)
    except (TypeError, ValueError):
        demand = 0.0
    sid = insert(conn, "suggestions", learner_id=lid, text=text[: s["moderation"]["max_chars"]], created_at=now(),
                 status="pending", screen=j(scr), assessment=a.model_dump_json(), source="owner-api",
                 client_ref=ref, tags=j(catalog.clean_tags(body.get("tags") or {})), demand=demand)
    mailer.approval_request(conn, s, sid, text, a)
    telemetry.record("suggest", items=1, flags=[a.verdict, "owner_api"], detail={"verdict": a.verdict, "source": "owner-api"})
    return 201, _view(one(conn, "SELECT * FROM suggestions WHERE id=?", sid))


def statuses(conn, refs: list[str]) -> list[dict]:
    refs = [r for r in refs if r][:200]
    if not refs:
        return []
    q = ",".join("?" * len(refs))
    return [_view(r) for r in rows(conn, f"SELECT * FROM suggestions WHERE source='owner-api' AND client_ref IN ({q})", *refs)]


def progress(conn, s: Settings) -> dict:
    """The owner's courses: enrolled, which levels are complete, the highest one. Keyed by course slug."""
    lid = owner_learner(conn, s)
    out = {}
    for e in rows(conn, "SELECT course, enrolled_at FROM enrollments WHERE learner_id=?", lid):
        done = {p["level"]: p["completed_at"] for p in
                rows(conn, "SELECT level, completed_at FROM progress WHERE learner_id=? AND course=? AND completed_at IS NOT NULL",
                     lid, e["course"])}
        highest = next((lv for lv in reversed(LEVELS) if lv in done), None)
        out[e["course"]] = {"enrolled_at": e["enrolled_at"], "completed": done, "highest_completed": highest}
    return {"learner": "owner", "levels": list(LEVELS), "courses": out}


def catalog_list(conn) -> list[dict]:
    return [{"slug": c.slug, "title": c.title, "category": c.category, "tags": c.tags}
            for c in catalog.all_courses(conn).values()]
