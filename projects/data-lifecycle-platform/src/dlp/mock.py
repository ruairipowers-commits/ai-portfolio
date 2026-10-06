"""Deterministic offline stand-in for a model, so the platform runs with no keys and CI costs nothing.

It reads the same prompts a real model gets and answers in the same JSON contracts. It is deliberately naive about
safety — it follows instructions it finds in untrusted text and copies what it sees — so the guardrails downstream
are exercised exactly as they would be with a real model that slips.
"""
from __future__ import annotations

import json
import re

from .llm import ModelSpec, estimate_tokens


def _block(tag: str, text: str) -> str:
    """The content of the LAST <tag>…</tag> block (instructions may mention the tag earlier)."""
    found = re.findall(rf"\n<{tag}>\n(.*?)\n</{tag}>", "\n" + text, re.S)
    return found[-1] if found else ""


def _task(user: str) -> str:
    return _block("task", user).strip()


class MockProvider:
    def complete(self, spec: ModelSpec, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        task = _task(user)
        out = {"extract": _extract, "search": _search, "answer": _answer, "assess": _assess,
               "monetize": _monetize}.get(task, lambda u: {"error": f"unknown task {task}"})(user)
        text = json.dumps(out)
        return text, estimate_tokens(system + user), estimate_tokens(text)


# ---------------------------------------------------------------- extraction
_KEYS = {"headquarters": ("vendor", "hq"), "website": ("vendor", "website"), "coverage": ("dataset", "coverage"),
         "history": ("dataset", "history_start"), "frequency": ("dataset", "frequency"),
         "delivery": ("dataset", "delivery"), "identifiers": ("dataset", "identifiers"),
         "licence": ("dataset", "licence"), "license": ("dataset", "licence"), "list price": ("dataset", "list_price_usd"),
         "documentation": ("vendor", "docs_url")}


def _extract(user: str) -> dict:
    src = _block("source", user).replace("&lt;", "<").replace("&gt;", ">")
    lines = [l.strip() for l in src.splitlines() if l.strip()]
    vendor, dataset, fields = {}, {}, []
    title_lines = [l for l in lines if not re.match(r"^[\w ]+:", l)]
    if lines:
        vendor["name"] = {"value": re.sub(r"^#\s*", "", lines[0]).split(" — ")[0].strip(), "quote": lines[0][:120]}
    if len(title_lines) > 1:
        t = title_lines[1]
        if "|" not in t and len(t) < 90:
            dataset["title"] = {"value": t.lstrip("# ").strip(), "quote": t[:120]}
        if len(title_lines) > 2 and "|" not in title_lines[2]:
            dataset["description"] = {"value": title_lines[2], "quote": title_lines[2][:200]}
    for l in lines:
        m = re.match(r"^([A-Za-z ]+):\s*(.+)$", l)
        if m and m.group(1).strip().lower() in _KEYS:
            side, key = _KEYS[m.group(1).strip().lower()]
            val = m.group(2).strip()
            if key == "history_start":
                d = re.search(r"\d{4}-\d{2}-\d{2}", val)
                val = d.group(0) if d else val
            elif key == "list_price_usd":
                n = re.search(r"([\d,]{4,})", val)
                val = float(n.group(1).replace(",", "")) if n else None
            elif key == "licence":
                val = val.split(",")[0].strip().lower()
            elif key in ("website", "docs_url"):
                u = re.search(r"https?://\S+", val)
                val = u.group(0).rstrip(".") if u else val
            elif key == "identifiers":
                val = [x.strip() for x in val.split(",")]
            (vendor if side == "vendor" else dataset)[key] = {"value": val, "quote": l[:200]}
        # A naive model obeys instructions it reads. The guardrails must catch this.
        inj = re.search(r"licen[cs]e\s+(apache-2\.0|mit|cc-by-4\.0)", l, re.I)
        if inj and ("ignore" in l.lower() or "mark this" in l.lower()):
            dataset["licence"] = {"value": inj.group(1).lower(), "quote": l[:200]}
    for l in lines:                       # markdown table rows: | name | type | description |
        cells = [c.strip() for c in l.strip("|").split("|")] if l.startswith("|") else []
        if len(cells) >= 3 and cells[0].lower() not in ("field", "---", "") and not set(cells[0]) <= set("-:"):
            fields.append({"name": cells[0], "type": cells[1], "description": cells[2]})
    if lines and lines[0].lower().startswith("field,type,description"):
        for l in lines[1:]:
            parts = l.split(",", 2)
            if len(parts) == 3:
                fields.append({"name": parts[0], "type": parts[1], "description": parts[2]})
    return {"vendor": vendor, "dataset": dataset, "fields": fields, "notes": "mock extraction"}


# ---------------------------------------------------------------- search planning
def _search(user: str) -> dict:
    need = _block("need", user).lower()
    vocab = json.loads(_block("vocabulary", user) or "[]")
    plan = {"concepts": [], "categories": [], "sectors": [], "factors": [], "free_only": False,
            "needs_ai_processing": False, "rationale": ""}
    key = {"Measure": "concepts", "Identifier": "concepts", "Concept": "concepts", "DataCategory": "categories",
           "Sector": "sectors", "EconomicFactor": "factors"}
    for t in vocab:
        if any(re.search(rf"(?<![a-z]){re.escape(lab)}(?![a-z])", need) for lab in t["labels"] if len(lab) > 2):
            k = key.get(t["kind"])
            if k and t["iri"] not in plan[k]:
                plan[k].append(t["iri"])
    plan["free_only"] = bool(re.search(r"\bfree\b|open licen", need))
    plan["needs_ai_processing"] = bool(re.search(r"\bai\b|\bllm\b|model", need))
    plan["rationale"] = f"matched {sum(len(plan[k]) for k in ('concepts', 'categories', 'sectors', 'factors'))} vocabulary terms"
    return plan


# ---------------------------------------------------------------- answers
def _answer(user: str) -> dict:
    packet = json.loads(_block("packet", user) or "{}")
    status = packet.get("status", "ANSWERED")
    if status != "ANSWERED":
        return {"answer": packet.get("status_reason", status), "status": status, "citations": []}
    parts, cites = [], []
    for m in packet.get("metrics", []):
        for row in m["rows"][:6]:
            label = ", ".join(str(row[g]) for g in m["group_by"]) or "all"
            vals = "; ".join(f"{k} {row[k]}" for k in row if k not in m["group_by"] and row[k] is not None)
            parts.append(f"{label}: {vals}")
        cites.append(m["query_id"])
    for e in packet.get("graph", [])[:5]:
        cites.append(e["id"])
        parts.append(e["text"])
    if not parts:
        return {"answer": "The context has no facts that answer this.", "status": "NO_DATA", "citations": []}
    return {"answer": " ".join(p.rstrip(".") + "." for p in parts), "status": "ANSWERED", "citations": cites}


# ---------------------------------------------------------------- assessment and monetization
_ALPHA = {
    "options & volatility": [("Names whose implied vol sits well above 20-day realised vol tend to see that premium "
                              "shrink; a cross-sectional IV–HV spread signal", "days to weeks",
                              "rank symbols by iv_hv_spread each day; test next-5-day realised vol and straddle P&L")],
    "shipping & freight": [("Rising port congestion ahead of earnings flags margin pressure for importers",
                            "weeks", "event study of congestion changes vs. gross-margin surprises")],
    "consumer transactions": [("Card spend growth leads reported same-store sales", "weeks",
                               "regress quarterly revenue surprise on spend index growth, point-in-time only")],
}


def _assess(user: str) -> dict:
    f = json.loads(_block("facts", user) or "{}")
    strengths, risks = [], []
    cov = f.get("coverage_pct")
    if cov is not None:
        (strengths if cov >= 0.5 else risks).append(f"S&P 500 coverage {cov}")
    if f.get("history_days") is not None:
        (strengths if f["history_days"] >= 365 else risks).append(f"history_days {f['history_days']}")
    if f.get("licence_verdict") in ("LEGAL_REVIEW", "BLOCKED"):
        risks.append(f"licence verdict {f['licence_verdict']}")
    if f.get("point_in_time") is False:
        risks.append("history is not point-in-time")
    ideas = [{"hypothesis": h, "horizon": hz, "test": t} for h, hz, t in _ALPHA.get(f.get("category", ""), [])]
    rec = "LEGAL_REVIEW" if f.get("licence_verdict") == "LEGAL_REVIEW" else "SHORTLIST" if len(risks) == 0 else "TRIAL"
    return {"summary": f"{f.get('title')}: {len(strengths)} strengths, {len(risks)} risks.",
            "strengths": strengths, "risks": risks, "alpha_ideas": ideas, "recommendation": rec,
            "citations": [k for k in ("coverage_pct", "history_days", "licence_verdict") if k in f]}


def _monetize(user: str) -> dict:
    f = json.loads(_block("facts", user) or "{}")
    segs = ["Event-driven and fundamental equity funds covering " + ", ".join(f.get("sectors", [])[:3])] \
        if f.get("sectors") else ["Fundamental equity funds"]
    return {"summary": f"{f.get('company')}: uniqueness {f.get('uniqueness')}, history {f.get('history_months')} months.",
            "buyer_segments": segs + ["Quant funds that buy alternative data for nowcasting"],
            "use_cases": [f"Nowcast {x}" for x in f.get("factors", [])[:2]] or ["Nowcast sector activity"],
            "packaging": ["Weekly aggregated file, lane-level, lagged 1 day", "Point-in-time history back to the start"],
            "gaps": f.get("gaps", []), "citations": ["uniqueness", "history_months"]}
