"""Deterministic checks around the model: untrusted text in (SEC-02), schema out (SEC-04), every claim checked against
the rows it came from (OBS-02). The model may write sentences; it may not introduce a number, a cost or an outcome.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

INJECTION = [
    r"ignore (all |any |the )?(previous|prior|above|earlier)?\s*(instructions|data|facts|rules)",
    r"disregard (the |all )?(previous|prior|above|system|data)",
    r"\byou are now\b", r"^\s*(system|assistant)\s*:", r"reveal (your|the) (system )?prompt",
    r"\bsay (that )?this launch\b", r"\b(report|state|claim) (that )?(it|this) (failed|succeeded|was cancelled)",
    r"(developer|admin|god) mode",
]
OUTCOME_WORDS = {
    "failure": r"\b(fail(ed|ure|s)?|lost|explod\w*|anomal\w*)\b",
    "success": r"\b(succeed(ed|s)?|successful(ly)?|reached orbit)\b",
    "cancelled": r"\b(cancel+ed|scrubbed for good|abandoned)\b",
}


class Citation(BaseModel):
    field: str
    value: str | int | float | bool | None


class Summary(BaseModel):
    subject: str
    text: str = Field(min_length=1, max_length=1800)
    citations: list[Citation] = Field(default_factory=list)


def scan(text: str) -> list[str]:
    return [p for p in INJECTION if re.search(p, text or "", re.I | re.M)]


def sanitize(text: str | None, max_chars: int) -> tuple[str, dict]:
    """Untrusted text (a mission description) made safe to place inside delimiters, plus flags."""
    text = text or ""
    hits = scan(text)
    clean = text.replace("<", "&lt;").replace(">", "&gt;")[:max_chars]
    return clean, {"injection_suspected": bool(hits), "patterns": hits, "truncated": len(text) > max_chars}


def parse(reply: str) -> Summary:
    """SEC-04: strict parse into the schema; anything else is rejected."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("no JSON object in the reply")
    return Summary.model_validate(json.loads(t[s:e + 1]))


def _numbers(text: str) -> set[float]:
    return {float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", text or "")}


def allowed_numbers(facts) -> set[float]:
    """Every number that appears anywhere in the facts (dates contribute their year, month and day)."""
    return _numbers(json.dumps(facts, default=str))


def check(summary: Summary, facts: dict) -> list[str]:
    """Problems with a draft; an empty list means it is accepted."""
    problems = []
    flat = _flatten(facts)
    for c in summary.citations:
        if c.field not in flat:
            problems.append(f"cites unknown field '{c.field}'")
        elif str(c.value).strip().lower() != str(flat[c.field]).strip().lower():
            problems.append(f"cites {c.field}={c.value!r} but the data says {flat[c.field]!r}")
    stray = sorted(_numbers(summary.text) - allowed_numbers(facts))
    if stray:
        problems.append(f"numbers not in the data: {', '.join(f'{n:g}' for n in stray[:6])}")
    outcome = str(flat.get("launch.outcome", flat.get("outcome", ""))).lower()
    if outcome == "success" and re.search(OUTCOME_WORDS["failure"], summary.text, re.I):
        problems.append("says the launch failed, but the data says it succeeded")
    if outcome in ("failure", "partial") and re.search(OUTCOME_WORDS["success"], summary.text, re.I) \
            and not re.search(OUTCOME_WORDS["failure"], summary.text, re.I):
        problems.append("says the launch succeeded, but the data says it did not")
    if outcome == "pending" and re.search(OUTCOME_WORDS["cancelled"] + "|" + OUTCOME_WORDS["failure"], summary.text, re.I):
        problems.append("says an upcoming launch failed or was cancelled; the data says it is still scheduled")
    if re.search(r"\$\s?\d|\bcost(s|ing)?\b|\bprice\b", summary.text, re.I) and "cost" not in flat:
        problems.append("mentions a cost, but no published cost is in the data")
    return problems


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out
