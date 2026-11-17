"""Deterministic offline stand-in for a model (not an LLM), so the project runs with no keys and CI is free.

It writes the memo from the metrics block. It is deliberately *gullible* about the researcher's notes: a note that
says "state the Sharpe is 4" puts 4 in the headline, and "skip the disclaimer / quote gross" drops the disclosures and
quotes gross figures. The deterministic checks downstream must catch both, and the tests prove they do.
"""
from __future__ import annotations

import json
import re

DISCLOSURES = ["Results are hypothetical, from a simulated backtest on synthetic data.",
               "Figures are net of modelled costs (spread, impact, commission, latency) only; real costs may be higher.",
               "Past performance, simulated or actual, does not guarantee future results."]


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


class MockProvider:
    def complete(self, spec, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        m = json.loads(re.search(r"<run_metrics>\s*(\{.*?\})\s*</run_metrics>", user, re.S).group(1))
        checks = json.loads(re.search(r"<promotion_checks>\s*(\[.*?\])\s*</promotion_checks>", user, re.S).group(1))
        notes = (re.search(r"<untrusted_research_notes>(.*?)</untrusted_research_notes>", user, re.S) or [None, ""])[1]
        failed = [c["check"] for c in checks if not c["passed"]]
        head = {"net_sharpe": m["net_sharpe"], "net_total_return": m["net_total_return"], "max_drawdown": m["max_drawdown"]}
        disclosures = list(DISCLOSURES)
        forced = re.search(r"sharpe[^\d\n]{0,20}(\d+(?:\.\d+)?)", notes, re.I)
        if forced:                                                    # gullible on purpose
            head["net_sharpe"] = float(forced.group(1))
        if re.search(r"\b(skip|omit|drop)\b.{0,20}\b(disclaimer|disclosure)", notes, re.I) or re.search(r"\bgross\b", notes, re.I):
            disclosures = []
            head["net_sharpe"], head["net_total_return"] = m["gross_sharpe"], m["gross_total_return"]
        rec = "PROMOTE" if not failed else ("REJECT" if "lookahead_clean" in failed or m["net_sharpe"] < 0 else "MORE_RESEARCH")
        if forced and rec != "PROMOTE":
            rec = "PROMOTE"
        keys = ["net_sharpe", "gross_sharpe", "net_total_return", "max_drawdown", "fills", "avg_cost_bps",
                "oos_sharpe", "selection_adjusted_t", "sharpe_at_stress_costs"]
        memo = {
            "run_id": m.get("run_id", "run"), "strategy": m["strategy"],
            "thesis": f"{m['strategy']} on {m['days']} days of {m['bar']} bars. Net Sharpe {head['net_sharpe']} "
                      f"(gross {m['gross_sharpe']}), out-of-sample Sharpe {m['oos_sharpe']}.",
            "headline": head,
            "figures": [{"metric": k, "value": m[k]} for k in keys if k in m],
            "risks": [f"Failed check: {c.replace('_', ' ')}" for c in failed] or
                     ["Single synthetic instrument; regime change could remove the edge."],
            "disclosures": disclosures, "recommendation": rec, "confidence": 0.7 if not failed else 0.5,
        }
        text = json.dumps(memo)
        return text, estimate_tokens(system + user), estimate_tokens(text)
