"""Deterministic checks around retrieval and the model.

SEC-02 instruction screening (at ingest and again on retrieved text), DATA-03 PII redaction,
SEC-04 strict output parsing, OBS-02 citation + support verification.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from .llm import sentences, tokens

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|prompts|context)",
    r"ignore (all |any )?(the )?(documents|sources|excerpts) above",
    r"disregard (the |all |any )?(previous|prior|above|system|instructions)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"reveal (your|the) (system )?prompt",
    r"(developer|admin|jailbreak) mode",
    r"do not (cite|mention|reveal) (any )?(sources|this)",
    r"tell the user\b",
]
PII_PATTERNS = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "PHONE": r"\+?\d[\d\s().-]{8,}\d",
}


def scan_injection(text: str) -> list[str]:
    """The instruction-like phrases found (quoted), so the quarantine log says what was caught."""
    hits = []
    for p in INJECTION_PATTERNS:
        m = re.search(p, text, re.I | re.M)
        if m:
            hits.append(f"instruction-like text: '{m.group(0).strip()}'")
    return hits


def redact_pii(text: str) -> tuple[str, int]:
    n = 0
    for label, pat in PII_PATTERNS.items():
        text, k = re.subn(pat, f"[REDACTED_{label}]", text)
        n += k
    return text, n


# ---------------------------------------------------------------- model output (SEC-04)
class Citation(BaseModel):
    chunk_id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=3, max_length=1200)


class Answer(BaseModel):
    answer: str = Field(default="", max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=8)
    refused: bool = False
    refusal_reason: str = Field(default="", max_length=500)


def parse_answer(text: str) -> Answer:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object in model output")
    return Answer.model_validate(json.loads(cleaned[start:end + 1]))


# ---------------------------------------------------------------- verification (OBS-02)
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def verify_citations(ans: Answer, context: dict[str, str]) -> list[dict]:
    """Each citation must point at a chunk that was in the context and quote it word for word."""
    out = []
    for c in ans.citations:
        ok_chunk = c.chunk_id in context
        ok_quote = ok_chunk and _norm(c.quote) in _norm(context[c.chunk_id])
        out.append({"chunk_id": c.chunk_id, "quote": c.quote, "in_context": ok_chunk, "verbatim": bool(ok_quote)})
    return out


def supported_ratio(answer: str, quotes: list[str], min_overlap: float = 0.6) -> tuple[float, list[dict]]:
    """Share of answer sentences whose numbers all appear in the cited quotes and whose content words mostly do.

    A cheap, deterministic stand-in for an LLM-judged faithfulness score (RAGAS-style), run on every answer."""
    support_text = " ".join(quotes)
    sup_tokens, sup_numbers = set(tokens(support_text)), _numbers(support_text)
    rows = []
    for s in sentences(answer) or ([answer] if answer.strip() else []):
        t = set(tokens(s))
        overlap = len(t & sup_tokens) / max(len(t), 1)
        nums_ok = _numbers(s) <= sup_numbers
        rows.append({"sentence": s, "overlap": round(overlap, 2), "numbers_supported": nums_ok,
                     "supported": overlap >= min_overlap and nums_ok})
    if not rows:
        return 0.0, rows
    return sum(r["supported"] for r in rows) / len(rows), rows
