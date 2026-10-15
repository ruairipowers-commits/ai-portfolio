"""Draft a level with the writer model, check it, and hold it for the owner (HITL-02).

The writer gets the level's required sections, the time budget, the quiz size and the source page. Its reply must
validate as schemas.Level; code then overwrites the fields a model must never set (course, level, version, status,
provenance, source hash) and runs every content check. A failing draft is regenerated once with the failures in
the request, then saved as a flagged draft. Nothing is published here: `publish` is the owner's action.
"""
from __future__ import annotations

import os

from . import ai, catalog, checks, mailer, telemetry
from .config import Settings
from .schemas import Level, Provenance, Source
from .store import approval, now

NO_WRITER = ("no writer model: COURSE_WRITER_MODEL isn't set, and the offline mock only writes placeholder text. "
             "Set it (e.g. local-qwen), restart, then use Draft now on the owner page.")

GUIDE = {
    "concept": "What it is, at a high level, in plain words; the one problem it solves.",
    "history": "Where it came from and how it is used today (only facts you are sure of).",
    "business": "How it fits business users: who touches it, what decisions or work it supports.",
    "use_cases": "4–6 key use cases as a list.",
    "pros_cons": "A two-column table of pros and cons.",
    "resources": "Key resources for further learning: the official docs first (given), then 2–4 more, https only.",
    "hello_world": "Introduce the hello-world project in the `project` field (one paragraph here).",
    "interview": "How to discuss it well in interviews: 4–6 likely questions, what a strong answer includes, one pitfall.",
    "recap": "Five bullets recapping the Familiar level.",
    "core_terms": "The 10 core terms, each with a one-line definition and a tiny example.",
    "setup": "A setup checklist (local or free tier) ending with 'You are ready when …'.",
    "guided_project": "Introduce the guided project in `project` (5–7 steps, checkpoints, expected output).",
    "mistakes": "Common mistakes and how to debug each.",
    "cheat_sheet": "A one-page cheat sheet of the commands, syntax or settings used daily.",
    "next_steps": "What to learn next, with the official docs link.",
    "modules": "One paragraph introducing the 4–5 modules in `modules` (each: body, exercise, 5+ check questions).",
    "production": "Production concerns: performance, cost, security and governance.",
    "alternatives": "A comparison table with 2–4 alternatives and when not to use this tool.",
    "in_portfolio": "How this portfolio uses it (from the source's 'In this portfolio' section).",
    "capstone": "Introduce the capstone in `project`: requirements, a self-check rubric, extension ideas.",
    "further_learning": "Advanced docs, specs, talks and communities, with the official docs link.",
}


def request(course: catalog.Course, level: str, s: Settings, fix: list[str] | None = None) -> dict:
    cfg = s.level(level)
    n = cfg["quiz"]["questions"]
    req = {
        "course": {"slug": course.slug, "title": course.title, "category": course.category, "docs": course.docs},
        "level": level, "minutes": cfg["minutes"], "project_minutes": cfg["project_minutes"],
        "sections": [{"id": sid, "covers": GUIDE[sid]} for sid in cfg["sections"]],
        "quiz_questions": n * s["quizzes"]["generated_bank_factor"],
        "modules": cfg.get("modules"),
        "source": {"page": course.source_page, "markdown": course.source_md},
        "schema": Level.model_json_schema(),
    }
    if fix:
        req["fix"] = fix
    return req


def build(conn, s: Settings, slug: str, level: str) -> tuple[Level | None, checks.Report | None, str]:
    """Draft, check, save as a draft, tell the owner. Returns (level, report, error)."""
    course = catalog.all_courses(conn).get(slug)
    if not course:
        return None, None, "unknown course"
    if ai.placeholder_writer_blocked(s):
        # Live service, no real writer configured: write nothing rather than a placeholder that would pass the
        # checks and look publishable. The level stays "being prepared"; the owner page says why.
        telemetry.record("build", status="failed", flags=["no_writer_model"])
        return None, None, NO_WRITER
    # never fall back to the mock writer on the live service: a failed call is better than placeholder text
    fallback = s["build"]["fallback_alias"]
    if ai.live() and ai.is_placeholder(fallback) and os.getenv("COURSE_ALLOW_MOCK_WRITER") != "1":
        fallback = None
    fix, last_err, lv, rep, spent = None, "", None, None, 0.0
    for _ in range(1 + s["build"]["regenerate_on_fail"]):
        res = ai.call(conn, s, "build", "writer", s["build"]["writer_alias"], request(course, level, s, fix), Level,
                      s["cost"]["max_usd_per_build"] - spent, s["build"]["max_output_tokens"],
                      fallback=fallback)
        spent += res.cost_usd
        if res.value is None:
            last_err = res.error
            fix = [res.error]
            continue
        lv = res.value.model_copy(update={
            "course": slug, "level": level, "version": catalog.next_version(slug, level), "status": "draft",
            "source": Source(page=course.source_page, sha=course.source_sha, docs=course.docs),
            "provenance": Provenance(written_by=f"{s['build']['writer_alias']} → {res.model}", prompt_hash=res.prompt_hash),
        })
        rep = checks.check_level(lv, course, s)
        if rep.ok:
            break
        fix = rep.problems
    if lv is None:
        telemetry.record("build", status="failed", flags=["no_valid_draft"])
        return None, None, last_err or "no valid draft"
    if not rep.ok:
        lv = lv.model_copy(update={"provenance": lv.provenance.model_copy(
            update={"note": "FAILED CHECKS: " + "; ".join(rep.problems[:5])})})
    catalog.save_level(lv)
    mailer.draft_ready(conn, s, slug, level, rep.ok, rep.problems)
    telemetry.record("build", items=1, status="ok" if rep.ok else "failed", cost_usd=spent,
                     flags=[] if rep.ok else ["checks_failed"], detail={"level": level})
    return lv, rep, ""


def publish(conn, s: Settings, slug: str, level: str, actor: str) -> tuple[bool, list[str]]:
    """The owner publishes a draft. Checks run again here; a failing draft can't be published."""
    telemetry.require_enabled("publish", actor=actor)
    lv = catalog.load_level(slug, level, include_drafts=True)
    if not lv or lv.status != "draft":
        return False, ["no draft to publish"]
    course = catalog.all_courses(conn).get(slug)
    rep = checks.check_level(lv, course, s)
    if not rep.ok:
        return False, rep.problems
    lv = lv.model_copy(update={"status": "published", "provenance": lv.provenance.model_copy(
        update={"approved_by": actor, "approved_at": now(), "note": ""})})
    catalog.save_level(lv)
    approval(conn, actor, "level", f"{slug}:{level}:v{lv.version}", "publish")
    telemetry.record("publish", actor=actor, items=1, detail={"level": level})
    return True, []


def reject(conn, s: Settings, slug: str, level: str, actor: str, note: str = "") -> bool:
    lv = catalog.load_level(slug, level, include_drafts=True)
    if not lv or lv.status != "draft":
        return False
    catalog.save_level(lv.model_copy(update={"status": "rejected", "provenance": lv.provenance.model_copy(
        update={"note": f"rejected by {actor}: {note}"[:300]})}))
    approval(conn, actor, "level", f"{slug}:{level}:v{lv.version}", "reject", note)
    return True
