"""The glossary: highlight a word on a course page to see what it means, ask for an explanation, add it to the
glossary or suggest it as a course.

Entries:
  bundled   config/glossary.yaml — reviewed in git like the courses, so they count as approved
  approved  rows the owner approved (owner page): shown to everyone, and as hover definitions on course pages
  draft     an AI answer to a learner's "Find out more", kept so the next learner asking costs nothing; shown labelled
            "AI-generated, not reviewed" until the owner approves (and may edit) it or rejects it

The one model call a learner can trigger (Ruairi's decision, 4 November 2026): "Find out more" — signed-in learners
only, rate-limited per minute and per day, a per-answer budget, the governance kill switch, the term screened before
any model sees it, the reply validated against `GlossaryAnswer`, and a cached answer reused instead of a new call.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import yaml
from pydantic import Field, ValidationError

from . import ai, mock as _mock
from .config import Settings, root
from .moderation import EMAIL, PHONE
from .schemas import Strict
from .store import approval, now, one, rows

TERM_RX = re.compile(r"^[\w][\w .+#/&()'’-]*$")


class GlossaryAnswer(Strict):
    is_term: bool = True                                   # false: not a term worth defining (a typo, a sentence)
    term: str = Field(min_length=1, max_length=60)
    expansion: str = Field(default="", max_length=120)     # what an acronym stands for
    definition: str = Field(min_length=10, max_length=300)
    more: str = Field(default="", max_length=1500)         # how it works / why it matters, plain text
    course_worthy: bool = False                            # big enough to be its own crash course


class Refused(ValueError):
    """The term can't be looked up (format, screened words, rate limit)."""


def key(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip()).casefold()


def bundled() -> dict[str, dict]:
    p = root() / "config" / "glossary.yaml"
    raw = (yaml.safe_load(p.read_text()) or {}).get("terms", []) if p.exists() else []
    return {key(t["term"]): {"term": t["term"], "expansion": t.get("expansion", ""), "definition": t["definition"],
                             "more": t.get("more", ""), "status": "approved", "source": "bundled"} for t in raw}


def check_term(term: str, s: Settings) -> str:
    """The same screen as topic suggestions, for a short highlighted term. Returns the cleaned term or raises."""
    t = re.sub(r"\s+", " ", (term or "").strip().strip(".,;:!?\"“”"))
    g = s["glossary"]
    if not (2 <= len(t) <= g["max_term_chars"]) or len(t.split()) > g["max_term_words"] or not TERM_RX.match(t):
        raise Refused("highlight a word or short phrase (letters, numbers and simple punctuation)")
    low = key(t)
    if EMAIL.search(t) or PHONE.search(t):
        raise Refused("that looks like contact details")
    if _mock.INJECTION.search(t):
        raise Refused("that isn't a term")
    for word, _cat, action in s.blocked:
        if action == "reject" and re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", low):
            raise Refused("that term can't be looked up here")
    return t


def lookup(conn, term: str) -> dict | None:
    """An approved entry (bundled or owner-approved), else a draft, else None."""
    k = key(term)
    b = bundled().get(k)
    if b:
        return {**b, "key": k}
    r = one(conn, "SELECT * FROM glossary WHERE term_key=? AND status IN ('approved', 'draft')", k)
    return {**r, "key": k} if r else None


def approved_terms(conn, limit: int = 400) -> list[dict]:
    """For hover definitions: every approved entry, longest term first (so 'API gateway' wins over 'API')."""
    out = {k: v for k, v in bundled().items()}
    for r in rows(conn, "SELECT term_key, term, expansion, definition FROM glossary WHERE status='approved'"):
        out.setdefault(r["term_key"], {"term": r["term"], "expansion": r["expansion"], "definition": r["definition"]})
    return sorted(({"term": v["term"], "expansion": v.get("expansion", ""), "definition": v["definition"]}
                   for v in out.values()), key=lambda v: -len(v["term"]))[:limit]


def asks_today(conn, learner_id: int) -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    return one(conn, "SELECT COUNT(*) n FROM glossary_asks WHERE learner_id=? AND at >= ?", learner_id, day)["n"]


def explain(conn, s: Settings, learner_id: int, term: str, course_title: str = "", context: str = "") -> dict:
    """"Find out more". A cached entry is returned as is; otherwise one model call, within the learner's daily limit."""
    t = check_term(term, s)
    hit = lookup(conn, t)
    if hit and hit.get("definition") and (hit.get("more") or hit.get("status") == "draft"):
        return {**hit, "cached": True}                    # a full answer is already there: no model call
    g = s["glossary"]
    if asks_today(conn, learner_id) >= g["per_learner_per_day"]:
        raise Refused(f"you've reached today's limit of {g['per_learner_per_day']} explanations; try again tomorrow")
    conn.execute("INSERT INTO glossary_asks (learner_id, term_key, at) VALUES (?,?,?)", (learner_id, key(t), now()))
    payload = {"term": t, "course": course_title[:80], "context": re.sub(r"\s+", " ", context)[: g["context_chars"]]}
    res = ai.call(conn, s, "glossary_explain", "glossary", g["alias"], payload, GlossaryAnswer,
                  budget_usd=g["max_usd_per_answer"], max_tokens=900)
    if not res.value:
        raise Refused("no explanation is available right now; try again later")
    v = res.value
    if hit and hit.get("status") == "approved":           # keep the reviewed definition; add the AI's "more", labelled
        return {**hit, "more": v.more.strip(), "more_ai": bool(v.more.strip()), "cached": False}
    if not v.is_term:
        return {"term": t, "status": "not_a_term", "definition": "", "expansion": "", "more": ""}
    entry = {"term": t, "expansion": v.expansion.strip(), "definition": v.definition.strip(), "more": v.more.strip(),
             "status": "draft", "source": "ai", "model": res.model, "course_worthy": v.course_worthy}
    if not ai.is_placeholder(g["alias"]):          # never cache the offline placeholder as if it were an answer
        conn.execute("INSERT OR IGNORE INTO glossary (term_key, term, expansion, definition, more, status, source, "
                     "model, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (key(t), t, entry["expansion"], entry["definition"], entry["more"], "draft", "ai", res.model, now()))
    return {**entry, "key": key(t), "cached": False}


def request_add(conn, s: Settings, learner_id: int, term: str, course: str = "") -> str:
    """"Add to glossary": the term goes to the owner (with the AI draft if there is one). Returns what happened."""
    t = check_term(term, s)
    k = key(t)
    if k in bundled() or one(conn, "SELECT 1 FROM glossary WHERE term_key=? AND status='approved'", k):
        return "already in the glossary"
    if one(conn, "SELECT 1 FROM glossary WHERE term_key=? AND status='rejected'", k):
        return "the owner decided not to add this term"
    conn.execute("INSERT OR IGNORE INTO glossary (term_key, term, expansion, definition, more, status, source, "
                 "created_at) VALUES (?,?,?,?,?,?,?,?)", (k, t, "", "", "", "draft", "learner", now()))
    conn.execute("UPDATE glossary SET requested_by=?, requested_at=?, course=? WHERE term_key=? AND requested_at IS NULL",
                 (learner_id, now(), course[:40], k))
    return "sent to the owner for review"


def pending(conn) -> list[dict]:
    """Owner page: requested terms first, then other AI drafts."""
    return rows(conn, "SELECT * FROM glossary WHERE status='draft' ORDER BY requested_at IS NULL, requested_at, "
                      "created_at LIMIT 100")


def decide(conn, term_key: str, decision: str, actor: str, term: str = "", expansion: str = "",
           definition: str = "", more: str = "") -> None:
    r = one(conn, "SELECT * FROM glossary WHERE term_key=?", term_key)
    if not r:
        raise ValueError("no such term")
    if decision == "reject":
        conn.execute("UPDATE glossary SET status='rejected', decided_by=?, decided_at=? WHERE term_key=?",
                     (actor, now(), term_key))
    elif decision == "approve":
        try:
            fixed = GlossaryAnswer(term=(term or r["term"])[:60], expansion=(expansion or "")[:120],
                                   definition=(definition or r["definition"] or "").strip()[:300], more=(more or "")[:1500])
        except ValidationError as e:
            raise ValueError("a definition of at least 10 characters is needed to approve") from e
        conn.execute("UPDATE glossary SET term=?, expansion=?, definition=?, more=?, status='approved', decided_by=?, "
                     "decided_at=? WHERE term_key=?", (fixed.term, fixed.expansion, fixed.definition, fixed.more,
                                                       actor, now(), term_key))
    else:
        raise ValueError("decision must be approve or reject")
    approval(conn, actor, "glossary", term_key, decision)
