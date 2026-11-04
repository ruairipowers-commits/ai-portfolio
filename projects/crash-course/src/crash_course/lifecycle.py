"""A course's lifecycle after it is written: the owner withdraws a course for rework and re-releases it, and every
level keeps a version history that learners and the owner can see.

Withdraw (the owner page, Ruairi's decision, 4 November 2026): a withdrawn course leaves the catalog and takes no
new sign-ups. Learners already signed up keep full access and keep progressing, with a banner saying the course is
being reworked. Re-release puts it back. Both are logged to `approvals`. The state lives in `course_state`, because
bundled courses come from tech pages and have no row of their own.

Versions: every level file carries `version` (and `changes`, what changed). Learners always get the newest published
version. A learner who completed an older version keeps the completion and sees "Updated to vN" with what changed
since their version, until they dismiss it. The owner can roll a level back: the chosen older version is published
again as a new version, so the history only ever grows and learners' notices still work.
"""
from __future__ import annotations

from . import catalog, checks, telemetry
from .config import LEVELS, Settings
from .schemas import Level
from .store import approval, now, one, rows

STATES = ("withdrawn", "active")


# ---------------------------------------------------------------- withdraw / re-release
def withdrawn(conn) -> dict[str, dict]:
    """slug -> {note, actor, at} for every withdrawn course."""
    return {r["slug"]: r for r in rows(conn, "SELECT slug, note, actor, at FROM course_state WHERE state='withdrawn'")}


def is_withdrawn(conn, slug: str) -> bool:
    return bool(one(conn, "SELECT 1 FROM course_state WHERE slug=? AND state='withdrawn'", slug))


def set_state(conn, slug: str, state: str, actor: str, note: str = "") -> None:
    if state not in STATES:
        raise ValueError("state must be withdrawn or active")
    if slug not in catalog.all_courses(conn):
        raise ValueError("unknown course")
    telemetry.require_enabled("approve", actor=actor)
    conn.execute("INSERT OR REPLACE INTO course_state (slug, state, note, actor, at) VALUES (?,?,?,?,?)",
                 (slug, state, note.strip()[:300], actor, now()))
    approval(conn, actor, "course", slug, "withdraw" if state == "withdrawn" else "release", note.strip()[:300])


def enrolled_count(conn, slug: str) -> int:
    return one(conn, "SELECT COUNT(*) n FROM enrollments WHERE course=?", slug)["n"]


# ---------------------------------------------------------------- version history
def history(slug: str, level: str) -> list[dict]:
    """Every version of a level, newest first. When a version exists both bundled and at runtime (the owner
    published the bundled draft), the runtime copy is the one that counts."""
    by_v: dict[int, tuple[str, Level]] = {}
    for where, lv in catalog.versions_with_source(slug, level):
        by_v[lv.version] = (where, lv)                    # runtime copies come after bundled ones
    current = catalog.load_level(slug, level)
    out = []
    for v in sorted(by_v, reverse=True):
        where, lv = by_v[v]
        out.append({"version": v, "status": lv.status, "where": where, "title": lv.title, "changes": lv.changes,
                    "written_by": lv.provenance.written_by, "approved_by": lv.provenance.approved_by,
                    "approved_at": lv.provenance.approved_at, "note": lv.provenance.note,
                    "current": bool(current and current.version == v)})
    return out


def rollback(conn, s: Settings, slug: str, level: str, version: int, actor: str) -> tuple[bool, list[str], int]:
    """Publish an older published version again, as the newest version. Checks run again, as on every publish."""
    telemetry.require_enabled("publish", actor=actor)
    if level not in LEVELS:
        return False, ["unknown level"], 0
    old = next((lv for _w, lv in reversed(catalog.versions_with_source(slug, level))
                if lv.version == version and lv.status == "published"), None)
    current = catalog.load_level(slug, level)
    if not old:
        return False, [f"v{version} was never published"], 0
    if current and current.version == version:
        return False, [f"v{version} is already the published version"], 0
    rep = checks.check_level(old, catalog.all_courses(conn).get(slug), s)
    if not rep.ok:
        return False, rep.problems, 0
    new_v = catalog.next_version(slug, level)
    lv = old.model_copy(update={
        "version": new_v, "status": "published",
        "changes": (f"Rolled back to the content of version {version}." + (f" {old.changes}" if old.changes else ""))[:1000],
        "provenance": old.provenance.model_copy(update={"approved_by": actor, "approved_at": now(),
                                                        "note": f"rollback to v{version}"})})
    catalog.save_level(lv)
    approval(conn, actor, "level", f"{slug}:{level}:v{new_v}", "rollback", f"content of v{version}")
    telemetry.record("publish", actor=actor, items=1, detail={"level": level, "rollback_to": version})
    return True, [], new_v


# ---------------------------------------------------------------- learners: "Updated to vN"
def _done_version(conn, p: dict) -> int | None:
    """The version the learner completed. Completions recorded before versions were tracked fall back to the
    version of their last passed attempt."""
    if p.get("completed_version"):
        return p["completed_version"]
    r = one(conn, "SELECT MAX(version) v FROM attempts WHERE learner_id=? AND course=? AND level=? AND passed=1",
            p["learner_id"], p["course"], p["level"])
    return r["v"] if r and r["v"] else None


def notice(conn, p: dict | None, current: Level | None) -> dict | None:
    """The "Updated to vN" notice for one completed level, or None. Lists what changed in every published version
    after the one the learner completed, newest first."""
    if not p or not p.get("completed_at") or not current:
        return None
    done_v = _done_version(conn, p)
    if done_v is None:                                   # unknown: newer only if published after they finished
        if not (current.provenance.approved_at and current.provenance.approved_at > p["completed_at"]):
            return None
        done_v = 0
    if current.version <= done_v or (p.get("notice_version") or 0) >= current.version:
        return None
    since = [h for h in history(current.course, current.level) if h["status"] == "published" and h["version"] > done_v]
    return {"course": current.course, "level": current.level, "from": done_v or None, "to": current.version,
            "changes": [{"version": h["version"], "text": h["changes"], "at": h["approved_at"][:10]} for h in since]}


def notices(conn, learner_id: int, course: str | None = None) -> list[dict]:
    sql = "SELECT * FROM progress WHERE learner_id=? AND completed_at IS NOT NULL" + (" AND course=?" if course else "")
    out = []
    for p in rows(conn, sql, learner_id, *([course] if course else [])):
        n = notice(conn, p, catalog.load_level(p["course"], p["level"]))
        if n:
            out.append(n)
    return out


def dismiss(conn, learner_id: int, course: str, level: str) -> bool:
    current = catalog.load_level(course, level)
    if not current or level not in LEVELS:
        return False
    cur = conn.execute("UPDATE progress SET notice_version=? WHERE learner_id=? AND course=? AND level=? "
                       "AND completed_at IS NOT NULL", (current.version, learner_id, course, level))
    return cur.rowcount > 0
