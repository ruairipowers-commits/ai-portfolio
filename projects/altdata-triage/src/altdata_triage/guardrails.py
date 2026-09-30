"""Deterministic guardrails around the model.

SEC-02 prompt-injection screening, DATA-03 PII redaction, SEC-04 output
validation, OBS-02 citation checking, and post-LLM business policy.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .schemas import TriageMemo

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|above|system)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"reveal (your|the) (system )?prompt",
    r"(approval|developer|admin) mode",
    r"do not mention",
]
PII_PATTERNS = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "PHONE": r"\+?\d[\d\s().-]{8,}\d",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
}


def scan_injection(text: str) -> list[str]:
    return [p for p in INJECTION_PATTERNS if re.search(p, text, re.I | re.M)]


def redact_pii(text: str) -> tuple[str, int]:
    n = 0
    for label, pat in PII_PATTERNS.items():
        text, k = re.subn(pat, f"[REDACTED_{label}]", text)
        n += k
    return text, n


def sanitize_untrusted(text: str, max_chars: int, redact: bool = True) -> tuple[str, dict]:
    """Return text safe to place inside delimiters, plus flags for logging/policy."""
    hits = scan_injection(text)
    n_pii = 0
    if redact:
        text, n_pii = redact_pii(text)
    # Neutralise anything that could close our XML-style delimiters.
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    truncated = len(text) > max_chars
    text = text[:max_chars]
    return text, {"injection_suspected": bool(hits), "injection_patterns": hits,
                  "pii_redactions": n_pii, "truncated": truncated}


def parse_memo(text: str) -> TriageMemo:
    """SEC-04: strict parse. Raises ValueError/ValidationError on anything off-contract."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in model output")
    return TriageMemo.model_validate(json.loads(cleaned[start : end + 1]))


def check_citations(memo: TriageMemo, facts: dict, rel_tol: float = 0.005) -> list[str]:
    """OBS-02: every cited metric must exist in the facts with the same value."""
    errors = []
    for ev in memo.evidence:
        if ev.metric not in facts:
            errors.append(f"cited unknown metric '{ev.metric}'")
            continue
        truth = facts[ev.metric]
        if isinstance(truth, (int, float)) and not isinstance(truth, bool):
            try:
                v = float(ev.value)
            except (TypeError, ValueError):
                errors.append(f"{ev.metric}: non-numeric value {ev.value!r}")
                continue
            if abs(v - truth) > max(abs(truth) * rel_tol, 1e-6):
                errors.append(f"{ev.metric}: cited {v} but source is {truth}")
        elif str(ev.value).lower() != str(truth).lower():
            errors.append(f"{ev.metric}: cited {ev.value!r} but source is {truth!r}")
    return errors


def apply_policy(rec: str, facts: dict, flags: dict, policy: dict) -> tuple[str, list[str]]:
    """Business rules that no model output can override. Returns (final_rec, reasons)."""
    reasons: list[str] = []
    final = rec
    if policy.get("escalate_on_injection") and flags.get("injection_suspected"):
        final = "ESCALATE"
        reasons.append("Vendor text contained instruction-like content (possible prompt injection)")
    if facts.get("pii_present") and not facts.get("license_derived_use"):
        allowed = policy.get("pii_without_license_allowed", ["REJECT", "ESCALATE"])
        if final not in allowed:
            reasons.append(f"PII without derived-use license: {final} not allowed")
            final = "ESCALATE"
    if final == "PURSUE":
        if facts.get("rule_score", 0) < policy.get("min_score_for_pursue", 70):
            reasons.append("Rule score below PURSUE threshold")
            final = "PARK"
        elif policy.get("require_point_in_time_for_pursue") and not facts.get("point_in_time", True):
            reasons.append("History not point-in-time")
            final = "PARK"
    return final, reasons


def fallback_memo(vendor_id: str, reason: str) -> TriageMemo:
    return TriageMemo(
        vendor_id=vendor_id, recommendation="ESCALATE", confidence=0.0,
        summary=f"Automated triage unavailable: {reason}",
        risks=[reason], evidence=[{"metric": "vendor_id", "value": vendor_id}],
        next_steps=["Manual review required"],
    )
