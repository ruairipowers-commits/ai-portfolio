"""Deterministic guardrails around the model.

SEC-02 prompt-injection screening, DATA-03 PII redaction and trader pseudonyms, SEC-04 output validation,
OBS-02 citation checks against the engine's event log, and post-model policy no output can override.
"""
from __future__ import annotations

import json
import re

from .schemas import AlertNarrative

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|above|system)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"reveal (your|the) (system )?prompt",
    r"(approval|developer|admin) mode",
    r"do not (mention|escalate|flag)",
    r"(pre-?cleared|already cleared|compliance (has )?(approved|cleared))",
    r"\b(recommend|suggest|mark)\w*\s+(\w+\s+){0,3}(clos\w*|clear\w*|no issue)",
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
    hits = scan_injection(text)
    n_pii = 0
    if redact:
        text, n_pii = redact_pii(text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    truncated = len(text) > max_chars
    return text[:max_chars], {"injection_suspected": bool(hits), "injection_patterns": hits,
                              "pii_redactions": n_pii, "truncated": truncated}


def pseudonymise(traders: list[str]) -> dict[str, str]:
    """DATA-03: trader ids are replaced by TRADER-n before any model call; the mapping stays local."""
    return {t: f"TRADER-{i}" for i, t in enumerate(dict.fromkeys(traders), start=1)}


def parse_narrative(text: str) -> AlertNarrative:
    """SEC-04: strict parse; raises on anything off-contract (extra keys included)."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in model output")
    return AlertNarrative.model_validate(json.loads(cleaned[start: end + 1]))


def check_citations(n: AlertNarrative, alert: dict, facts: dict, rel_tol: float = 0.005) -> list[str]:
    """OBS-02: cited events must belong to the alert; every figure must exist in the facts with the same value."""
    errors = []
    allowed = set(alert["event_ids"])
    bad = [e for e in n.cited_events if e not in allowed]
    if bad:
        errors.append(f"cited events not in this alert: {bad[:5]}")
    if n.alert_id != alert["alert_id"]:
        errors.append(f"alert id {n.alert_id!r} does not match {alert['alert_id']!r}")
    if n.pattern != alert["pattern"]:
        errors.append(f"pattern {n.pattern!r} does not match {alert['pattern']!r}")
    for f in n.figures:
        if f.name not in facts:
            errors.append(f"unknown figure '{f.name}'")
            continue
        truth = facts[f.name]
        if isinstance(truth, (int, float)) and not isinstance(truth, bool):
            try:
                v = float(f.value)
            except (TypeError, ValueError):
                errors.append(f"{f.name}: non-numeric {f.value!r}")
                continue
            if abs(v - truth) > max(abs(truth) * rel_tol, 1e-6):
                errors.append(f"{f.name}: cited {v} but the event log says {truth}")
        elif str(f.value).lower() != str(truth).lower():
            errors.append(f"{f.name}: cited {f.value!r} but the event log says {truth!r}")
    # numbers written in the summary must also appear among the facts (no invented figures in prose)
    nums = {round(float(x), 4) for x in re.findall(r"(?<![\w-])\d+(?:\.\d+)?", n.summary)}
    known = {round(float(v), 4) for v in facts.values() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    known |= {float(i) for i in range(0, 11)}            # small counting words ("3 orders", "step 2")
    stray = sorted(nums - known)
    if stray:
        errors.append(f"summary states numbers not in the facts: {stray[:5]}")
    return errors


def apply_policy(suggestion: str, severity: str, flags: dict, policy: dict) -> tuple[str, list[str]]:
    """Rules no model output can override. Returns (final suggestion, reasons)."""
    reasons, final = [], suggestion
    if policy.get("escalate_on_injection") and flags.get("injection_suspected"):
        if final != "ESCALATE":
            reasons.append("Order memos tried to influence the review (possible prompt injection)")
        final = "ESCALATE"
    if final == "CLOSE" and severity in policy.get("no_close_suggestion_on", ["high"]):
        reasons.append(f"CLOSE is not a permitted suggestion for {severity}-severity alerts")
        final = "ESCALATE"
    return final, reasons


def fallback_narrative(alert: dict, reason: str) -> AlertNarrative:
    return AlertNarrative(alert_id=alert["alert_id"], pattern=alert["pattern"],
                          summary=f"Automated narrative unavailable: {reason}", cited_events=alert["event_ids"][:1],
                          figures=[{"name": "event_count", "value": len(alert["event_ids"])}],
                          observations=[reason], suggested_disposition="ESCALATE", confidence=0.0)
