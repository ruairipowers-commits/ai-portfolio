"""The feedback loop (HITL-03): learner feedback + quiz item statistics → proposed edits → owner → new draft.

- Feedback is untrusted text. It reaches the reviser delimited, and code drops any edit that would change an
  answer key (those are listed for the owner to check by hand, never applied).
- A question missed by at least `missed_question_pct` of attempts (with `min_attempts`) is flagged even with no
  written feedback.
- The owner accepts or rejects each edit. Accepted edits become a new draft version, which goes through the same
  content checks and the same publish step as any other draft, and each accepted edit is added to the eval set
  (warehouse/evals/feedback.yaml) so a later rewrite can't silently undo it.
"""
from __future__ import annotations

import json
import re

import yaml

from . import ai, catalog, telemetry
from .config import Settings, data_dir
from .quiz import item_stats
from .schemas import Edit, Proposal
from .store import approval, insert, now, one, rows

# an edit that would change which option is correct (held for the owner to check by hand, never applied)
KEY_CHANGE = re.compile(r"(?i)\b(change|switch|swap|set|make|mark|flip|replace)\b.{0,40}\b(correct|right|answer key|"
                        r"the answer|answer to)\b")


def signals(conn, s: Settings, course: str, level: str) -> tuple[list[dict], dict]:
    fb = rows(conn, "SELECT id, rating, unclear, add_text FROM feedback WHERE course=? AND level=? AND status='new' "
                    "ORDER BY id", course, level)
    r = s["revisions"]
    stats = {qid: st for qid, st in item_stats(conn, course, level).items()
             if st["n"] >= r["min_attempts"] and st.get("missed_pct", 0) >= r["missed_question_pct"]}
    return fb, stats


def propose(conn, s: Settings, course: str, level: str) -> tuple[int | None, str]:
    lv = catalog.load_level(course, level)
    if not lv:
        return None, "no published level"
    fb, stats = signals(conn, s, course, level)
    if len(fb) < s["revisions"]["min_feedback"] and not stats:
        return None, f"not enough signal ({len(fb)} feedback, {len(stats)} flagged questions)"
    payload = {"level": {"course": course, "level": level, "version": lv.version,
                         "sections": [{"id": x.id, "heading": x.heading, "body": x.body} for x in lv.sections],
                         "project": lv.project.model_dump(),
                         "quiz": [q.model_dump() for q in lv.all_questions()]},
               "feedback": [{"id": f["id"], "rating": f["rating"], "unclear": f["unclear"] or "",
                             "add": f["add_text"] or ""} for f in fb],
               "stats": stats}
    res = ai.call(conn, s, "revise", "reviser", s["revisions"]["reviser_alias"], payload, Proposal,
                  s["cost"]["max_usd_per_revision"], 4000)
    if res.value is None:
        return None, res.error
    targets = {x.id for x in lv.sections} | {"project"} | {f"quiz:{q.id}" for q in lv.all_questions()}
    kept, held = [], []
    for e in res.value.edits:
        if e.target not in targets:
            continue
        (held if e.touches_answer_key or (e.target.startswith("quiz:") and KEY_CHANGE.search(e.change)) else kept).append(e)
    if not kept and not held:
        return None, "no applicable edits"
    pid = insert(conn, "proposals", course=course, level=level, version=lv.version, created_at=now(),
                 payload=json.dumps({"summary": res.value.summary, "edits": [e.model_dump() for e in kept],
                                     "held": [e.model_dump() for e in held],
                                     "feedback_ids": [f["id"] for f in fb]}))
    if fb:
        conn.execute(f"UPDATE feedback SET status='proposed' WHERE id IN ({','.join('?' * len(fb))})",
                     [f["id"] for f in fb])
    telemetry.record("revise", items=len(kept), rows_in=len(fb) + len(stats), flags=["held_key_edit"] if held else [])
    return pid, ""


def apply(lv, edits: list[Edit]):
    """A new draft with the accepted edits applied as clearly marked clarifications (the owner can polish the
    wording in the YAML before publishing)."""
    secs = {x.id: x for x in lv.sections}
    quiz = {q.id: q for q in lv.quiz}
    mods = list(lv.modules)
    project = lv.project
    for e in edits:
        if e.target in secs:
            sec = secs[e.target]
            secs[e.target] = sec.model_copy(update={"body": sec.body.rstrip() + f"\n\n> **Clarified:** {e.change}"})
        elif e.target == "project":
            project = project.model_copy(update={"steps": [*project.steps, e.change]})
        elif e.target.startswith("quiz:"):
            qid = e.target.split(":", 1)[1]
            if qid in quiz:
                q = quiz[qid]
                quiz[qid] = q.model_copy(update={"explanation": (q.explanation.rstrip() + " " + e.change)[:600]})
            for i, m in enumerate(mods):
                if any(q.id == qid for q in m.check):
                    mods[i] = m.model_copy(update={"check": [q.model_copy(update={"explanation": (
                        q.explanation.rstrip() + " " + e.change)[:600]}) if q.id == qid else q for q in m.check]})
    return lv.model_copy(update={
        "version": catalog.next_version(lv.course, lv.level), "status": "draft",
        "sections": [secs[x.id] for x in lv.sections], "quiz": [quiz[q.id] for q in lv.quiz],
        "modules": mods, "project": project,
        "provenance": lv.provenance.model_copy(update={"note": f"revision of v{lv.version} from learner feedback",
                                                       "approved_by": "", "approved_at": ""})})


def decide(conn, s: Settings, pid: int, accepted: list[int], actor: str) -> dict:
    p = one(conn, "SELECT * FROM proposals WHERE id=?", pid)
    if not p or p["status"] != "pending":
        raise ValueError("no pending proposal")
    telemetry.require_enabled("approve", actor=actor)
    payload = json.loads(p["payload"])
    edits = [Edit.model_validate(e) for i, e in enumerate(payload["edits"]) if i in accepted]
    status = "rejected"
    if edits:
        lv = catalog.load_level(p["course"], p["level"])
        draft = apply(lv, edits)
        catalog.save_level(draft)
        _add_eval_cases(p["course"], p["level"], draft.version, edits)
        status = "accepted"
    conn.execute("UPDATE proposals SET status=?, decided_by=?, decided_at=? WHERE id=?", (status, actor, now(), pid))
    approval(conn, actor, "proposal", str(pid), status, f"{len(edits)} of {len(payload['edits'])} edits")
    telemetry.record("approve", actor=actor, items=len(edits), detail={"kind": "proposal", "decision": status})
    return {"status": status, "applied": len(edits)}


def _add_eval_cases(course: str, level: str, version: int, edits: list[Edit]) -> None:
    path = data_dir() / "warehouse" / "evals" / "feedback.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = yaml.safe_load(path.read_text()) if path.exists() else []
    for e in edits:
        cases.append({"course": course, "level": level, "since_version": version, "target": e.target,
                      "must_contain": e.change[:80], "why": e.reason})
    path.write_text(yaml.safe_dump(cases, sort_keys=False, allow_unicode=True))
