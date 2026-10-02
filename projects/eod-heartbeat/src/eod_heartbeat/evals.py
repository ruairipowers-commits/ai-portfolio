"""Golden-set eval gate (EVAL-01/02, MODEL-02).

Metrics:
  detection_recall / precision   breaks SQL found vs the golden list, every date (deterministic — catches SQL regressions)
  runbook_accuracy               explanations citing an acceptable runbook for the break
  explained_rate                 breaks a model explained (vs degraded mode with no model available)
  citation_rate                  explanations citing at least one retrieved runbook section (NFR-2)
  human_routing                  critical breaks routed to a human, others not
  unsafe_actions                 explanations whose shown next step is unsafe after policy (must be 0)
  total_cost_usd
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import yaml

from . import telemetry
from .explain import prompt, run_eod
from .llm import Registry
from .loader import load
from .transform import run_dbt
from .store import ROOT, Settings, workspace


def run_eval(settings: Settings, alias: str = "explain-primary", actor: str = "eval",
             unavailable: set[str] | None = None) -> dict:
    gold = yaml.safe_load((ROOT / settings["eval"]["golden_set"]).read_text())
    spec = Registry(ROOT / "config" / "models.yaml").resolve(alias)
    run_id = "eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    load(settings)
    # One dbt build covers every date: all golden arrivals happen before the as-of time on their own date.
    dbt = run_dbt(settings, f"{gold['dates'][-1]['date']} {gold['as_of_time']}")
    rows, found_n, expected_n, matched, cost = [], 0, 0, 0, 0.0
    unsafe = [p for p in settings["policy"]["unsafe_action_patterns"]]
    for day in gold["dates"]:
        r = run_eod(settings, day["date"], gold["as_of_time"], actor=actor, trigger="eval", alias=alias,
                    unavailable=unavailable, reload=False, run_id=f"{run_id}-{day['date']}", dbt_result=dbt,
                    use_cache=False)
        cost += r["cost_usd"]
        found = {(b["break_type"], b["entity"]): b for b in r["breaks"]}
        found_n += len(found)
        expected_n += len(day["breaks"])
        for g in day["breaks"]:
            b = found.get((g["type"], g["entity"]))
            e = r["explanations"].get(b["break_id"]) if b else None
            docs = {x.split("#")[0] for x in (e["runbook_refs"] if e else [])}
            row = {"date": day["date"], "type": g["type"], "entity": g["entity"], "detected": b is not None,
                   "status": e["status"] if e else None, "runbooks": sorted(docs),
                   "runbook_ok": bool(docs & set(g["runbooks"])), "cited": bool(e and e["runbook_refs"]),
                   "human_ok": bool(e) and (e["needs_human"] == g["human"] or (g["human"] is False and e["status"] == "degraded")),
                   "unsafe_shown": bool(e) and any(re.search(p, e["next_step"], re.I) for p in unsafe)
                                   and not e["next_step"].startswith("Blocked by policy"),
                   "model": e["model_name"] if e else "", "next_step": e["next_step"] if e else "",
                   "likely_cause": e["likely_cause"] if e else ""}
            matched += row["detected"]
            rows.append(row)
    ex = [x for x in rows if x["detected"]]
    m = {
        "detection_recall": round(matched / max(expected_n, 1), 3),
        "detection_precision": round(matched / max(found_n, 1), 3),
        "runbook_accuracy": round(sum(x["runbook_ok"] for x in ex) / max(len(ex), 1), 3),
        "citation_rate": round(sum(x["cited"] for x in ex) / max(len(ex), 1), 3),
        "human_routing": round(sum(x["human_ok"] for x in ex) / max(len(ex), 1), 3),
        "explained_rate": round(sum(x["status"] in ("explained", "needs_human") for x in ex) / max(len(ex), 1), 3),
        "unsafe_actions": sum(x["unsafe_shown"] for x in ex),
        "total_cost_usd": round(cost, 5),
        "breaks": len(rows),
    }
    th = settings["eval"]
    failures = [k for k, ok in [
        ("detection_recall", m["detection_recall"] >= th["min_detection_recall"]),
        ("detection_precision", m["detection_precision"] >= th["min_detection_precision"]),
        ("runbook_accuracy", m["runbook_accuracy"] >= th["min_runbook_accuracy"]),
        ("citation_rate", m["citation_rate"] >= th["min_citation_rate"]),
        ("explained_rate", m["explained_rate"] >= th["min_explained_rate"]),
        ("unsafe_actions", m["unsafe_actions"] <= th["max_unsafe_actions"]),
        ("total_cost_usd", m["total_cost_usd"] <= th["max_total_cost_usd"]),
    ] if not ok]
    from .store import connect
    with connect(settings) as con:
        kbv = con.execute("select kb_version from kb.index_runs where active").fetchone()
    report = {"run_id": run_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "alias": alias,
              "model_name": spec.name, "model_id": spec.model_id, "prompt_sha": prompt(settings)[1],
              "kb_version": kbv["kb_version"] if kbv else None, "metrics": m, "failures": failures,
              "passed": not failures, "cases": rows}
    out = workspace() / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{run_id}_{spec.name}.json").write_text(json.dumps(report, indent=2, default=str))
    (out / f"latest_{spec.name}.json").write_text(json.dumps(report, indent=2, default=str))
    telemetry.record("eval-gate", event_type="eval", actor=actor, status="pass" if report["passed"] else "fail",
                     run_id=run_id, model=spec.name, cost_usd=m["total_cost_usd"], items=len(rows),
                     detail={"metrics": m, "failures": failures})
    return report


def compare(candidate: dict, baseline: dict) -> list[str]:
    keys = ("detection_recall", "detection_precision", "runbook_accuracy", "citation_rate", "human_routing")
    return [f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}"
            for k in keys if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]]


def latest_report(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
