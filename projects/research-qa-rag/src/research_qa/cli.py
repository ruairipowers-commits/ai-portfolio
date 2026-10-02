"""rqa — Research Q&A command line. Everything runs offline with the mock models by default."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from . import evals, telemetry
from .answer import IndexMismatch, ask, prompt
from .ingest import ingest
from .llm import Registry
from .store import ROOT, Settings, connect


def reset_corpus(s: Settings) -> str:
    """Regenerate the synthetic corpus and drop the index (used by `rqa data` and the app's Reset)."""
    shutil.rmtree(s.corpus_dir, ignore_errors=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(s.db_path) + suffix).unlink(missing_ok=True)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_corpus.py")], capture_output=True, text=True,
                       env={**__import__("os").environ, "RQA_CORPUS_DIR": str(s.corpus_dir)})
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return r.stdout.strip()


def cmd_data(a, s):
    print(reset_corpus(s))


def cmd_ingest(a, s):
    st = ingest(s, embedding_alias=a.embedding, full=a.full)
    print(json.dumps(st, indent=2))


def cmd_ask(a, s):
    r = ask(s, a.question, a.user, alias=a.alias, mode=a.mode, actor=a.user)
    if r["status"] == "answered":
        print(r["answer"])
        for c in r["citations"]:
            print(f"  [{c['doc_id']} p.{c['page']}] \"{c['quote'][:100]}\"")
    else:
        print(f"REFUSED: {r['refusal_reason']}")
    print(f"  flags={r['flags']} index={r['index_version']} model={r['model_name'] or '-'} "
          f"cost=${r['cost_usd']:.5f} {r['latency_ms']}ms excluded(entitlement)={r['excluded_entitlement']}")


def cmd_eval(a, s):
    rep = evals.run_eval(s, a.alias, a.mode)
    print(json.dumps(rep["metrics"], indent=2))
    for c in rep["cases"]:
        if not c["passed"]:
            print(f"  FAIL {c['id']} ({c['user']}): expected {c['expect']}, got {c['status']}: {c['answer'][:90]}")
    ok = rep["passed"]
    if a.baseline:
        base_name = Registry(ROOT / "config" / "models.yaml").resolve(a.baseline).name
        base = evals.latest_report(base_name) or evals.run_eval(s, a.baseline, a.mode)
        regress = evals.compare(rep, base)
        if regress:
            print("REGRESSION vs baseline:", *regress, sep="\n  ")
            ok = False
    print("EVAL GATE:", "PASS" if ok else f"FAIL {rep['failures']}")
    sys.exit(0 if ok else 1)


def cmd_compare_retrieval(a, s):
    print(f"{'mode':8s} {'recall@k':>9s} {'MRR':>6s}")
    for r in evals.retrieval_comparison(s):
        print(f"{r['mode']:8s} {r['recall_at_k']:9.3f} {r['mrr']:6.3f}   (k={r['k']}, {r['questions']} answerable questions)")


def cmd_promote(a, s):
    rep = evals.latest_report(a.model)
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {a.model}: no passing eval on record (MODEL-02).")
    if rep["prompt_sha"] != prompt(s)[1]:
        sys.exit("Refusing to promote: prompt changed since the last eval. Re-run eval.")
    con = connect(s)
    try:
        idx = con.execute("select index_version from index_runs where active = 1").fetchone()
    finally:
        con.close()
    if not idx or rep["index_version"] != idx[0]:
        sys.exit("Refusing to promote: the index changed since the last eval. Re-run eval.")
    Registry(ROOT / "config" / "models.yaml").set_alias(a.alias, a.model)
    print(f"{a.alias} -> {a.model} (eval {rep['run_id']} passed)")


def cmd_models_check(a, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    warn = s["governance"]["deprecation_warning_days"]
    today = date.fromisoformat(a.today) if a.today else date.today()
    rc = 0
    for alias, name in reg.aliases.items():
        m = reg.models[name]
        issues = [x for x, bad in [("not approved", not m.approved), ("no pricing", not m.priced())] if bad]
        if m.deprecation_date and m.deprecation_date - today <= timedelta(days=warn):
            issues.append(f"deprecates {m.deprecation_date} — start migration runbook")
        print(f"{alias:18s} -> {name:16s} {m.provider}:{m.model_id} {'OK' if not issues else '; '.join(issues)}")
        rc |= bool(issues)
    sys.exit(rc)


def cmd_cost_report(a, s):
    con = connect(s)
    try:
        rows = con.execute("""select substr(ts, 1, 7) as mth, coalesce(nullif(model_name, ''), '(no model call)') as model,
                                     case when run_id like 'eval-%' then 'eval' else 'prod' end as kind, count(*) as n,
                                     sum(input_tokens), sum(output_tokens), round(sum(cost_usd), 5),
                                     sum(status = 'refused')
                              from answers group by 1, 2, 3 order by 1, 2, 3""").fetchall()
    finally:
        con.close()
    limit = s["cost"]["monthly_alert_usd"]
    print(f"{'month':8s} {'model':18s} {'kind':5s} {'answers':>7s} {'in_tok':>8s} {'out_tok':>8s} {'usd':>9s} {'refused':>8s}")
    totals: dict[str, float] = {}
    for mo, mn, kind, n, ti, to, usd, ref in rows:
        totals[mo] = totals.get(mo, 0) + usd
        print(f"{mo:8s} {mn:18s} {kind:5s} {n:7d} {ti:8d} {to:8d} {usd:9.5f} {ref:8d}")
    for mo, usd in totals.items():
        print(f"{mo} total ${usd:.4f} vs alert ${limit:.2f}" + ("  <-- OVER ALERT (COST-04)" if usd > limit else ""))


def cmd_serve(a, s):
    import uvicorn

    uvicorn.run("research_qa.api:app", host=a.host, port=a.port)


def cmd_ui(a, s):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], cwd=ROOT)


def cmd_all(a, s):
    cmd_data(a, s)
    a.embedding, a.full = None, True
    cmd_ingest(a, s)
    cmd_compare_retrieval(a, s)
    for user, q in [("public-analyst", "What was Halvorsen Robotics' revenue in fiscal 2025?"),
                    ("public-analyst", "What is Northbridge's price target on Halvorsen Robotics?"),
                    ("equity-analyst", "What is Northbridge's price target on Halvorsen Robotics?"),
                    ("portfolio-manager", "How does Aldgate rate Brightwater Utilities?")]:
        print(f"\n[{user}] {q}")
        a.question, a.user, a.alias, a.mode = q, user, None, None
        cmd_ask(a, s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="rqa", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="regenerate the synthetic corpus (drops the index)").set_defaults(fn=cmd_data)
    i = sub.add_parser("ingest", help="parse, screen, chunk, embed and index (incremental)")
    i.add_argument("--embedding", help="embedding model or alias (default: llm.embedding_alias)")
    i.add_argument("--full", action="store_true", help="re-index every document")
    i.set_defaults(fn=cmd_ingest)
    q = sub.add_parser("ask", help="ask a question as one of the demo analysts")
    q.add_argument("question"); q.add_argument("--user", default="public-analyst")
    q.add_argument("--alias"); q.add_argument("--mode", choices=["hybrid", "bm25", "vector"]); q.set_defaults(fn=cmd_ask)
    e = sub.add_parser("eval", help="golden-set eval gate; non-zero exit on failure")
    e.add_argument("--alias", default="answer-primary"); e.add_argument("--baseline")
    e.add_argument("--mode", choices=["hybrid", "bm25", "vector"]); e.set_defaults(fn=cmd_eval)
    sub.add_parser("compare-retrieval", help="recall@k and MRR for bm25 vs vector vs hybrid").set_defaults(
        fn=cmd_compare_retrieval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed evals")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check", help="approval, pricing and deprecation check")
    mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report", help="tokens and $ by month, model, prod vs eval").set_defaults(fn=cmd_cost_report)
    sv = sub.add_parser("serve", help="FastAPI service (OpenAPI docs at /docs)")
    sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    sub.add_parser("ui", help="Streamlit app").set_defaults(fn=cmd_ui)
    sub.add_parser("all", help="data -> ingest -> retrieval comparison -> sample questions").set_defaults(fn=cmd_all)
    a = p.parse_args(argv)
    s = Settings.load()
    telemetry.register(ROOT)
    try:
        a.fn(a, s)
    except (IndexMismatch, telemetry.WorkflowDisabled) as e:
        sys.exit(f"Blocked: {e}")


if __name__ == "__main__":
    main()
