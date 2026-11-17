"""Eval suite and promotion gate for model changes (EVAL-01..03, MODEL-02, HITL-03)."""
from __future__ import annotations

import json
from functools import lru_cache

import yaml

from .data import synthetic_ticks
from .store import ROOT, Settings, connect, now, rows, workspace
from .workflow import build_prompt, client_for, new_run_id, run


def load_golden(s: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / s["eval"]["golden_set"]).read_text())["cases"]


def corrupt(t):
    t = t.copy()
    i = len(t) // 2
    t.loc[i, "ask"] = t.loc[i, "bid"] - 0.05
    t.loc[i + 10, "ts"] = t.loc[i + 10, "ts"] - __import__("pandas").Timedelta(minutes=30)
    return t


@lru_cache(maxsize=8)
def _ticks(seed: int, trend: float, days: int, tpd: int):
    return synthetic_ticks(days=days, ticks_per_day=tpd, trend_strength=trend, seed=seed)


def dataset(s: Settings, d: dict):
    base = s["dataset"]
    t = _ticks(d.get("seed", base["seed"]), d.get("trend_strength", base["trend_strength"]), base["days"], base["ticks_per_day"])
    return corrupt(t) if d.get("corrupt") else t


def run_eval(s: Settings, alias: str) -> dict:
    client = client_for(s, s["eval"]["max_total_cost_usd"])
    spec = client.registry.resolve(alias)
    eval_id = "eval-" + new_run_id()
    out = []
    n_memo = valid = 0
    clean_n = clean_ok = 0
    must_flag = flagged = comp_n = comp_caught = 0
    for c in load_golden(s):
        r_ = c["run"]
        res = run(s, dataset(s, c["data"]), kind=r_.get("kind", "MA crossover"), notes=r_.get("notes", ""),
                  trials=r_.get("trials", 1), alias=alias, run_id=f"{eval_id}-{c['id']}", client=client, dataset="eval")
        e, probs = c["expect"], []
        if e.get("gate_blocked"):
            if res.gate.ok:
                probs.append("data gate did not block")
        else:
            m = res.memo
            failed = [x["check"] for x in res.checks if not x["passed"]]
            n_memo += 1
            valid += m.schema_valid
            if "promotable" in e and m.promotable != e["promotable"]:
                probs.append(f"promotable={m.promotable}")
            if "final" in e and m.final_recommendation != e["final"]:
                probs.append(f"final {m.final_recommendation} != {e['final']}")
            if "final_not" in e and m.final_recommendation == e["final_not"]:
                probs.append(f"final is {e['final_not']}")
            for fc in e.get("failed_checks", []):
                if fc not in failed:
                    probs.append(f"check {fc} should fail")
            if e.get("flagged"):
                must_flag += 1
                flagged += m.injection_suspected
                if not m.injection_suspected:
                    probs.append("injection not flagged")
            if e.get("compliance_caught"):
                comp_n += 1
                caught = bool(m.compliance_errors or m.citation_errors) and not m.promotable
                comp_caught += caught
                if not caught:
                    probs.append("compliance problem not caught")
            if "must_flag" not in c.get("tags", []) and "compliance" not in c.get("tags", []):
                clean_n += 1
                clean_ok += not m.citation_errors
                if e.get("citations_clean") and m.citation_errors:
                    probs.append("citation errors: " + "; ".join(m.citation_errors[:2]))
        out.append({"id": c["id"], "tags": c.get("tags", []), "why": c.get("why", ""), "passed": not probs,
                    "final": res.memo.final_recommendation if res.memo else "BLOCKED",
                    "promotable": res.memo.promotable if res.memo else False, "problems": "; ".join(probs)})
    met = {
        "case_pass_rate": sum(x["passed"] for x in out) / len(out),
        "schema_valid_rate": valid / n_memo if n_memo else 1.0,
        "citation_accuracy_clean": clean_ok / clean_n if clean_n else 1.0,
        "injection_recall": flagged / must_flag if must_flag else 1.0,
        "compliance_catch_rate": comp_caught / comp_n if comp_n else 1.0,
        "total_cost_usd": round(client.budget.spent, 6),
    }
    disp = rows(connect(s), "select agrees_with_ai from promotions")
    met["human_agreement"] = (sum(d["agrees_with_ai"] for d in disp) / len(disp)) if disp else None   # HITL-03
    th = s["eval"]
    failures = [k for k, ok in [
        ("case_pass_rate", met["case_pass_rate"] >= th["min_case_pass_rate"]),
        ("schema_valid_rate", met["schema_valid_rate"] >= th["min_schema_valid_rate"]),
        ("citation_accuracy_clean", met["citation_accuracy_clean"] >= th["min_citation_accuracy_clean"]),
        ("injection_recall", met["injection_recall"] >= th["min_injection_recall"]),
        ("compliance_catch_rate", met["compliance_catch_rate"] >= th["min_compliance_catch_rate"]),
        ("total_cost_usd", met["total_cost_usd"] <= th["max_total_cost_usd"]),
    ] if not ok]
    _, _, psha = build_prompt(s)
    rep = {"run_id": eval_id, "ts": now(), "alias": alias, "model_name": spec.name, "model_id": spec.model_id,
           "prompt_sha": psha, "metrics": met, "failures": failures, "passed": not failures, "cases": out}
    d = workspace() / "output" / "evals"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"latest_{spec.name}.json").write_text(json.dumps(rep, indent=2))
    (d / f"{rep['ts'][:19].replace(':', '')}_{spec.name}.json").write_text(json.dumps(rep, indent=2))
    return rep


def compare(candidate: dict, baseline: dict) -> list[str]:
    return [f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}"
            for k in ("case_pass_rate", "schema_valid_rate", "citation_accuracy_clean", "injection_recall",
                      "compliance_catch_rate") if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]]


def latest_report(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
