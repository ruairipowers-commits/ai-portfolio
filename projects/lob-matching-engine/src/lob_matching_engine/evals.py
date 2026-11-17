"""Eval suite and promotion gate (EVAL-01..03, MODEL-02, HITL-03)."""
from __future__ import annotations

import json
import re

import yaml

from . import sessions
from .store import ROOT, Settings, connect, now, rows, workspace
from .workflow import build_prompt, client_for, new_run_id, run

PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\+?\d[\d\s().-]{8,}\d")


def load_golden(s: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / s["eval"]["golden_set"]).read_text())["cases"]


def _session(sc: dict):
    kw = {"seed": sc.get("seed", 7), "behaviours": tuple(sc.get("behaviours", sessions.BEHAVIOURS))}
    if "layer_memo" in sc:
        kw["layer_memo"] = sc["layer_memo"]
    return sessions.generate(**kw)


def run_eval(s: Settings, alias: str) -> dict:
    client = client_for(s, s["eval"]["max_total_cost_usd"])
    spec = client.registry.resolve(alias)
    eval_id = "eval-" + new_run_id()
    cases, out = load_golden(s), []
    exp_total = found_total = fp = 0
    n_narr = valid = cite_ok = 0
    must_flag = flagged = 0
    pii_leaks = 0
    for c in cases:
        res = run(s, _session(c["scenario"]), alias=alias, source="eval", run_id=f"{eval_id}-{c['id']}",
                  client=client, store_events=False)
        e = c["expect"]
        by = {r.pattern: r for r in res.results}
        got = sorted({a["pattern"] for a in res.alerts})
        want = sorted(e.get("patterns", []))
        problems = []
        exp_total += len(want)
        found_total += len(set(want) & set(got))
        extra = set(got) - set(want)
        fp += len(extra)
        if set(want) - set(got):
            problems.append(f"missed {sorted(set(want) - set(got))}")
        if extra:
            problems.append(f"unexpected {sorted(extra)}")
        for p, fin in (e.get("final") or {}).items():
            if p in by and by[p].final_suggestion != fin:
                problems.append(f"{p}: final {by[p].final_suggestion} != {fin}")
        for p, m in (e.get("model") or {}).items():
            if p in by and by[p].model_suggestion != m:
                problems.append(f"{p}: model drafted {by[p].model_suggestion}, case expects {m}")
        for p in e.get("flagged", []):
            must_flag += 1
            if p in by and by[p].injection_suspected:
                flagged += 1
            else:
                problems.append(f"{p}: injection not flagged")
        if e.get("no_self_trades"):
            ev = res.replay.events
            selfp = ev[(ev.event == "trade") & (ev.trader == ev.maker_trader)]
            if len(selfp):
                problems.append(f"{len(selfp)} self-trades printed")
        if e.get("no_pii_in_payload"):
            leaks = sum(len(PII.findall(p)) for p in res.payloads)
            pii_leaks += leaks
            if leaks:
                problems.append(f"{leaks} PII strings reached the model")
        if "figures_match_clean_seed" in e:
            clean = run(s, _session({"seed": e["figures_match_clean_seed"], "behaviours": c["scenario"]["behaviours"]}),
                        alias=alias, source="eval", run_id=f"{eval_id}-{c['id']}-clean", client=client, store_events=False)
            cb = {r.pattern: r for r in clean.results}
            for p, r in by.items():
                if p in cb and [f.model_dump() for f in r.narrative.figures] != [f.model_dump() for f in cb[p].narrative.figures]:
                    problems.append(f"{p}: figures changed when memos were injected")
        for r in res.results:
            n_narr += 1
            valid += r.schema_valid
            cite_ok += not r.citation_errors
        if e.get("citations_clean") and any(r.citation_errors for r in res.results):
            problems.append("citation errors")
        out.append({"id": c["id"], "tags": c.get("tags", []), "why": c.get("why", ""), "alerts": got,
                    "final": {p: r.final_suggestion for p, r in by.items()}, "passed": not problems,
                    "problems": "; ".join(problems)})
    m = {
        "cases_passed": sum(x["passed"] for x in out), "cases": len(out),
        "detection_recall": found_total / exp_total if exp_total else 1.0,
        "false_positive_alerts": fp,
        "schema_valid_rate": valid / n_narr if n_narr else 1.0,
        "citation_accuracy": cite_ok / n_narr if n_narr else 1.0,
        "injection_recall": flagged / must_flag if must_flag else 1.0,
        "pii_leaks": pii_leaks,
        "total_cost_usd": round(client.budget.spent, 6),
    }
    con = connect(s)
    disp = rows(con, "select decision, agrees_with_ai from dispositions")
    m["human_agreement"] = (sum(d["agrees_with_ai"] for d in disp) / len(disp)) if disp else None   # HITL-03
    th = s["eval"]
    failures = [k for k, ok in [
        ("cases", m["cases_passed"] == m["cases"]),
        ("detection_recall", m["detection_recall"] >= th["min_detection_recall"]),
        ("false_positive_alerts", m["false_positive_alerts"] <= th["max_false_positive_alerts"]),
        ("schema_valid_rate", m["schema_valid_rate"] >= th["min_schema_valid_rate"]),
        ("citation_accuracy", m["citation_accuracy"] >= th["min_citation_accuracy"]),
        ("injection_recall", m["injection_recall"] >= th["min_injection_recall"]),
        ("pii_leaks", m["pii_leaks"] <= th["max_pii_leaks"]),
        ("total_cost_usd", m["total_cost_usd"] <= th["max_total_cost_usd"]),
    ] if not ok]
    _, _, psha = build_prompt(s)
    rep = {"run_id": eval_id, "ts": now(), "alias": alias, "model_name": spec.name, "model_id": spec.model_id,
           "prompt_sha": psha, "metrics": m, "failures": failures, "passed": not failures, "cases": out}
    d = workspace() / "output" / "evals"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"latest_{spec.name}.json").write_text(json.dumps(rep, indent=2))
    (d / f"{rep['ts'][:19].replace(':', '')}_{spec.name}.json").write_text(json.dumps(rep, indent=2))
    return rep


def compare(candidate: dict, baseline: dict) -> list[str]:
    reg = []
    for k in ("detection_recall", "schema_valid_rate", "citation_accuracy", "injection_recall"):
        if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]:
            reg.append(f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}")
    for k in ("false_positive_alerts", "pii_leaks"):
        if candidate["metrics"][k] > baseline["metrics"][k]:
            reg.append(f"{k}: {candidate['metrics'][k]} > baseline {baseline['metrics'][k]}")
    return reg


def latest_report(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
