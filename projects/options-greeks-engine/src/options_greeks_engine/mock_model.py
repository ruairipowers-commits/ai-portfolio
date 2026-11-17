"""Deterministic offline stand-in for a model (not an LLM), so the project runs with no keys and CI is free.

Two jobs, told apart by the tags in the prompt:
  <chain> … <untrusted_request>  → parse the request with rules (spreads, straddles, strangles, single options)
  <ticket_risk>                  → write the explanation from the computed risk table
It ignores instructions inside the request, so the injection is caught by the guardrails, not by the mock.
"""
from __future__ import annotations

import json
import re

WORD_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _parse(chain: dict, req: str) -> dict:
    t = req.lower()
    side = "BUY" if re.search(r"\b(buy|long|purchase)\b", t) else "SELL" if re.search(r"\b(sell|short|write)\b", t) else None
    m = re.search(rf"\b({WORD_MONTHS})[a-z]*\b", t)
    expiry = None
    if m:
        from datetime import date
        mo = [x for x in WORD_MONTHS.split("|")].index(m.group(1)) + 1
        hits = [e for e in chain["expiries"] if date.fromisoformat(e).month == mo and e > chain["as_of"]]
        expiry = hits[0] if hits else None
    qty = re.search(r"\b(buy|sell|long|short|write|purchase)\s+(\d+)\b", t)
    pair = re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\b", t)
    single = re.search(rf"\b(?:{WORD_MONTHS})[a-z]*\s+(\d+(?:\.\d+)?)\s*(?:strike\s*)?(calls?|puts?|straddles?)\b", t)
    if not single and qty:   # "buy 2 ACME 105 calls expiring December": strike before the month; look after the quantity
        single = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:strike\s*)?(calls?|puts?|straddles?)\b").search(t, qty.end())
    lim = re.search(r"(?:max(?:imum)?\s+debit|debit of|for a|for)\s+\$?(\d+(?:\.\d+)?)\s*(debit|credit)?", t)
    credit = re.search(r"(\d+(?:\.\d+)?)\s*credit", t)
    missing = [k for k, v in [("side", side), ("expiry", expiry), ("quantity", qty)] if not v]
    if missing or not (pair or single):
        has_strike = pair or single or re.compile(r"\b\d+(?:\.\d+)?\s*(?:strike\s*)?(?:calls?|puts?|straddles?|strangles?)\b").search(
            t, qty.end() if qty else 0)
        what = missing + ([] if has_strike else ["strike"])
        ask = (f"Please confirm the {', '.join(what)}." if what else
               "Please restate the order as side, quantity, strike, call or put, and expiry month.")
        return {"status": "CLARIFY", "legs": [], "clarification": ask, "notes": []}
    n = int(qty.group(2))
    legs = []
    buy, sell = ("BUY", "SELL") if side == "BUY" else ("SELL", "BUY")
    if pair:
        k1, k2 = sorted([float(pair.group(1)), float(pair.group(2))])
        if "strangle" in t:
            legs = [(side, "PUT", k1), (side, "CALL", k2)]
        elif "put" in t:
            legs = [(buy, "PUT", k2), (sell, "PUT", k1)]
        else:
            legs = [(buy, "CALL", k1), (sell, "CALL", k2)]
    else:
        k, kind = float(single.group(1)), single.group(2)
        legs = [(side, "CALL", k), (side, "PUT", k)] if kind.startswith("straddle") else [(side, kind[:-1].upper().rstrip("S") if kind.endswith("s") else kind.upper(), k)]
    out_legs = [{"side": s, "quantity": n, "option_type": ty, "strike": k, "expiry": expiry} for s, ty, k in legs]
    out = {"status": "OK", "legs": out_legs, "limit_price": None, "price_type": None, "clarification": None, "notes": []}
    if credit:
        out["limit_price"], out["price_type"] = float(credit.group(1)), "CREDIT"
    elif lim:
        out["limit_price"], out["price_type"] = float(lim.group(1)), (lim.group(2) or "debit").upper()
    return out


def _usd(x: float) -> str:
    return f"-${abs(x):,}" if x < 0 else f"${x:,}"


def _explain(risk: dict) -> dict:
    s = risk["summary"]
    keys = ["net_premium_usd", "premium_type", "position_delta_shares", "position_vega_usd", "position_theta_usd",
            "max_loss_usd", "max_profit_usd", "worst_scenario_pnl_usd"]
    failed = [c for c in risk.get("checks", []) if not c["passed"]]
    loss = "unlimited" if s["max_loss_usd"] == "unlimited" else f"${s['max_loss_usd']:,}"
    return {"ticket_id": risk.get("ticket_id", "T0"),
            "summary": (f"{s['premium_type'].title()} of ${abs(s['net_premium_usd']):,} for {len(risk['legs'])} leg(s). "
                        f"Delta {s['position_delta_shares']:,} shares, vega {_usd(s['position_vega_usd'])} per vol point, "
                        f"theta {_usd(s['position_theta_usd'])} per day. Maximum loss at first expiry: {loss}."),
            "figures": [{"metric": k, "value": s[k]} for k in keys],
            "risks": [f"Failed check: {c['check']} ({c['value']} vs limit {c['limit']})" for c in failed]
            or [f"Worst scenario shown: {s['worst_scenario']}."]}


class MockProvider:
    def complete(self, spec, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        if "<ticket_risk>" in user:
            risk = json.loads(re.search(r"<ticket_risk>\s*(\{.*\})\s*</ticket_risk>", user, re.S).group(1))
            out = _explain(risk)
        else:
            chain = json.loads(re.search(r"<chain>\s*(\{.*?\})\s*</chain>", user, re.S).group(1))
            req = re.search(r"<untrusted_request>(.*?)</untrusted_request>", user, re.S).group(1)
            out = _parse(chain, req)
        text = json.dumps(out)
        return text, estimate_tokens(system + user), estimate_tokens(text)
