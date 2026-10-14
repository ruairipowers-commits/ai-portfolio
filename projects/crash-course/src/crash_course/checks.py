"""Content checks every level must pass before it can be published (OBS-02 grounding, EVAL-02 thresholds, SEC-04).

Code, not a model, decides:
  - schema           the file parses into schemas.Level (done by the loader / parser)
  - sections         every section the level type requires is present, in order; Intermediate has 4–5 modules
  - grounding        each question's `evidence` is a verbatim span (≥ N words) of the source page or the level's own
                     text, and the correct option shares a content word with it
  - quiz validity    unique ids; 3–5 options; no duplicate options; no "all/none of the above"; options short;
                     the bank is big enough that a retry is a different draw
  - duration         reading time + quiz time + project estimate within the level's budget
  - links            https only; the course's official docs link appears in the resources
  - banned content   nothing from config/blocked_terms.txt with action=reject
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import Course, norm
from .config import Settings
from .schemas import Level, Question

STOP = set("""a an the and or of to in on for with by is are was were be been it its this that these those as at from
into than then so not no but if when what which who how why do does did can could should would will your you
they them their there here use used using about over under more most less least very just only also each per via
one two three""".split())
LINK = re.compile(r"\]\((https?://[^)\s]+)\)|(?<![(\w])(https?://[^\s)>\]]+)")


@dataclass
class Report:
    course: str
    level: str
    problems: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, msg: str) -> None:
        self.problems.append(msg)


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def content_words(text: str) -> set[str]:
    toks = (w.rstrip(".-") for w in re.findall(r"[a-z0-9][a-z0-9+#.\-]*", norm(text)))
    return {w for w in toks if (len(w) > 2 or w.isdigit()) and w not in STOP}


def minutes(lv: Level, s: Settings) -> float:
    cfg = s.level(lv.level)
    reading_words = words("\n".join(sec.body for sec in lv.sections) + "\n" + "\n".join(m.body for m in lv.modules))
    quiz_n = cfg["quiz"]["questions"] + sum(len(m.check[: cfg.get("modules", {}).get("check_questions", 0)])
                                            for m in lv.modules)
    module_ex = sum(max(0, m.minutes - words(m.body) / s["reading_wpm"]) for m in lv.modules)
    return reading_words / s["reading_wpm"] + quiz_n * s["seconds_per_question"] / 60 + lv.project.minutes + module_ex


def check_question(q: Question, corpus: str, s: Settings, where: str, r: Report) -> None:
    c = s["checks"]
    ev = norm(q.evidence)
    if len(ev.split()) < c["evidence_min_words"]:
        r.add(f"{where} {q.id}: evidence shorter than {c['evidence_min_words']} words")
    elif ev not in corpus:
        r.add(f"{where} {q.id}: evidence not found verbatim in the source page or the level text")
    opts = [norm(o) for o in q.options]
    if not (c["options"]["min"] <= len(opts) <= c["options"]["max"]):
        r.add(f"{where} {q.id}: {len(opts)} options (allowed {c['options']['min']}–{c['options']['max']})")
    if len(set(opts)) != len(opts):
        r.add(f"{where} {q.id}: duplicate options, so more than one is correct")
    if any(re.search(r"\b(all|none|both) of the (above|these)\b", o) for o in opts):
        r.add(f"{where} {q.id}: 'all/none of the above' option")
    if any(words(o) > c["max_option_words"] for o in q.options):
        r.add(f"{where} {q.id}: an option is longer than {c['max_option_words']} words")
    correct = content_words(q.options[q.answer])
    if correct and len(correct & content_words(q.evidence + " " + q.explanation)) < c["answer_overlap_min"]:
        r.add(f"{where} {q.id}: the correct option shares no content word with its evidence or explanation")


def check_level(lv: Level, course: Course, s: Settings) -> Report:
    r = Report(lv.course, lv.level)
    cfg = s.level(lv.level)
    ids = [sec.id for sec in lv.sections]
    want = cfg["sections"]
    missing = [w for w in want if w not in ids]
    if missing:
        r.add(f"missing sections: {', '.join(missing)}")
    elif [i for i in ids if i in want] != want:
        r.add(f"sections out of order (want {', '.join(want)})")
    if lv.level == "intermediate":
        mc = cfg["modules"]
        if not (mc["min"] <= len(lv.modules) <= mc["max"]):
            r.add(f"{len(lv.modules)} modules (want {mc['min']}–{mc['max']})")
        for m in lv.modules:
            if len(m.check) < mc["check_questions"]:
                r.add(f"module {m.id}: {len(m.check)} check questions (want {mc['check_questions']})")
    elif lv.modules:
        r.add(f"{lv.level} levels have no modules")

    # quiz bank
    qs = lv.all_questions()
    dup = {q.id for q in qs if [x.id for x in qs].count(q.id) > 1}
    if dup:
        r.add(f"duplicate question ids: {', '.join(sorted(dup))}")
    need = cfg["quiz"]["questions"] + s["quizzes"]["bank_min_extra"]
    if len(lv.quiz) < need:
        r.add(f"quiz bank has {len(lv.quiz)} questions; needs at least {need} so retries differ")

    corpus = norm(course.source_text + "\n" + lv.text())
    for q in lv.quiz:
        check_question(q, corpus, s, "quiz", r)
    for m in lv.modules:
        for q in m.check:
            check_question(q, corpus, s, f"module {m.id}", r)

    # time budget
    mins = minutes(lv, s)
    r.stats = {"minutes": round(mins, 1), "budget": cfg["minutes"], "questions": len(lv.quiz),
               "words": words(lv.text())}
    if mins > cfg["minutes"]:
        r.add(f"estimated {mins:.1f} min is over the {cfg['minutes']} min budget")
    if lv.project.minutes > cfg["project_minutes"] * 1.5:
        r.add(f"project estimate {lv.project.minutes} min is far over {cfg['project_minutes']} min")

    # links
    links = [a or b for a, b in LINK.findall(lv.text())]
    local = ("http://localhost", "http://127.0.0.1")        # instructions to open your own app, not outbound links
    bad = [u for u in links if not u.startswith(tuple(f"{sch}://" for sch in s["checks"]["allowed_link_schemes"]))
           and not u.startswith(local)]
    if bad:
        r.add(f"non-https links: {', '.join(bad[:3])}")
    res = lv.section("resources") or lv.section("further_learning") or lv.section("next_steps")
    if course.docs and res and course.docs.rstrip("/") not in res.body:
        r.add("resources don't link the official documentation")

    # banned content
    text = norm(lv.text() + " " + " ".join(o for q in qs for o in q.options))
    for term, cat, action in s.blocked:
        if action == "reject" and cat != "injection" and re.search(rf"\b{re.escape(term)}\b", text):
            r.add(f"contains blocked term ({cat})")
    return r
