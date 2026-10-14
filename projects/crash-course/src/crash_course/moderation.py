"""Topic suggestions: rules first, then a model's assessment, then the owner. Nothing is created without approval.

1. screen (code)   length, rate limit, blocked terms, contact details, a bare personal name, near-duplicates.
                   A rule "reject" never reaches a model; the owner still sees it in the queue.
2. assess (model)  a fixed-schema assessment (schemas.Assessment) of the delimited, untrusted text.
3. merge (code)    the final recommendation is the MORE severe of rules and model: a model can raise concern but
                   can never clear what a rule flagged, and text claiming to be an approval changes nothing.
4. owner (human)   an email with signed approve / reject links and the operator queue (HITL-02).
"""
from __future__ import annotations

import json
import re

from . import ai, catalog, mailer, telemetry
from .config import Settings
from .schemas import Assessment
from .store import insert, j, now, one

SEVERITY = {"approve-recommended": 0, "needs-review": 1, "reject-recommended": 2}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+?\d[\s().-]?){9,}")
NAME = re.compile(r"^(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){1,2}$")
TECH_HINT = re.compile(r"(?i)\b(api|sdk|sql|ml|ai|db|js|py|cloud|data|web|app|apps|framework|library|language|"
                       r"server|kit|ops|lang|script|graph|stack|engine|studio|code|net|hub|flow|base|forms?|"
                       r"apache|google|microsoft|amazon|aws|azure|adobe|oracle|ibm|meta|apple|atlassian|salesforce|"
                       r"hashicorp|mozilla|linux|github|gitlab)\b")


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in {"basics", "101", "intro", "for",
            "beginners", "the", "and", "to", "of", "a", "an", "in", "with", "how", "learn", "course", "crash"}}


def duplicate_of(text: str, courses: dict, threshold: float = 0.5) -> str | None:
    """The existing course the suggestion mostly names: "Docker for beginners" → docker, "Advanced pandas" → pandas,
    but not "Rust for Python developers" (token Jaccard against the course slug, title and aliases)."""
    t = tokens(text)
    if not t:
        return None
    best, score = None, 0.0
    for c in courses.values():
        for n in (c.slug.replace("-", " "), c.title, *c.aliases):
            ct = tokens(n)
            if ct and t & ct:
                sc = len(t & ct) / len(t | ct)
                if sc > score:
                    best, score = c.slug, sc
    return best if score >= threshold else None


def screen(text: str, s: Settings, courses: dict) -> dict:
    m = s["moderation"]
    cats, reasons, action = set(), [], "ok"
    clean = text.strip()
    low = catalog.norm(clean)
    if not (m["min_chars"] <= len(clean) <= m["max_chars"]):
        return {"action": "reject", "categories": ["format"], "reasons": [f"length must be {m['min_chars']}–"
                f"{m['max_chars']} characters"], "duplicate_of": None}
    for term, cat, act in s.blocked:
        if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", low):
            cats.add(cat)
            if act == "reject":
                action = "reject"
            elif action == "ok":
                action = "review"
    if EMAIL.search(clean) or PHONE.search(clean):
        cats.add("personal_data")
        action = "reject"
        reasons.append("contains contact details")
    if NAME.match(clean) and not TECH_HINT.search(clean) and not duplicate_of(clean, courses):
        cats.add("personal_data")
        action = "reject" if action == "reject" else "review"
        reasons.append("looks like a person's name, not a technology")
    if cats - {"personal_data"}:
        reasons.append("matched screened terms: " + ", ".join(sorted(cats - {"personal_data"})))
    dup = duplicate_of(clean, courses, m["duplicate_threshold"])
    if dup:
        reasons.append(f"close to the existing course '{dup}'")
        if action == "ok":
            action = "review"
    return {"action": action, "categories": sorted(cats), "reasons": reasons, "duplicate_of": dup}


def rule_assessment(scr: dict) -> Assessment:
    return Assessment(verdict="reject-recommended", categories=scr["categories"],
                      reasons=(scr["reasons"] or ["rejected by the screening rules"])[:6],
                      duplicate_of=scr["duplicate_of"], learnable_in_format=False)


def merge(scr: dict, model: Assessment | None) -> Assessment:
    rule_verdict = {"ok": "approve-recommended", "review": "needs-review", "reject": "reject-recommended"}[scr["action"]]
    if model is None:   # model unavailable or invalid: never approve on rules alone
        return Assessment(verdict=max(rule_verdict, "needs-review", key=SEVERITY.get), categories=scr["categories"],
                          reasons=[*scr["reasons"], "no model assessment (unavailable or invalid reply)"][:6],
                          duplicate_of=scr["duplicate_of"])
    verdict = max(rule_verdict, model.verdict, key=SEVERITY.get)
    if scr["duplicate_of"] and verdict == "approve-recommended":
        verdict = "needs-review"
    if not model.learnable_in_format and verdict == "approve-recommended":
        verdict = "needs-review"
    return model.model_copy(update={
        "verdict": verdict,
        "categories": sorted(set(model.categories) | set(scr["categories"])),
        "reasons": [*scr["reasons"], *model.reasons][:6],
        "duplicate_of": scr["duplicate_of"] or model.duplicate_of,
        "official_docs": model.official_docs if model.official_docs.startswith("https://") else "",
    })


def assess(conn, s: Settings, text: str) -> tuple[Assessment, dict]:
    courses = catalog.all_courses(conn)
    scr = screen(text, s, courses)
    if scr["action"] == "reject":
        telemetry.record("assess", status="ok", items=1, flags=["rule_reject"])
        return rule_assessment(scr), scr
    payload = {"suggestion": text, "existing": [{"slug": c.slug, "title": c.title} for c in courses.values()]}
    res = ai.call(conn, s, "assess", "moderator", s["moderation"]["model_alias"], payload, Assessment,
                  s["cost"]["max_usd_per_assessment"], s["moderation"]["max_output_tokens"])
    return merge(scr, res.value), scr


def suggest(conn, s: Settings, learner_id: int, text: str) -> dict:
    """Store a suggestion, assess it, and ask the owner. Returns the suggestion row."""
    today = now()[:10]
    n = one(conn, "SELECT COUNT(*) n FROM suggestions WHERE learner_id=? AND substr(created_at,1,10)=?",
            learner_id, today)["n"]
    if n >= s["moderation"]["per_learner_per_day"]:
        raise ValueError(f"limit of {s['moderation']['per_learner_per_day']} suggestions a day reached")
    a, scr = assess(conn, s, text)
    sid = insert(conn, "suggestions", learner_id=learner_id, text=text.strip()[:s["moderation"]["max_chars"]],
                 created_at=now(), status="pending", screen=j(scr), assessment=a.model_dump_json())
    mailer.approval_request(conn, s, sid, text, a)
    telemetry.record("suggest", items=1, flags=[a.verdict], detail={"verdict": a.verdict})
    return one(conn, "SELECT * FROM suggestions WHERE id=?", sid)


def approvable(a: Assessment, s: Settings) -> bool:
    """Defence in depth for HITL-02: a topic flagged in a reject category (explicit, hate, harassment, violence,
    self-harm, illegal, personal data, injection) can't be approved by anyone, so a misclick can't publish it."""
    return not (a.verdict == "reject-recommended" and set(a.categories) & set(s["moderation"]["reject_categories"]))


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "course"


def decide(conn, s: Settings, sid: int, decision: str, actor: str, title: str = "", docs: str = "",
           notes: str = "", category: str = "Suggested") -> dict:
    """The owner's decision. Approve creates the course and queues its Familiar level; reject closes it."""
    from . import jobs
    from .store import approval
    row = one(conn, "SELECT * FROM suggestions WHERE id=?", sid)
    if not row:
        raise ValueError("unknown suggestion")
    if row["status"] != "pending":
        return row
    a = Assessment.model_validate_json(row["assessment"])
    telemetry.require_enabled("approve", actor=actor)
    slug = None
    if decision == "approve" and not approvable(a, s):
        raise ValueError("this topic was flagged " + ", ".join(sorted(set(a.categories) & set(s["moderation"]["reject_categories"])))
                         + " and can't be approved; reject it or ask the learner to suggest it differently")
    if decision == "approve":
        if docs and not docs.startswith("https://"):
            raise ValueError("docs link must be https")
        title = (title or a.proposed_title or row["text"]).strip()[:80]
        slug = slugify(title)
        base, i = slug, 2
        while slug in catalog.all_courses(conn):
            slug, i = f"{base}-{i}", i + 1
        outline = "\n".join(f"- {o}" for o in a.proposed_outline)
        insert(conn, "courses", slug=slug, title=title, category=category, summary=(a.proposed_outline or [""])[0],
               docs=docs or a.official_docs, source_text=(notes or "") + ("\n" + outline if outline else ""),
               suggestion_id=sid, created_at=now())
        jobs.enqueue(conn, "build", slug, "familiar")
    conn.execute("UPDATE suggestions SET status=?, decided_by=?, decided_at=?, decision_note=?, course_slug=? "
                 "WHERE id=?", ("approved" if decision == "approve" else "rejected", actor, now(), notes[:500], slug,
                                sid))
    approval(conn, actor, "suggestion", str(sid), decision, title)
    telemetry.record("approve", actor=actor, items=1, detail={"decision": decision, "kind": "suggestion"})
    if s["approvals"]["notify_suggester"]:
        mailer.suggestion_outcome(conn, s, row["learner_id"], row["text"], decision, slug)
    return one(conn, "SELECT * FROM suggestions WHERE id=?", sid)


def parse(row: dict) -> dict:
    out = dict(row)
    out["assessment"] = json.loads(row["assessment"]) if row.get("assessment") else {}
    out["screen"] = json.loads(row["screen"]) if row.get("screen") else {}
    return out
