"""A tiny job queue in SQLite: course builds and revision proposals run in the background, never in a web request.

`course worker` (or the thread inside `course serve`) picks pending jobs oldest first. One job of a kind per course
and level is queued at a time.
"""
from __future__ import annotations

import json
import threading
import time
import traceback

from .config import Settings
from .store import connect, insert, now, one, rows


def enqueue(conn, kind: str, course: str, level: str) -> int | None:
    if one(conn, "SELECT id FROM jobs WHERE kind=? AND course=? AND level=? AND status IN ('pending','running')",
           kind, course, level):
        return None
    return insert(conn, "jobs", kind=kind, course=course, level=level, status="pending", created_at=now())


def run_pending(s: Settings, limit: int = 5) -> list[dict]:
    from . import builder, revise
    done = []
    for _ in range(limit):
        with connect() as conn:
            job = one(conn, "SELECT * FROM jobs WHERE status='pending' ORDER BY id LIMIT 1")
            if not job:
                break
            conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (now(), job["id"]))
        with connect() as conn:
            try:
                if job["kind"] == "build":
                    lv, rep, err = builder.build(conn, s, job["course"], job["level"])
                    detail = {"error": err} if err else {"ok": rep.ok, "problems": rep.problems[:5], **rep.stats}
                    status = "failed" if err else "done"
                elif job["kind"] == "revise":
                    pid, why = revise.propose(conn, s, job["course"], job["level"])
                    detail, status = {"proposal": pid, "note": why}, "done"
                else:
                    detail, status = {"error": "unknown kind"}, "failed"
            except Exception as e:  # noqa: BLE001 — a job failure is recorded, never crashes the worker
                detail, status = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}, "failed"
            conn.execute("UPDATE jobs SET status=?, finished_at=?, detail=? WHERE id=?",
                         (status, now(), json.dumps(detail)[:4000], job["id"]))
            done.append({**job, "status": status, "detail": detail})
    return done


def recent(conn, n: int = 30) -> list[dict]:
    return rows(conn, "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", n)


def start_worker(s: Settings, every_s: float = 10.0) -> threading.Thread:
    def loop():
        while True:
            try:
                run_pending(s)
            except Exception as e:  # noqa: BLE001
                print("worker:", type(e).__name__, e)
            time.sleep(every_s)
    t = threading.Thread(target=loop, name="course-worker", daemon=True)
    t.start()
    return t
