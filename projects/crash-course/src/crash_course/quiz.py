"""Quizzes: drawn, shuffled and scored on the server. The browser only ever gets a token, prompts and options in a
shuffled order. Which option is correct stays in the YAML on the server; the attempt row stores the shuffle so a
submitted position maps back to the real option. Retries are unlimited and draw a fresh sample from the bank.
"""
from __future__ import annotations

import json
import random
import secrets
from datetime import datetime, timedelta, timezone

from . import telemetry, tracker
from .config import Settings
from .store import insert, now, one
from .tracker import NotAllowed

_rng = random.SystemRandom()


def _bank(lv, part: str):
    if part == "final":
        return lv.quiz
    if part.startswith("module:"):
        m = next((m for m in lv.modules if m.id == part.split(":", 1)[1]), None)
        if m:
            return m.check
    raise NotAllowed("unknown quiz")


def _size(s: Settings, level: str, part: str) -> tuple[int, int]:
    cfg = s.level(level)
    if part == "final":
        return cfg["quiz"]["questions"], cfg["quiz"]["pass_pct"]
    return cfg["modules"]["check_questions"], cfg["modules"]["check_pass_pct"]


def start(conn, s: Settings, learner_id: int, course: str, level: str, part: str = "final") -> dict:
    """A new attempt: returns the public view only (token, prompts, shuffled options)."""
    lv = tracker.require_open(conn, learner_id, course, level)
    bank = _bank(lv, part)
    n, _ = _size(s, level, part)
    picked = _rng.sample(bank, min(n, len(bank)))
    orders = {}
    for q in picked:
        order = list(range(len(q.options)))
        if s["quizzes"]["shuffle_options"]:
            _rng.shuffle(order)
        orders[q.id] = order
    token = secrets.token_urlsafe(18)
    insert(conn, "attempts", token=token, learner_id=learner_id, course=course, level=level, part=part,
           version=lv.version, question_ids=json.dumps([q.id for q in picked]), option_orders=json.dumps(orders),
           started_at=now())
    return {"token": token, "course": course, "level": level, "part": part, "pass_pct": _size(s, level, part)[1],
            "questions": [{"id": q.id, "prompt": q.prompt, "options": [q.options[i] for i in orders[q.id]]}
                          for q in picked]}


def submit(conn, s: Settings, learner_id: int, token: str, answers: dict[str, int]) -> dict:
    """Score an attempt. `answers` maps question id → the position the learner chose in the shuffled list."""
    a = one(conn, "SELECT * FROM attempts WHERE token=?", token)
    if not a or a["learner_id"] != learner_id:
        raise NotAllowed("unknown attempt")
    if a["submitted_at"]:
        raise NotAllowed("this attempt was already submitted; start a new one")
    started = datetime.fromisoformat(a["started_at"])
    if datetime.now(timezone.utc) - started > timedelta(minutes=s["quizzes"]["attempt_ttl_minutes"]):
        raise NotAllowed("this attempt expired; start a new one")
    lv = tracker.require_open(conn, learner_id, a["course"], a["level"])   # still unlocked and published
    bank = {q.id: q for q in _bank(lv, a["part"])}
    orders = json.loads(a["option_orders"])
    results, score, chosen = [], 0, {}
    for qid in json.loads(a["question_ids"]):
        q = bank.get(qid)
        if q is None:          # the level was revised mid-attempt; drop the question rather than guess
            continue
        pos = answers.get(qid)
        real = orders[qid][pos] if isinstance(pos, int) and 0 <= pos < len(orders[qid]) else None
        ok = real == q.answer
        score += ok
        chosen[qid] = real
        item = {"id": qid, "prompt": q.prompt, "correct": ok}
        if not ok or s["quizzes"]["show_explanations"] == "all":
            item["explanation"] = q.explanation
        results.append(item)
    total = len(results)
    pct = round(100 * score / total) if total else 0
    passed = pct >= _size(s, a["level"], a["part"])[1]
    conn.execute("UPDATE attempts SET submitted_at=?, answers=?, score=?, total=?, passed=? WHERE id=?",
                 (now(), json.dumps(chosen) if s["privacy"]["store_answers"] else None, score, total, int(passed),
                  a["id"]))
    p = tracker.progress(conn, learner_id, a["course"], a["level"])
    if a["part"] == "final":
        conn.execute("UPDATE progress SET quiz_best=MAX(quiz_best, ?), quiz_passed_at=CASE WHEN ? AND quiz_passed_at "
                     "IS NULL THEN ? ELSE quiz_passed_at END WHERE learner_id=? AND course=? AND level=?",
                     (pct, int(passed), now(), learner_id, a["course"], a["level"]))
    elif passed:
        done = set(json.loads(p["modules_passed"] or "[]")) | {a["part"]}
        conn.execute("UPDATE progress SET modules_passed=? WHERE learner_id=? AND course=? AND level=?",
                     (json.dumps(sorted(done)), learner_id, a["course"], a["level"]))
    after = tracker.maybe_complete(conn, s, learner_id, a["course"], a["level"])
    telemetry.record("quiz", items=score, rows_in=total, status="ok",
                     detail={"level": a["level"], "passed": passed, "pct": pct})
    return {"score": score, "total": total, "pct": pct, "passed": passed, "results": results,
            "pass_pct": _size(s, a["level"], a["part"])[1], "level_complete": bool(after.get("completed_at")),
            "course": a["course"], "level": a["level"], "part": a["part"]}


def item_stats(conn, course: str, level: str) -> dict[str, dict]:
    """Per question: attempts and share missed (for the feedback loop, HITL-03)."""
    stats: dict[str, dict] = {}
    for a in conn.execute("SELECT question_ids, answers FROM attempts WHERE course=? AND level=? AND submitted_at "
                          "IS NOT NULL AND answers IS NOT NULL", (course, level)).fetchall():
        chosen = json.loads(a["answers"])
        for qid, real in chosen.items():
            st = stats.setdefault(qid, {"n": 0, "missed": 0})
            st["n"] += 1
            st["chosen"] = st.get("chosen", {})
            st["chosen"][str(real)] = st["chosen"].get(str(real), 0) + 1
    from . import catalog
    lv = catalog.load_level(course, level, include_drafts=True)
    if lv:
        for q in lv.all_questions():
            if q.id in stats:
                st = stats[q.id]
                st["missed"] = st["n"] - st["chosen"].get(str(q.answer), 0)
                st["missed_pct"] = round(100 * st["missed"] / st["n"])
    return stats
