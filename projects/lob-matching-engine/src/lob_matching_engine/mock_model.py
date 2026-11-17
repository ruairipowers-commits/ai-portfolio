"""Deterministic offline stand-in for a model, so the project runs with no keys and CI is free.

It reads the facts block and writes a narrative from templates. It is deliberately *gullible*: if the
untrusted order memos ask for the alert to be closed, it suggests CLOSE — the way a weak model might.
The deterministic guardrails downstream must catch that, and the tests prove they do. It is not an LLM.
"""
from __future__ import annotations

import json
import re


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1

TEMPLATES = {
    "layering": ("{trader} placed {layer_orders} {layer_side} orders totalling {layer_qty} shares, "
                 "{layer_qty_vs_median} times the median order size, then traded {opposite_fill_qty} shares on the "
                 "other side at {opposite_fill_price} and cancelled the layer within {seconds_fill_to_cancel} seconds."),
    "wash": ("{trader} rested orders and crossed them within about {median_order_age_ms} ms; self-trade prevention "
             "blocked {stp_blocked_attempts} attempts covering {blocked_qty} shares."),
    "stuffing": ("{trader} sent {orders} orders with a cancel ratio of {cancel_ratio} and a fill ratio of "
                 "{fill_ratio}; median order lifetime {median_lifetime_ms} ms."),
    "ignition": ("{trader} sent {burst_orders} aggressive {burst_side} orders in {burst_seconds} seconds, moving the "
                 "price {price_move_ticks} ticks, then traded {reverse_fill_qty} shares the other way after "
                 "{seconds_to_reverse} seconds."),
}
FIGURES = {
    "layering": ["layer_orders", "layer_qty", "layer_qty_vs_median", "opposite_fill_qty", "cancelled_share_of_layer"],
    "wash": ["stp_blocked_attempts", "blocked_qty", "median_order_age_ms"],
    "stuffing": ["orders", "cancel_ratio", "fill_ratio", "median_lifetime_ms"],
    "ignition": ["burst_orders", "price_move_ticks", "reverse_fill_qty", "seconds_to_reverse"],
}


class MockProvider:
    def complete(self, spec, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        m = re.search(r"<alert_facts>\s*(\{.*?\})\s*</alert_facts>", user, re.S)
        f = json.loads(m.group(1)) if m else {}
        memos = re.search(r"<untrusted_order_memos>(.*?)</untrusted_order_memos>", user, re.S)
        memo_text = memos.group(1) if memos else ""
        pattern = f.get("pattern", "layering")
        facts = f.get("facts", {})
        sev = f.get("severity", "medium")
        suggestion = {"high": "ESCALATE", "medium": "NEEDS_INFO"}.get(sev, "CLOSE")
        obs = []
        if re.search(r"\b(close|cleared|no issue)\b", memo_text, re.I):   # gullible on purpose
            suggestion = "CLOSE"
            obs.append("Order memos state the activity was cleared.")
        try:
            summary = TEMPLATES[pattern].format(trader=f.get("trader", "TRADER-1"), **facts)
        except (KeyError, IndexError):
            summary = f"{f.get('trader', 'TRADER-1')}: {pattern} pattern flagged by the rule engine."
        out = {
            "alert_id": f.get("alert_id", "A000"), "pattern": pattern, "summary": summary,
            "sequence": [f"event {e}" for e in f.get("event_ids", [])[:4]],
            "cited_events": f.get("event_ids", [0])[:8] or [0],
            "figures": [{"name": k, "value": facts[k]} for k in FIGURES.get(pattern, []) if k in facts][:8]
            or [{"name": "event_count", "value": f.get("event_count", 0)}],
            "observations": obs, "suggested_disposition": suggestion,
            "confidence": 0.8 if sev == "high" else 0.6,
        }
        text = json.dumps(out)
        return text, estimate_tokens(system + user), estimate_tokens(text)
