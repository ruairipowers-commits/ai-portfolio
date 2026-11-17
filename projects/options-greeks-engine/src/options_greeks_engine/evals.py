"""Eval suite and promotion gate for model changes (EVAL-01..03, MODEL-02)."""
from __future__ import annotations

import json

import yaml

from .store import ROOT, Settings, now, workspace
from .workflow import client_for, process, prompt
from .schemas import parse_json_schema


def load_golden(s: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / s["eval"]["golden_set"]).read_text())["cases"]


def run_eval(s: Settings, alias: str, explain_alias: str | None = None) -> dict:
    client = client_for(s, s["eval"]["max_total_cost_usd"])
    spec = client.registry.resolve(alias)
    eval_id = "eval-" + now().replace(":", "").replace("-", "")[:15]
    out = []
    parse_n = parse_ok = expl_n = expl_ok = must_flag = flagged = must_block = blocked = valid = 0
    for c in load_golden(s):
        tk = process(s, c["request"], c["account"], alias, explain_alias, ticket_id=f"{eval_id}-{c['id']}", client=client)
        e, probs = c["expect"], []
        valid += tk.schema_valid
        if tk.status != e["status"]:
            probs.append(f"status {tk.status} != {e['status']}")
        if "legs" in e:
            parse_n += 1
            got = [[l.side, l.quantity, l.option_type, l.strike, l.expiry] for l in (tk.parse.legs if tk.parse else [])]
            want = [[a, b, t, float(k), x] for a, b, t, k, x in e["legs"]]
            same = got == want and (e.get("limit_price") is None or (tk.parse and tk.parse.limit_price == e["limit_price"]))
            parse_ok += same
            if not same:
                probs.append(f"legs {got} != {want}")
        failed = [x["check"] for x in tk.checks if not x["passed"]]
        for fc in e.get("failed_checks", []):
            if fc not in failed:
                probs.append(f"check {fc} should fail")
        if e.get("checks_ran") and not tk.checks:
            probs.append("limits were not checked")
        if e.get("flagged"):
            must_flag += 1
            flagged += tk.injection_suspected
            if not tk.injection_suspected:
                probs.append("injection not flagged")
        if "must_block" in c.get("tags", []):
            must_block += 1
            blocked += tk.status in ("BLOCKED", "INVALID", "CLARIFY")
        if tk.explanation is not None:
            expl_n += 1
            expl_ok += not tk.citation_errors
            if e.get("citations_clean") and tk.citation_errors:
                probs.append("explanation figures don't match")
        out.append({"id": c["id"], "account": c["account"], "status": tk.status, "passed": not probs,
                    "problems": "; ".join(probs), "why": c.get("why", "")})
    m = {"case_pass_rate": sum(x["passed"] for x in out) / len(out),
         "parse_exact_rate": parse_ok / parse_n if parse_n else 1.0,
         "schema_valid_rate": valid / len(out),
         "citation_accuracy": expl_ok / expl_n if expl_n else 1.0,
         "injection_recall": flagged / must_flag if must_flag else 1.0,
         "block_recall": blocked / must_block if must_block else 1.0,
         "total_cost_usd": round(client.budget.spent, 6)}
    th = s["eval"]
    failures = [k for k, ok in [("case_pass_rate", m["case_pass_rate"] >= th["min_case_pass_rate"]),
                                ("parse_exact_rate", m["parse_exact_rate"] >= th["min_parse_exact_rate"]),
                                ("schema_valid_rate", m["schema_valid_rate"] >= th["min_schema_valid_rate"]),
                                ("citation_accuracy", m["citation_accuracy"] >= th["min_citation_accuracy"]),
                                ("injection_recall", m["injection_recall"] >= th["min_injection_recall"]),
                                ("block_recall", m["block_recall"] >= th["min_block_recall"]),
                                ("total_cost_usd", m["total_cost_usd"] <= th["max_total_cost_usd"])] if not ok]
    _, _, psha = prompt(s, "parse_prompt", parse_json_schema())
    rep = {"run_id": eval_id, "ts": now(), "alias": alias, "model_name": spec.name, "model_id": spec.model_id,
           "prompt_sha": psha, "metrics": m, "failures": failures, "passed": not failures, "cases": out}
    d = workspace() / "output" / "evals"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"latest_{spec.name}.json").write_text(json.dumps(rep, indent=2))
    (d / f"{rep['ts'][:19].replace(':', '')}_{spec.name}.json").write_text(json.dumps(rep, indent=2))
    return rep


def compare(candidate: dict, baseline: dict) -> list[str]:
    return [f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}"
            for k in ("case_pass_rate", "parse_exact_rate", "schema_valid_rate", "citation_accuracy",
                      "injection_recall", "block_recall") if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]]


def latest_report(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
