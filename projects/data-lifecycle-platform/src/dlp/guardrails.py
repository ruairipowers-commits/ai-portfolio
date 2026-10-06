"""Deterministic guardrails around every model call.

SEC-02 injection screening of untrusted text (vendor pages, dataset cards, owner submissions, user questions),
DATA-03 PII detection and redaction, SEC-04 strict output parsing, OBS-02 grounding checks: every number in an
answer must come from the context packet, and every extracted field must quote its source.
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|above|system)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"\bSYSTEM:",
    r"reveal (your|the) (system )?prompt",
    r"(approval|developer|admin) mode",
    r"do not (mention|tell|report)",
    r"mark (this|it) (dataset )?as (approved|licen[cs]e)",
]
PII_PATTERNS = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "PHONE": r"\+?\d{1,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "CARD": r"\b(?:\d[ -]?){13,16}\b",
}
_HIDDEN = re.compile(r"<(script|style|head)[^>]*>.*?</\1>|<!--.*?-->", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def scan_injection(text: str) -> list[str]:
    return [p for p in INJECTION_PATTERNS if re.search(p, text or "", re.I | re.M)]


def redact_pii(text: str) -> tuple[str, int]:
    n = 0
    for label, pat in PII_PATTERNS.items():
        text, k = re.subn(pat, f"[REDACTED_{label}]", text)
        n += k
    return text, n


def html_to_text(html: str) -> str:
    """Visible-ish text from a vendor page. Hidden elements are KEPT (so injection in them is still scanned)."""
    text = _HIDDEN.sub(" ", html)
    text = re.sub(r"<(br|/p|/li|/h\d|/div|/tr)>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = re.sub(r"&nbsp;", " ", text)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def sanitize_untrusted(text: str, max_chars: int, redact: bool = True) -> tuple[str, dict]:
    """Text safe to place inside delimiters, plus flags for logging and policy."""
    hits = scan_injection(text)
    n_pii = 0
    if redact:
        text, n_pii = redact_pii(text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    truncated = len(text) > max_chars
    return text[:max_chars], {"injection_suspected": bool(hits), "injection_patterns": hits,
                              "pii_redactions": n_pii, "truncated": truncated}


def pii_columns(columns: list[str], configured: list[str]) -> list[str]:
    """Columns that look like personal data, by name (DATA-03)."""
    from . import ontology

    out = []
    for c in columns:
        t = ontology.map_field(c)
        if c.lower() in configured or (t and t.iri.endswith("/PersonalData")):
            out.append(c)
    return out


M = TypeVar("M", bound=BaseModel)


def parse(model: type[M], text: str) -> M:
    """SEC-04: strict parse into the expected schema; raises on anything off-contract."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in model output")
    return model.model_validate(json.loads(cleaned[start: end + 1]))


_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*\.?\d*%?")


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text or ""):
        t = m.rstrip("%").replace(",", "")
        try:
            out.append(float(t))
        except ValueError:
            pass
    return out


def ungrounded_numbers(answer: str, allowed: list[float], rel_tol: float = 0.005) -> list[float]:
    """OBS-02 / NFR-2: numbers in an answer that don't match any number in the context packet.
    Small integers (≤ 31) are allowed as ordinary prose ('3 datasets', '20-day')."""
    bad = []
    for x in numbers_in(answer):
        if abs(x) <= 31 and float(x).is_integer():
            continue
        if not any(abs(x - a) <= max(abs(a) * rel_tol, 0.006) for a in allowed):
            bad.append(x)
    return bad


def quotes_missing(fields: dict[str, dict], source_text: str) -> list[str]:
    """Extraction grounding: each extracted value must carry a quote that appears in the source text."""
    norm = " ".join(source_text.split()).lower()
    missing = []
    for k, f in fields.items():
        q = " ".join(str(f.get("quote", "")).split()).lower()
        if f.get("value") not in (None, "", []) and (not q or q not in norm):
            missing.append(k)
    return missing
