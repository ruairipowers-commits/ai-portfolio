"""Eval suite and promotion gate (EVAL-01..03, MODEL-02, HITL-03)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from sqlmodel import select

from . import catalog, context, licensing, lifecycle, monetize, search, store
from .ai import Runner
from .config import ROOT, Settings, now
from .llm import Budget


def load_golden(settings: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / settings["eval"]["golden_set"]).read_text())["cases"]


def _case(settings: Settings, c: dict, runner: Runner) -> dict:
    row = {"id": c["id"], "kind": c["kind"], "tags": c.get("tags", []), "expected": c.get("expected", c.get("expected_not")),
           "schema_valid": None, "grounded": None}
    k = c["kind"]
    if k == "search":
        out = search.run(settings, c["need"], c.get("customer"), runner=runner, include_marketplaces=False)
        top = [r["dataset_id"] for r in out["results"][:max(2, len(c["expected"]))]]
        row["got"] = top
        row["correct"] = all(e in top for e in c["expected"])
        row["schema_valid"] = out["plan_meta"]["model_ok"]
    elif k == "answer":
        r = context.answer(settings, c["question"], c["customer"], runner=runner)
        row["got"] = r.status
        ok = (r.status == c["expected"]) if "expected" in c else (r.status != c["expected_not"])
        ok = ok and all(x in r.answer for x in c.get("must_contain", []))
        if c.get("must_flag"):
            row["flagged"] = c["must_flag"] in r.packet.flags
            ok = ok and row["flagged"]
        row["correct"] = ok
        row["schema_valid"] = r.checks["schema_valid"]
        row["grounded"] = not r.checks["ungrounded_numbers"] and not r.checks["unknown_citations"]
        row["fallback_used"] = r.checks["fallback_used"]
    elif k == "extract":
        text = c.get("source_text") or (ROOT / c["source_file"]).read_text()
        a = catalog.extract(settings, text, c["source_url"], runner=runner)
        fields = {f["name"]: f["concept"] for f in a.payload["fields"]}
        ok = all(fields.get(n) == v for n, v in (c.get("expected") or {}).items())
        if c.get("must_flag"):
            row["flagged"] = c["must_flag"] in a.flags
            ok = ok and row["flagged"]
        for f in c.get("must_not_set", []):
            ok = ok and f not in a.payload["dataset"]
        row["got"] = {"fields": fields, "flags": a.flags, "set": sorted(a.payload["dataset"])}
        row["correct"] = ok
        row["schema_valid"] = "extraction_failed" not in a.flags
        row["grounded"] = not any(f.startswith("unquoted:") for f in a.flags)
        with store.session(settings) as s:                     # eval drafts never reach the catalog
            s.delete(s.get(store.Approval, a.id))
            s.commit()
    elif k == "licence":
        with store.session(settings) as s:
            v = licensing.assess(s, settings, c["dataset"], c["use"], c.get("customer"))
        row["got"], row["correct"] = v.verdict, v.verdict == c["expected"]
    elif k == "monetize":
        o = monetize.submit(settings, "Eval owner", (ROOT / "data/seed/sources/owner/bayline_description.md").read_text(),
                            c["sample"])
        r = monetize.assess(settings, o.id, runner=runner)
        row["got"], row["correct"] = r["status"], r["status"] == c["expected"]
        row["schema_valid"] = r["advice"] is not None if r["status"] == "assessed" else None
    elif k == "retire":
        r = lifecycle.request_retirement(settings, c["dataset"], "eval", c.get("customer"), c.get("substitute"))
        row["got"], row["correct"] = r["status"], r["status"] == c["expected"]
        if r.get("approval_id"):
            with store.session(settings) as s:
                s.delete(s.get(store.Approval, r["approval_id"]))
                s.commit()
    return row


def run_eval(settings: Settings, alias: str | None = None) -> dict:
    alias = alias or settings["llm"]["primary_alias"]
    runner = Runner(settings, alias=alias, run_id="eval-" + now().strftime("%Y%m%d%H%M%S"))
    c = settings["cost"]
    runner.budget = Budget(settings["eval"]["max_total_cost_usd"], c["max_input_tokens_per_call"], c["allow_unpriced_models"])
    runner.client.budget = runner.budget
    rows = [_case(settings, c, runner) for c in load_golden(settings)]
    n = len(rows)
    sv = [r["schema_valid"] for r in rows if r["schema_valid"] is not None]
    gr = [r["grounded"] for r in rows if r["grounded"] is not None]
    esc = [r for r in rows if "must_escalate" in r["tags"]]
    metrics = {"accuracy": round(sum(r["correct"] for r in rows) / n, 4),
               "schema_valid_rate": round(sum(sv) / len(sv), 4) if sv else 1.0,
               "citation_accuracy": round(sum(gr) / len(gr), 4) if gr else 1.0,
               "must_escalate_recall": round(sum(bool(r.get("flagged")) for r in esc) / len(esc), 4) if esc else 1.0,
               "fallback_answers": sum(1 for r in rows if r.get("fallback_used")),
               "total_cost_usd": round(runner.budget.spent, 6)}
    with store.session(settings) as s:                          # HITL-03: what reviewers changed
        fb = s.exec(select(store.Feedback)).all()
    metrics["reviewer_corrections"] = len(fb)
    th = settings["eval"]
    failures = [k for k, ok in [
        ("accuracy", metrics["accuracy"] >= th["min_accuracy"]),
        ("schema_valid_rate", metrics["schema_valid_rate"] >= th["min_schema_valid_rate"]),
        ("citation_accuracy", metrics["citation_accuracy"] >= th["min_citation_accuracy"]),
        ("must_escalate_recall", metrics["must_escalate_recall"] >= th["min_must_escalate_recall"]),
        ("total_cost_usd", metrics["total_cost_usd"] <= th["max_total_cost_usd"])] if not ok]
    spec = runner.registry.resolve(alias)
    report = {"ts": now().isoformat(), "alias": alias, "model_name": spec.name, "model_id": spec.model_id,
              "prompt_shas": {k: runner.prompt(k)[2] for k in settings["llm"]["prompts"]}, "metrics": metrics,
              "failures": failures, "passed": not failures, "cases": rows,
              "feedback": [{"subject": f.subject, "ai": f.ai_output, "human": f.human_output} for f in fb]}
    from .config import workspace
    out = workspace() / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"latest_{spec.name}.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def compare(candidate: dict, baseline: dict) -> list[str]:
    regress = []
    for k in ("accuracy", "schema_valid_rate", "citation_accuracy", "must_escalate_recall"):
        if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]:
            regress.append(f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}")
    return regress


def latest(model_name: str) -> dict | None:
    from .config import workspace
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
