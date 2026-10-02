"""Golden-set eval gate (EVAL-01/02, MODEL-02) and the retrieval comparison (BM25 vs vector vs hybrid).

Metrics (RAGAS-style, computed deterministically so they run free in CI):
  answer_accuracy     answerable questions answered with every expected fact
  refusal_accuracy    unanswerable / not-entitled / licence-barred questions refused
  citation_accuracy   answered questions whose citations are verbatim and point at the expected document
  faithfulness        mean share of answer sentences supported by their cited quotes
  context_recall      answerable questions whose expected document was in the retrieved context
  entitlement_leaks   context chunks the user may not see, or that are licence-barred / quarantined (must be 0)
  injection_resisted  no answer contains a must_not_contain string
  p95_latency_ms, total_cost_usd
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import yaml

from . import telemetry
from .answer import ask, prompt
from .llm import Registry
from .store import ROOT, Settings, connect, users, workspace


def cases(settings: Settings) -> list[dict]:
    return yaml.safe_load((ROOT / settings["eval"]["golden_set"]).read_text())["cases"]


def _leaks(con, res: dict, ents: list[str]) -> int:
    n = 0
    for c in res["context"]:
        row = con.execute("select entitlement, ai_processing, quarantined from chunks where chunk_id = ?",
                          (c["chunk_id"],)).fetchone()
        if row is None or row[0] not in ents or not row[1] or row[2]:
            n += 1
    return n


def p95(xs: list[int]) -> int:
    if not xs:
        return 0
    s = sorted(xs)
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


def run_eval(settings: Settings, alias: str = "answer-primary", mode: str | None = None, actor: str = "eval") -> dict:
    run_id = "eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    spec = Registry(ROOT / "config" / "models.yaml").resolve(alias)
    people = users(settings)
    con = connect(settings)
    rows, lat, cost, leaks = [], [], 0.0, 0
    try:
        for c in cases(settings):
            r = ask(settings, c["question"], c["user"], alias=alias, mode=mode, actor=actor, run_id=run_id,
                    action="eval")
            ents = people[c["user"]]["entitlements"]
            leak = _leaks(con, r, ents)
            leaks += leak
            lat.append(r["latency_ms"])
            cost += r["cost_usd"]
            text = r["answer"]
            ok_facts = all(m.lower() in text.lower() for m in c.get("must_contain", []))
            bad = [m for m in c.get("must_not_contain", []) if m.lower() in (text + r["refusal_reason"]).lower()]
            ctx_docs = {x["doc_id"] for x in r["context"]}
            cite_ok = bool(r["citations"]) and all(x["verbatim"] and x["doc_id"] == c.get("expected_doc")
                                                   for x in r["citations"])
            if c["expect"] == "answer":
                passed = r["status"] == "answered" and ok_facts and not bad
            else:
                passed = r["status"] == "refused" and not bad
            rows.append({"id": c["id"], "user": c["user"], "expect": c["expect"], "status": r["status"],
                         "passed": passed, "facts_ok": ok_facts, "forbidden_found": bad,
                         "citation_ok": cite_ok if r["status"] == "answered" else None,
                         "supported_ratio": r["supported_ratio"],
                         "context_recall": (c.get("expected_doc") in ctx_docs) if c["expect"] == "answer" else None,
                         "leaks": leak, "latency_ms": r["latency_ms"], "cost_usd": r["cost_usd"],
                         "answer": text or r["refusal_reason"], "flags": r["flags"], "tags": c.get("tags", [])})
    finally:
        con.close()
    ans = [r for r in rows if r["expect"] == "answer"]
    ref = [r for r in rows if r["expect"] == "refuse"]
    answered = [r for r in rows if r["status"] == "answered"]
    m = {
        "answer_accuracy": round(sum(r["passed"] for r in ans) / max(len(ans), 1), 3),
        "refusal_accuracy": round(sum(r["passed"] for r in ref) / max(len(ref), 1), 3),
        "citation_accuracy": round(sum(bool(r["citation_ok"]) for r in answered) / max(len(answered), 1), 3),
        "faithfulness": round(sum(r["supported_ratio"] or 0 for r in answered) / max(len(answered), 1), 3),
        "context_recall": round(sum(bool(r["context_recall"]) for r in ans) / max(len(ans), 1), 3),
        "entitlement_leaks": leaks,
        "injection_resisted": all(not r["forbidden_found"] for r in rows),
        "p95_latency_ms": p95(lat),
        "total_cost_usd": round(cost, 5),
        "cases": len(rows),
    }
    th = settings["eval"]
    failures = [k for k, ok in [
        ("answer_accuracy", m["answer_accuracy"] >= th["min_answer_accuracy"]),
        ("refusal_accuracy", m["refusal_accuracy"] >= th["min_refusal_accuracy"]),
        ("citation_accuracy", m["citation_accuracy"] >= th["min_citation_accuracy"]),
        ("faithfulness", m["faithfulness"] >= th["min_faithfulness"]),
        ("context_recall", m["context_recall"] >= th["min_context_recall"]),
        ("entitlement_leaks", m["entitlement_leaks"] <= th["max_entitlement_leaks"]),
        ("injection_resisted", m["injection_resisted"]),
        ("p95_latency_ms", m["p95_latency_ms"] <= th["max_p95_latency_ms"]),
        ("total_cost_usd", m["total_cost_usd"] <= th["max_total_cost_usd"]),
    ] if not ok]
    con = connect(settings)
    try:
        idx = con.execute("select index_version, embedding_model from index_runs where active = 1").fetchone()
    finally:
        con.close()
    report = {"run_id": run_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "alias": alias,
              "model_name": spec.name, "model_id": spec.model_id, "prompt_sha": prompt(settings)[1],
              "index_version": idx[0] if idx else None, "embedding_model": idx[1] if idx else None,
              "retrieval_mode": mode or settings["retrieval"]["mode"], "metrics": m, "failures": failures,
              "passed": not failures, "cases": rows}
    out = workspace() / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{run_id}_{spec.name}.json").write_text(json.dumps(report, indent=2))
    (out / f"latest_{spec.name}.json").write_text(json.dumps(report, indent=2))
    telemetry.record("eval-gate", event_type="eval", actor=actor, status="pass" if report["passed"] else "fail",
                     run_id=run_id, model=spec.name, cost_usd=m["total_cost_usd"], items=len(rows),
                     detail={"metrics": m, "failures": failures})
    return report


def compare(candidate: dict, baseline: dict) -> list[str]:
    """No-regression check for migrations."""
    keys = ("answer_accuracy", "refusal_accuracy", "citation_accuracy", "faithfulness", "context_recall")
    return [f"{k}: {candidate['metrics'][k]:.2f} < baseline {baseline['metrics'][k]:.2f}"
            for k in keys if candidate["metrics"][k] + 1e-9 < baseline["metrics"][k]]


def latest_report(model_name: str) -> dict | None:
    p = workspace() / "output" / "evals" / f"latest_{model_name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def retrieval_comparison(settings: Settings) -> list[dict]:
    """Recall@k and MRR of the expected document for each retrieval mode, over the answerable golden cases.
    Retrieval only — no model calls, no cost."""
    from .retrieve import retrieve

    reg = Registry(ROOT / "config" / "models.yaml")
    people = users(settings)
    answerable = [c for c in cases(settings) if c["expect"] == "answer"]
    out = []
    con = connect(settings)
    try:
        for mode in ("bm25", "vector", "hybrid"):
            hits, rr = 0, 0.0
            for c in answerable:
                ret = retrieve(con, c["question"], people[c["user"]]["entitlements"], settings, reg, mode=mode)
                docs = [x["doc_id"] for x in ret.chunks]
                if c["expected_doc"] in docs:
                    hits += 1
                    rr += 1 / (docs.index(c["expected_doc"]) + 1)
            out.append({"mode": mode, "recall_at_k": round(hits / len(answerable), 3),
                        "mrr": round(rr / len(answerable), 3), "k": settings["retrieval"]["top_k"],
                        "questions": len(answerable)})
    finally:
        con.close()
    return out
