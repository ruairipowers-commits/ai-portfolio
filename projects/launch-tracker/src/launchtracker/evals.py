"""Eval suite and promotion gate (EVAL-01..03, MODEL-02). Runs on the offline sample; the mock costs nothing."""
from __future__ import annotations

import copy
import json
import re
from datetime import date

import yaml

from . import analytics, guardrails, reference, summaries
from .config import ROOT, Settings, utcnow, workspace
from .db import scalar


def load_cases(settings: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / settings["eval"]["golden_set"]).read_text())["cases"]


def _with(settings: Settings, overrides: dict | None) -> Settings:
    if not overrides:
        return settings
    raw = copy.deepcopy(settings.raw)
    for dotted, v in overrides.items():
        d = raw
        *path, last = dotted.split(".")
        for k in path:
            d = d[k]
        d[last] = v
    return Settings(raw)


def run_case(con, settings: Settings, c: dict, alias: str, llm) -> dict:
    s = _with(settings, c.get("settings"))
    e = c["expect"]
    subject = scalar(con, c["subject_sql"]) if c.get("subject_sql") else None
    got: dict = {"subject": subject}
    ok, why = True, []

    def need(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            why.append(msg)

    if c.get("subject_sql") and not subject:
        return {"id": c["id"], "passed": False, "why": ["no subject found in the data (run `launches build` first?)"],
                "got": got, "tags": c.get("tags", []), "kind": c["kind"]}
    if c["kind"] in ("mission", "digest"):
        r = summaries.mission(con, s, subject, alias=alias, llm=llm) if c["kind"] == "mission" else \
            summaries.digest(con, s, date.fromisoformat(c["week_start"]), alias=alias, llm=llm)
        got.update({"accepted": r.accepted, "source": r.source, "flags": r.flags, "problems": r.problems,
                    "text": r.text, "cost_usd": r.cost_usd, "model_draft_ok": r.accepted})
        if "accepted" in e:
            need(r.accepted == e["accepted"], f"accepted={r.accepted}")
        if "source" in e:
            need(r.source == e["source"], f"source={r.source}")
        if "flag" in e:
            need(e["flag"] in r.flags, f"flag {e['flag']} missing")
        if e.get("no_outcome_claim"):
            need(not re.search(guardrails.OUTCOME_WORDS["failure"] + "|" + guardrails.OUTCOME_WORDS["cancelled"], r.text, re.I),
                 "final text repeats the injected claim")
        if "launches_sql" in e:
            need(r.facts.get("launches") == scalar(con, e["launches_sql"]), "digest count differs from SQL")
        # every accepted text passes the number check against its own facts (checked again, independently)
        if r.accepted:
            stray = guardrails._numbers(r.text) - guardrails.allowed_numbers(r.facts)
            need(not stray, f"numbers not in the data: {sorted(stray)}")
    elif c["kind"] == "cost":
        L = analytics.launch(con, s, subject)["launch"]
        st = reference.cost_for(con, s, L)["status"]
        got["cost_status"] = st
        need(st == e["cost_status"], f"cost status {st}")
    elif c["kind"] == "slips":
        r = analytics.slips(con, subject)[0]
        got.update({"slip_days": r["slip_days"], "changes": r["changes"]})
        need(r["slip_days"] == e["slip_days"] and r["changes"] == e["changes"], f"slip {r['slip_days']} / {r['changes']}")
    elif c["kind"] == "image":
        d = analytics.launch(con, s, subject)["image"]
        got.update(d)
        need(d["show"] == e["show"] and bool(d.get("link")) == e["link"], f"image decision {d}")
    elif c["kind"] == "discrepancy":
        n = scalar(con, "select count(*) from discrepancies where field = ?", [e["field"]])
        got["count"] = n
        need(n == e["count"], f"{n} discrepancies")
    elif c["kind"] == "retirement":
        r = {x["rocket"]: x for x in analytics.retirements(con, s)}
        got["retired"] = sorted(r)
        need(e["rocket"] in r and r[e["rocket"]]["retired_year"] == e["retired_year"], "not listed as retired")
    return {"id": c["id"], "passed": ok, "why": why, "got": got, "tags": c.get("tags", []), "kind": c["kind"]}


def run_eval(con, settings: Settings, alias: str | None = None) -> dict:
    alias = alias or settings["llm"]["summary_alias"]
    llm = summaries.client(settings, budget_usd=settings["eval"]["max_total_cost_usd"])
    spec = llm.registry.resolve(alias)
    results = [run_case(con, settings, c, alias, llm) for c in load_cases(settings)]
    ai = [r for r in results if r["kind"] in ("mission", "digest")]
    model_drafts = [r for r in ai if r["got"].get("source") == "model" or "draft_rejected" in r["got"].get("flags", [])]
    must_flag = [r for r in results if "must_flag" in r["tags"]]
    metrics = {
        "accuracy": round(sum(r["passed"] for r in results) / len(results), 3),
        # of the drafts the guard accepted, how many had every citation and number right (re-checked independently)
        "citation_accuracy": round(sum(r["passed"] for r in ai if r["got"].get("accepted")) /
                                   max(1, sum(1 for r in ai if r["got"].get("accepted"))), 3),
        "injection_flag_recall": round(sum("injection_suspected" in r["got"].get("flags", []) for r in must_flag) /
                                       max(1, len(must_flag)), 3),
        "drafts_rejected": sum(1 for r in model_drafts if not r["got"].get("accepted")),
        "total_cost_usd": round(llm.budget.spent, 6),
    }
    th = settings["eval"]
    failures = [k for k, ok in [("accuracy", metrics["accuracy"] >= th["min_accuracy"]),
                                ("citation_accuracy", metrics["citation_accuracy"] >= th["min_citation_accuracy"]),
                                ("injection_flag_recall", metrics["injection_flag_recall"] >= th["min_injection_flag_recall"]),
                                ("total_cost_usd", metrics["total_cost_usd"] <= th["max_total_cost_usd"])] if not ok]
    report = {"ts": utcnow().isoformat(), "alias": alias, "model": spec.name, "model_id": spec.model_id,
              "metrics": metrics, "failures": failures, "passed": not failures, "cases": results}
    out = workspace() / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"latest_{spec.name}.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def compare(candidate: dict, baseline: dict) -> list[str]:
    """MODEL-02: a candidate must match or beat the baseline on every quality metric."""
    return [f"{k}: {candidate['metrics'][k]} < baseline {baseline['metrics'][k]}"
            for k in ("accuracy", "citation_accuracy", "injection_flag_recall")
            if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]]


def latest(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None
