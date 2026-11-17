"""Deterministic guardrails: SEC-02 injection screening of the request, DATA-03 redaction, SEC-04 strict parsing,
leg validation against the listed chain and the request text, OBS-02 figure checks on the explanation, and the
permission / limit checks that decide whether a ticket can be approved (HITL-01: high risk)."""
from __future__ import annotations

import json
import re

from .market import Market
from .schemas import RiskExplanation, TradeParse

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|above|system)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"(approval|developer|admin) mode",
    r"\b(pre-?approved|already approved|risk (has )?(approved|signed off))\b",
    r"\b(skip|bypass|ignore|override)\b[^.\n]{0,25}\b(limits?|checks?|risk|approval)\b",
    r"note to (the )?(assistant|model|ai)",
]
PII_PATTERNS = {"EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+", "PHONE": r"\+?\d[\d\s().-]{8,}\d"}


def sanitize_untrusted(text: str, max_chars: int, redact: bool = True) -> tuple[str, dict]:
    hits = [p for p in INJECTION_PATTERNS if re.search(p, text, re.I | re.M)]
    n = 0
    if redact:
        for label, pat in PII_PATTERNS.items():
            text, k = re.subn(pat, f"[REDACTED_{label}]", text)
            n += k
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text[:max_chars], {"injection_suspected": bool(hits), "injection_patterns": hits, "pii_redactions": n,
                              "truncated": len(text) > max_chars}


def _json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    a, b = cleaned.find("{"), cleaned.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("No JSON object in model output")
    return json.loads(cleaned[a: b + 1])


def parse_trade(text: str) -> TradeParse:
    return TradeParse.model_validate(_json(text))


def parse_explanation(text: str) -> RiskExplanation:
    return RiskExplanation.model_validate(_json(text))


def _num_in_text(x: float, text: str) -> bool:
    nums = {float(n) for n in re.findall(r"(?<![\d.])\d+(?:\.\d+)?", text)}
    return float(x) in nums


def validate_legs(p: TradeParse, mk: Market, request: str, max_legs: int) -> list[str]:
    """No ticket unless every leg is listed, live and actually asked for in the request text."""
    errs = []
    if p.status != "OK":
        return errs
    if not p.legs:
        errs.append("no legs parsed")
    if len(p.legs) > max_legs:
        errs.append(f"{len(p.legs)} legs (max {max_legs})")
    for i, lg in enumerate(p.legs, 1):
        if lg.strike not in mk.strikes:
            errs.append(f"leg {i}: strike {lg.strike:g} is not listed")
        if lg.expiry not in mk.expiries:
            errs.append(f"leg {i}: expiry {lg.expiry} is not listed")
        elif mk.years(lg.expiry) <= 0:
            errs.append(f"leg {i}: expiry {lg.expiry} has passed")
        if not _num_in_text(lg.strike, request):
            errs.append(f"leg {i}: strike {lg.strike:g} does not appear in the request")
        if not _num_in_text(lg.quantity, request):
            errs.append(f"leg {i}: quantity {lg.quantity} does not appear in the request")
    if p.limit_price is not None and not _num_in_text(p.limit_price, request):
        errs.append(f"limit price {p.limit_price} does not appear in the request")
    return errs


def check_limits(summary: dict, legs, account: dict) -> list[dict]:
    """Permission and limit checks, all computed. Any failure blocks approval."""
    lim, perm = account["limits"], account["permission"]
    short = [lg for lg in legs if lg.side == "SELL"]
    max_loss = summary["max_loss_usd"]
    checks = [
        _c("permission", perm, "long_only: no short options" if perm == "long_only" else
           "defined_risk: max loss must be finite" if perm == "defined_risk" else "any structure",
           not (perm == "long_only" and short) and not (perm == "defined_risk" and max_loss == "unlimited")),
        _c("contracts_per_leg", max(lg.quantity for lg in legs), lim["max_contracts_per_leg"],
           max(lg.quantity for lg in legs) <= lim["max_contracts_per_leg"]),
        _c("premium_usd", abs(summary["net_premium_usd"]), lim["max_premium_usd"], abs(summary["net_premium_usd"]) <= lim["max_premium_usd"]),
        _c("max_loss_usd", max_loss, lim["max_loss_usd"], max_loss != "unlimited" and max_loss <= lim["max_loss_usd"]),
        _c("abs_delta_shares", abs(summary["position_delta_shares"]), lim["max_abs_delta_shares"],
           abs(summary["position_delta_shares"]) <= lim["max_abs_delta_shares"]),
        _c("abs_vega_usd", abs(summary["position_vega_usd"]), lim["max_abs_vega_usd"], abs(summary["position_vega_usd"]) <= lim["max_abs_vega_usd"]),
    ]
    return checks


def _c(name, value, limit, ok) -> dict:
    return {"check": name, "value": value, "limit": limit, "passed": bool(ok)}


def check_citations(e: RiskExplanation, facts: dict) -> list[str]:
    errs = []
    for f in e.figures:
        if f.metric not in facts:
            errs.append(f"unknown metric '{f.metric}'")
            continue
        t = facts[f.metric]
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            try:
                ok = abs(float(f.value) - t) <= max(abs(t) * 0.005, 1e-6)
            except (TypeError, ValueError):
                ok = False
        else:
            ok = str(f.value).lower() == str(t).lower()
        if not ok:
            errs.append(f"{f.metric}: explanation says {f.value} but the engine says {t}")
    return errs
