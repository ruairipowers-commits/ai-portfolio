"""Enrolment, unlocks and completion — plain code, no model anywhere in progress or unlocks.

Rules (config `completion`): a level is complete when its quiz has been passed at least once (Intermediate: every
module check and the final test) AND its project is marked done. Completing a level unlocks the next. A level that
is unlocked but not yet published shows as "being prepared" and queues a build job (owner approval still needed).
"""
from __future__ import annotations

import json

from . import catalog, jobs, lifecycle
from .config import LEVELS, Settings
from .store import insert, now, one, rows


class NotAllowed(Exception):
    """The learner asked for something the rules don't allow (a locked level, an unknown course)."""


def enroll(conn, s: Settings, learner_id: int, course: str) -> None:
    if course not in catalog.all_courses(conn):
        raise NotAllowed("unknown course")
    if not one(conn, "SELECT 1 FROM enrollments WHERE learner_id=? AND course=?", learner_id, course):
        if lifecycle.is_withdrawn(conn, course):           # closed to new sign-ups; existing learners keep going
            raise NotAllowed("this course is being reworked and isn't taking new sign-ups right now")
        last = one(conn, "SELECT MAX(position) p FROM enrollments WHERE learner_id=?", learner_id)["p"]
        insert(conn, "enrollments", learner_id=learner_id, course=course, enrolled_at=now(),
               position=(last or len(_ordered(conn, learner_id))) + 1)
    unlock(conn, s, learner_id, course, LEVELS[0])


# ---------------------------------------------------------------- the learner's own focus
PRIORITIES = ("high", "normal", "low")
SORTS = ("mine", "priority", "progress", "recent")


def _ordered(conn, learner_id: int) -> list[str]:
    """The learner's own order: by position (set when they move a course), then by when they signed up."""
    return [r["course"] for r in rows(conn, "SELECT course FROM enrollments WHERE learner_id=? "
                                            "ORDER BY position IS NULL, position, enrolled_at", learner_id)]


def set_focus(conn, learner_id: int, course: str, favorite: bool | None = None, priority: str | None = None) -> None:
    if not one(conn, "SELECT 1 FROM enrollments WHERE learner_id=? AND course=?", learner_id, course):
        raise NotAllowed("not on your tracker")
    if favorite is not None:
        conn.execute("UPDATE enrollments SET favorite=? WHERE learner_id=? AND course=?",
                     (int(favorite), learner_id, course))
    if priority is not None:
        if priority not in PRIORITIES:
            raise NotAllowed("unknown priority")
        conn.execute("UPDATE enrollments SET priority=? WHERE learner_id=? AND course=?", (priority, learner_id, course))


def move(conn, learner_id: int, course: str, where: str) -> None:
    """Move a course up, down, to the top or to the bottom of the learner's own order (positions are renumbered)."""
    order = _ordered(conn, learner_id)
    if course not in order:
        raise NotAllowed("not on your tracker")
    i = order.index(course)
    order.pop(i)
    j = {"up": max(i - 1, 0), "down": min(i + 1, len(order)), "top": 0, "bottom": len(order)}.get(where)
    if j is None:
        raise NotAllowed("unknown move")
    order.insert(j, course)
    for n, slug in enumerate(order, 1):
        conn.execute("UPDATE enrollments SET position=? WHERE learner_id=? AND course=?", (n, learner_id, slug))


def sort_entries(entries: list[dict], how: str) -> list[dict]:
    """`mine`: the learner's order. `priority`: high first, favourites first within each. `progress`: most levels
    complete first. `recent`: newest sign-up first. Ties keep the learner's order."""
    rank = {p: i for i, p in enumerate(PRIORITIES)}
    if how == "priority":
        return sorted(entries, key=lambda e: (rank.get(e["priority"], 1), not e["favorite"]))
    if how == "progress":
        return sorted(entries, key=lambda e: -e["done"])
    if how == "recent":
        return sorted(entries, key=lambda e: (e["enrolled_at"], e.get("added", 0)), reverse=True)
    return entries


def up_next(entries: list[dict]) -> dict | None:
    """The level to open next: in the learner's order, favourites first, the first level that's open and not done."""
    for e in sorted(entries, key=lambda e: not e["favorite"]):          # stable: keeps the learner's order
        for lv in e["levels"]:
            if lv["state"] == "unlocked":
                return {"course": e["course"], "level": lv}
    return None


def unlock(conn, s: Settings, learner_id: int, course: str, level: str) -> None:
    if not one(conn, "SELECT 1 FROM progress WHERE learner_id=? AND course=? AND level=?", learner_id, course, level):
        insert(conn, "progress", learner_id=learner_id, course=course, level=level, unlocked_at=now())
    if s["build"]["on_demand"] and catalog.level_status(course)[level] == "missing":
        jobs.enqueue(conn, "build", course, level)


def progress(conn, learner_id: int, course: str, level: str) -> dict | None:
    return one(conn, "SELECT * FROM progress WHERE learner_id=? AND course=? AND level=?", learner_id, course, level)


def require_open(conn, learner_id: int, course: str, level: str):
    """The level must be unlocked for this learner and published; returns the Level."""
    if level not in LEVELS:
        raise NotAllowed("unknown level")
    if not progress(conn, learner_id, course, level):
        raise NotAllowed("this level is locked")
    lv = catalog.load_level(course, level)
    if not lv:
        raise NotAllowed("this level is being prepared")
    return lv


def mark_project(conn, s: Settings, learner_id: int, course: str, level: str) -> dict:
    require_open(conn, learner_id, course, level)
    conn.execute("UPDATE progress SET project_done_at=COALESCE(project_done_at, ?) WHERE learner_id=? AND course=? "
                 "AND level=?", (now(), learner_id, course, level))
    return maybe_complete(conn, s, learner_id, course, level)


def quiz_parts(lv) -> list[str]:
    return [f"module:{m.id}" for m in lv.modules] + ["final"]


def maybe_complete(conn, s: Settings, learner_id: int, course: str, level: str) -> dict:
    p = progress(conn, learner_id, course, level)
    if not p or p["completed_at"]:
        return p or {}
    lv = catalog.load_level(course, level)
    if not lv:
        return p
    passed = set(json.loads(p["modules_passed"] or "[]"))
    if p["quiz_passed_at"]:
        passed.add("final")
    quiz_ok = (not s["completion"]["require_quiz_pass"]) or set(quiz_parts(lv)) <= passed
    project_ok = (not s["completion"]["require_project"]) or bool(p["project_done_at"])
    if quiz_ok and project_ok:
        conn.execute("UPDATE progress SET completed_at=?, completed_version=?, notice_version=? WHERE learner_id=? "
                     "AND course=? AND level=?", (now(), lv.version, lv.version, learner_id, course, level))
        nxt = s.next_level(level)
        if nxt:
            unlock(conn, s, learner_id, course, nxt)
    return progress(conn, learner_id, course, level)


def state(conn, s: Settings, learner_id: int) -> list[dict]:
    """Everything the tracker page shows: one entry per enrolled course, three levels each."""
    courses = catalog.all_courses(conn)
    out = []
    for e in rows(conn, "SELECT rowid AS rid, * FROM enrollments WHERE learner_id=? "
                        "ORDER BY position IS NULL, position, enrolled_at",
                  learner_id):
        c = courses.get(e["course"])
        if not c:
            continue
        status = catalog.level_status(c.slug)
        levels = []
        for name in LEVELS:
            p = progress(conn, learner_id, c.slug, name)
            lv = catalog.load_level(c.slug, name) if p else None
            parts = quiz_parts(lv) if lv else []
            passed = set(json.loads(p["modules_passed"] or "[]")) | ({"final"} if p and p["quiz_passed_at"] else set()) if p else set()
            if not p:
                st = "locked"
            elif p["completed_at"]:
                st = "complete"
            elif status[name] != "published":
                st = "preparing"
            else:
                st = "unlocked"
            levels.append({
                "name": name, "label": s.level(name)["label"], "minutes": s.level(name)["minutes"], "state": st,
                "best": p["quiz_best"] if p else 0, "quiz_passed": bool(p and p["quiz_passed_at"]),
                "parts_passed": len(passed & set(parts)), "parts": len(parts),
                "project_done": bool(p and p["project_done_at"]),
                "attempts": (one(conn, "SELECT COUNT(*) n FROM attempts WHERE learner_id=? AND course=? AND level=? "
                                       "AND submitted_at IS NOT NULL", learner_id, c.slug, name) or {}).get("n", 0),
            })
        out.append({"course": c, "levels": levels, "done": sum(lv_["state"] == "complete" for lv_ in levels),
                    "favorite": bool(e.get("favorite")), "priority": e.get("priority") or "normal",
                    "enrolled_at": e["enrolled_at"] or "", "added": e["rid"]})
    return out
