"""Golden-set evaluation for the agent: outcome AND trajectory (EVAL-01..03, MODEL-02).

Metrics
  category_accuracy        right break category
  fix_accuracy             right effective fix (ESCALATE when policy/model escalated)
  escalation_recall        every must_escalate case escalated (safety)
  trajectory_compliance    required tools called and tool-call cap respected
  unapproved_writes        resolutions written during the eval (must be 0: evals never approve)
  total_cost_usd
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import yaml

from . import db
from .runner import ROOT, db_url, investigate, load_settings, workspace
from .llm import Registry


async def run_eval(alias: str) -> dict:
    s = load_settings()
    spec = Registry(ROOT / "config" / "models.yaml").resolve(alias)
    cases = yaml.safe_load((ROOT / s["eval"]["golden_set"]).read_text())["cases"]
    con = db.connect(db_url(s))
    writes_before = con.one("select count(*) as n from resolutions")["n"]
    con.close()
    run_id = "eval-" + uuid.uuid4().hex[:8]
    results = {r["exception_id"]: r for r in await investigate([c["exception_id"] for c in cases], alias, run_id)}
    con = db.connect(db_url(s))
    writes_after = con.one("select count(*) as n from resolutions")["n"]
    con.close()
    cap = s["agent"]["max_tool_calls"]
    rows = []
    for c in cases:
        r = results[c["exception_id"]]
        effective_fix = "ESCALATE" if r["status"] == "escalated" else r["fix_type"]
        rows.append({
            "exception_id": c["exception_id"], "tags": c.get("tags", []),
            "expected": [c["expected_category"], c["expected_fix"], c["expected_status"]],
            "got": [r["category"], effective_fix, r["status"]],
            "category_ok": r["category"] == c["expected_category"],
            "fix_ok": effective_fix == c["expected_fix"],
            "status_ok": r["status"] == c["expected_status"],
            "trajectory_ok": set(c["required_tools"]) <= set(r["tools_used"]) and r["tool_calls"] <= cap,
            "tool_calls": r["tool_calls"], "cost_usd": r["cost_usd"], "reasons": r["reasons"],
        })
    n = len(rows)
    esc = [x for x in rows if "must_escalate" in x["tags"]]
    m = {
        "category_accuracy": sum(x["category_ok"] for x in rows) / n,
        "fix_accuracy": sum(x["fix_ok"] for x in rows) / n,
        "escalation_recall": sum(x["got"][2] == "escalated" for x in esc) / len(esc) if esc else 1.0,
        "trajectory_compliance": sum(x["trajectory_ok"] for x in rows) / n,
        "unapproved_writes": writes_after - writes_before,
        "avg_tool_calls": round(sum(x["tool_calls"] for x in rows) / n, 2),
        "total_cost_usd": round(sum(x["cost_usd"] for x in rows), 6),
    }
    th = s["eval"]
    failures = [k for k, ok in [
        ("category_accuracy", m["category_accuracy"] >= th["min_category_accuracy"]),
        ("fix_accuracy", m["fix_accuracy"] >= th["min_fix_accuracy"]),
        ("escalation_recall", m["escalation_recall"] >= th["min_escalation_recall"]),
        ("trajectory_compliance", m["trajectory_compliance"] >= th["min_trajectory_compliance"]),
        ("unapproved_writes", m["unapproved_writes"] <= th["max_unapproved_writes"]),
        ("total_cost_usd", m["total_cost_usd"] <= th["max_total_cost_usd"]),
    ] if not ok]
    prompt_sha = __import__("hashlib").sha256((ROOT / s["llm"]["prompt_file"]).read_bytes()).hexdigest()[:16]
    report = {"run_id": run_id, "ts": datetime.now(timezone.utc).isoformat(), "alias": alias,
              "model_name": spec.name, "model_id": spec.model_id, "prompt_sha": prompt_sha,
              "metrics": m, "failures": failures, "passed": not failures, "cases": rows}
    out = workspace() / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{report['ts'][:19].replace(':', '')}_{spec.name}.json").write_text(json.dumps(report, indent=2))
    (out / f"latest_{spec.name}.json").write_text(json.dumps(report, indent=2))
    return report


def compare(candidate: dict, baseline: dict) -> list[str]:
    keys = ("category_accuracy", "fix_accuracy", "escalation_recall", "trajectory_compliance")
    return [f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}"
            for k in keys if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]]


def latest(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
