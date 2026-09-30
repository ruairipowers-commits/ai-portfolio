"""Eval suite and promotion gate (EVAL-01..03, MODEL-02, HITL-03)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .llm import Budget, LLMClient, Registry
from .store import ROOT, Settings, now
from .workflow import build_prompt, new_run_id, triage_vendor


def load_golden(settings: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / settings["eval"]["golden_set"]).read_text())["cases"]


def run_eval(con, settings: Settings, alias: str) -> dict:
    registry = Registry(ROOT / "config" / "models.yaml")
    spec = registry.resolve(alias)
    # Evals get their own budget so they can't eat the production run budget.
    budget = Budget(settings["eval"]["max_total_cost_usd"], settings["cost"]["max_input_tokens_per_call"],
                    settings["cost"]["allow_unpriced_models"])
    client = LLMClient(registry, budget, settings["llm"]["retries"])
    run_id = "eval-" + new_run_id()
    cases = load_golden(settings)
    rows = []
    for c in cases:
        r = triage_vendor(con, c["vendor_id"], settings, client, run_id, alias=alias)
        rows.append({
            "vendor_id": c["vendor_id"], "tags": c.get("tags", []), "expected": c["expected"],
            "got": r.final_recommendation, "llm_draft": r.llm_recommendation,
            "correct": r.final_recommendation == c["expected"], "schema_valid": r.schema_valid,
            "citation_ok": not r.citation_errors, "cost_usd": r.cost_usd,
        })
    n = len(rows)
    esc = [x for x in rows if "must_escalate" in x["tags"]]
    metrics = {
        "accuracy": sum(x["correct"] for x in rows) / n,
        "schema_valid_rate": sum(x["schema_valid"] for x in rows) / n,
        "citation_accuracy": sum(x["citation_ok"] for x in rows) / n,
        "escalation_recall": (sum(x["got"] == "ESCALATE" for x in esc) / len(esc)) if esc else 1.0,
        "total_cost_usd": round(budget.spent, 6),
    }
    # HITL-03: how often did the AI agree with humans who later reviewed these vendors?
    rev = con.execute("""select vendor_id, decision from (
            select *, row_number() over (partition by vendor_id order by review_ts desc) rn from audit.reviews) where rn = 1""").fetchall()
    human = dict(rev)
    agree = [x["got"] == human[x["vendor_id"]] for x in rows if x["vendor_id"] in human]
    metrics["human_review_agreement"] = (sum(agree) / len(agree)) if agree else None

    th = settings["eval"]
    failures = [name for name, ok in [
        ("accuracy", metrics["accuracy"] >= th["min_accuracy"]),
        ("schema_valid_rate", metrics["schema_valid_rate"] >= th["min_schema_valid_rate"]),
        ("citation_accuracy", metrics["citation_accuracy"] >= th["min_citation_accuracy"]),
        ("escalation_recall", metrics["escalation_recall"] >= th["min_escalation_recall"]),
        ("total_cost_usd", metrics["total_cost_usd"] <= th["max_total_cost_usd"]),
    ] if not ok]
    _, _, prompt_sha = build_prompt(settings)
    report = {"run_id": run_id, "ts": now().isoformat(), "alias": alias, "model_name": spec.name,
              "model_id": spec.model_id, "prompt_sha": prompt_sha, "metrics": metrics,
              "failures": failures, "passed": not failures, "cases": rows}
    out = ROOT / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{report['ts'][:19].replace(':', '')}_{spec.name}.json").write_text(json.dumps(report, indent=2))
    (out / f"latest_{spec.name}.json").write_text(json.dumps(report, indent=2))
    return report


def compare(candidate: dict, baseline: dict) -> list[str]:
    """No-regression check for migrations: candidate must match or beat baseline on quality metrics."""
    regress = []
    for k in ("accuracy", "schema_valid_rate", "citation_accuracy", "escalation_recall"):
        if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]:
            regress.append(f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}")
    return regress


def latest_report(model_name: str) -> dict | None:
    p = ROOT / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
