"""Deterministic guardrails around the model.

SEC-02 injection screening of the researcher's notes, DATA-03 redaction, SEC-04 strict parsing, OBS-02 figure checks
against the stored run, compliance checks on the memo (net headline, hypothetical-performance disclosures) and the
promotion policy no model output can override.
"""
from __future__ import annotations

import json
import re

from .schemas import ResearchMemo

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|above|system)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"reveal (your|the) (system )?prompt",
    r"(approval|developer|admin) mode",
    r"\b(state|write|say|report)\b[^.\n]{0,30}\bsharpe\b[^.\n]{0,20}\d",
    r"\b(mark|treat)\b[^.\n]{0,20}\b(approved|promoted)\b",
    r"\b(skip|omit|drop|leave out)\b[^.\n]{0,20}\b(disclaimer|disclosure)s?\b",
]
PII_PATTERNS = {"EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+", "PHONE": r"\+?\d[\d\s().-]{8,}\d"}


def scan_injection(text: str) -> list[str]:
    return [p for p in INJECTION_PATTERNS if re.search(p, text, re.I | re.M)]


def sanitize_untrusted(text: str, max_chars: int, redact: bool = True) -> tuple[str, dict]:
    hits = scan_injection(text)
    n = 0
    if redact:
        for label, pat in PII_PATTERNS.items():
            text, k = re.subn(pat, f"[REDACTED_{label}]", text)
            n += k
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text[:max_chars], {"injection_suspected": bool(hits), "injection_patterns": hits, "pii_redactions": n,
                              "truncated": len(text) > max_chars}


def parse_memo(text: str) -> ResearchMemo:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    a, b = cleaned.find("{"), cleaned.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("No JSON object in model output")
    return ResearchMemo.model_validate(json.loads(cleaned[a: b + 1]))


def _same(v, truth, rel=0.005) -> bool:
    if isinstance(truth, bool) or truth is None or isinstance(truth, str):
        return str(v).lower() == str(truth).lower()
    try:
        return abs(float(v) - float(truth)) <= max(abs(float(truth)) * rel, 1e-6)
    except (TypeError, ValueError):
        return False


def check_citations(memo: ResearchMemo, metrics: dict, checks: list[dict]) -> list[str]:
    """OBS-02: every figure must equal the stored metric; the headline must equal the NET metrics."""
    facts = {**metrics, **{f"check_{c['check']}": c["passed"] for c in checks}}
    errs = []
    for f in memo.figures:
        if f.metric not in facts:
            errs.append(f"unknown metric '{f.metric}'")
        elif not _same(f.value, facts[f.metric]):
            errs.append(f"{f.metric}: memo says {f.value} but the run says {facts[f.metric]}")
    for k in ("net_sharpe", "net_total_return", "max_drawdown"):
        v = getattr(memo.headline, k)
        if not _same(v, metrics.get(k)):
            hint = " (that is the GROSS figure)" if k.startswith("net_") and _same(v, metrics.get(k.replace("net_", "gross_"))) else ""
            errs.append(f"headline {k}: {v} but the run says {metrics.get(k)}{hint}")
    return errs


def check_compliance(memo: ResearchMemo, required: list[str], checks: list[dict]) -> list[str]:
    """Hypothetical-performance presentation: required disclosures present; failed checks named in the risks."""
    text = " ".join(memo.disclosures).lower()
    errs = [f"missing disclosure: '{d}'" for d in required if d.lower() not in text]
    failed = [c["check"] for c in checks if not c["passed"]]
    risks = " ".join(memo.risks).lower()
    for c in failed:
        if c.replace("_", " ") not in risks and c not in risks:
            errs.append(f"failed check '{c}' not disclosed in the risks")
    return errs


def apply_policy(rec: str, checks: list[dict], flags: dict, cite_errs: list, comp_errs: list, policy: dict
                 ) -> tuple[str, bool, list[str]]:
    """Returns (final recommendation, promotable, blockers). No model output can make a failed run promotable."""
    blockers = [f"promotion check failed: {c['check']} ({c['value']} vs {c['threshold']})" for c in checks if not c["passed"]]
    if policy.get("block_on_injection") and flags.get("injection_suspected"):
        blockers.append("research notes tried to change numbers, checks or disclosures (possible prompt injection)")
    if policy.get("block_on_citation_errors") and cite_errs:
        blockers.append("memo figures don't match the run")
    if comp_errs:
        blockers.append("memo fails the presentation rules: " + "; ".join(comp_errs[:3]))
    lookahead = any(c["check"] == "lookahead_clean" and not c["passed"] for c in checks)
    final = rec
    if lookahead:
        final = "REJECT"
    elif blockers and rec == "PROMOTE":
        final = "MORE_RESEARCH"
    return final, not blockers, blockers


def fallback_memo(run_id: str, strategy: str, metrics: dict, reason: str) -> ResearchMemo:
    return ResearchMemo(run_id=run_id, strategy=strategy, thesis=f"Automated memo unavailable: {reason}",
                        headline={"net_sharpe": metrics.get("net_sharpe") or 0.0,
                                  "net_total_return": metrics.get("net_total_return") or 0.0,
                                  "max_drawdown": metrics.get("max_drawdown") or 0.0},
                        figures=[{"metric": k, "value": metrics.get(k)} for k in ("net_sharpe", "net_total_return", "max_drawdown")],
                        risks=[reason], disclosures=[], recommendation="MORE_RESEARCH", confidence=0.0)
