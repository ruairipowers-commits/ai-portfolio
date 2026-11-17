"""Command-line entry point: `lob-matching-engine <command>` or `python -m lob_matching_engine <command>`."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import evals, sessions, telemetry
from .llm import Registry
from .store import ROOT, Settings, connect, rows, workspace
from .workflow import build_prompt, dispose, report_run, run


def session_path(name: str = "default") -> Path:
    return workspace() / "data" / "sessions" / f"{name}.csv"


def cmd_data(args, s):
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_sample_data
    generate_sample_data.main(workspace() / "data" / "sessions")


def cmd_run(args, s):
    p = Path(args.session) if args.session else session_path()
    if not p.exists():
        sys.exit(f"No session at {p}; run `lob-matching-engine data` first.")
    try:
        res = run(s, sessions.read_csv(p.read_bytes()), alias=args.alias, source=p.name)
    except telemetry.WorkflowDisabled as e:
        sys.exit(str(e))
    print(res.gate.message)
    if not res.gate.ok:
        sys.exit("Blocked (DATA-02): the session failed the data gate; the engine and the model were never called.")
    print("market quality:", json.dumps(res.replay.stats))
    out = workspace() / "output"
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# Surveillance run {res.run_id}", "", f"Spend: ${res.spend_usd:.4f}", "",
             "| Alert | Pattern | Severity | Model suggested | Final suggestion | Overrides |", "|---|---|---|---|---|---|"]
    for r in res.results:
        lines.append(f"| {r.alert_id} | {r.pattern} | {r.severity} | {r.model_suggestion} | **{r.final_suggestion}** | "
                     f"{'; '.join(r.policy_overrides) or '—'} |")
        print(f"{r.alert_id} {r.pattern:9s} {r.severity:6s} model {r.model_suggestion:10s} final {r.final_suggestion}")
    (out / "alerts_summary.md").write_text("\n".join(lines) + "\n\n_Advisory. An analyst closes or escalates every "
                                            "alert (`lob-matching-engine review`)._\n")
    if res.error:
        sys.exit(f"Stopped: {res.error}")
    print(f"run {res.run_id}: {len(res.alerts)} alerts, summary in output/alerts_summary.md")


def cmd_review(args, s):
    run_id = args.run or (rows(connect(s), "select run_id from runs where gate_ok=1 and run_id not like 'eval-%' "
                                           "order by started desc limit 1") or [{}])[0].get("run_id")
    ok, msg = dispose(s, run_id, args.alert, args.decision, args.reviewer, args.reason)
    print(msg)
    sys.exit(0 if ok else 1)


def cmd_eval(args, s):
    rep = evals.run_eval(s, args.alias)
    con = connect(s)
    report_run(con, rep["run_id"], 0, event_type="eval", status="ok" if rep["passed"] else "failed",
               flags=() if rep["passed"] else ("eval_failed",), detail={"metrics": rep["metrics"]})
    print(json.dumps(rep["metrics"], indent=2))
    for c in rep["cases"]:
        print(f"  {c['id']} {'PASS' if c['passed'] else 'FAIL'} {c['problems']}")
    ok = rep["passed"]
    if args.baseline:
        base_name = Registry(ROOT / "config" / "models.yaml").resolve(args.baseline).name
        base = evals.latest_report(base_name) or evals.run_eval(s, args.baseline)
        reg = evals.compare(rep, base)
        if reg:
            print("REGRESSION vs baseline:", *reg, sep="\n  ")
            ok = False
    print("EVAL GATE:", "PASS" if ok else f"FAIL {rep['failures']}")
    sys.exit(0 if ok else 1)


def cmd_promote(args, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    rep = evals.latest_report(args.model)
    _, _, current = build_prompt(s)
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {args.model}: no passing eval on record (MODEL-02).")
    if rep["prompt_sha"] != current:
        sys.exit("Refusing to promote: the prompt changed since the last eval. Re-run eval.")
    reg.set_alias(args.alias, args.model)
    print(f"{args.alias} -> {args.model} (eval {rep['run_id']} passed)")


def cmd_models_check(args, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    warn = s["governance"]["deprecation_warning_days"]
    today = date.fromisoformat(args.today) if args.today else date.today()
    rc = 0
    for alias, name in reg.aliases.items():
        m = reg.models[name]
        issues = [x for x, bad in [("not approved", not m.approved), ("no pricing", not m.priced()),
                                   (f"deprecates {m.deprecation_date} — start migration runbook",
                                    bool(m.deprecation_date and m.deprecation_date - today <= timedelta(days=warn)))] if bad]
        print(f"{alias:20s} -> {name:14s} {m.provider}:{m.model_id} {'OK' if not issues else '; '.join(issues)}")
        rc |= bool(issues)
    sys.exit(rc)


def cmd_cost_report(args, s):
    con = connect(s)
    data = rows(con, """select substr(call_ts,1,7) mth, model_name, case when run_id like 'eval-%' then 'eval' else 'prod' end kind,
                               count(*) calls, sum(input_tokens) tin, sum(output_tokens) tout, round(sum(cost_usd),4) usd
                        from ai_calls where status='ok' group by 1,2,3 order by 1,2,3""")
    limit = s["cost"]["monthly_alert_usd"]
    totals: dict[str, float] = {}
    print(f"{'month':8s} {'model':14s} {'kind':5s} {'calls':>6s} {'in_tok':>8s} {'out_tok':>8s} {'usd':>8s}")
    for r in data:
        totals[r["mth"]] = totals.get(r["mth"], 0) + r["usd"]
        print(f"{r['mth']:8s} {r['model_name']:14s} {r['kind']:5s} {r['calls']:6d} {r['tin']:8d} {r['tout']:8d} {r['usd']:8.4f}")
    for mo, usd in totals.items():
        print(f"{mo} total ${usd:.4f} vs alert ${limit:.2f}" + ("  <-- OVER ALERT (COST-04)" if usd > limit else ""))
    print("budget-blocked calls:", con.execute("select count(*) from ai_calls where status='budget_blocked'").fetchone()[0])


def cmd_bench(args, s):
    from . import _engine
    r = _engine.benchmark(n_orders=args.n, prefill=args.prefill)
    p = dict(r["percentiles"])
    print(f"{r['n_ops']:,} commands · {r['throughput_ops'] / 1e6:.2f} M ops/s · p50 {p[0.5]} ns · p99 {p[0.99]} ns · "
          f"p99.9 {p[0.999]} ns · max {p[1.0] / 1e3:.1f} µs (timer overhead ≈ {r['timer_overhead_ns']:.0f} ns)")
    print(pd.DataFrame(r["per_kind"]).to_string(index=False))


def cmd_ui(args, s):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], cwd=ROOT)


def cmd_all(args, s):
    cmd_data(args, s)
    args.session, args.alias = None, None
    cmd_run(args, s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="lob-matching-engine", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="generate synthetic sessions (seeded)").set_defaults(fn=cmd_data)
    r = sub.add_parser("run", help="gate → replay → detect → narratives")
    r.add_argument("--session"); r.add_argument("--alias"); r.set_defaults(fn=cmd_run)
    rv = sub.add_parser("review", help="an analyst closes or escalates an alert")
    rv.add_argument("alert"); rv.add_argument("decision", choices=["CLOSE", "ESCALATE"])
    rv.add_argument("--reviewer", required=True); rv.add_argument("--reason", default="")
    rv.add_argument("--run"); rv.set_defaults(fn=cmd_review)
    e = sub.add_parser("eval", help="golden-set evals; non-zero exit on failure")
    e.add_argument("--alias", default="narrative-primary"); e.add_argument("--baseline"); e.set_defaults(fn=cmd_eval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed evals")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check", help="approval, pricing and deprecation check")
    mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report", help="tokens and $ by month and model").set_defaults(fn=cmd_cost_report)
    b = sub.add_parser("bench", help="native engine benchmark (throughput, tail latency)")
    b.add_argument("--n", type=int, default=1_000_000); b.add_argument("--prefill", type=int, default=10_000)
    b.set_defaults(fn=cmd_bench)
    sub.add_parser("all", help="data → run").set_defaults(fn=cmd_all)
    sub.add_parser("ui", help="Streamlit app: input → run → output, plus the engine lab").set_defaults(fn=cmd_ui)
    args = p.parse_args(argv)
    args.fn(args, Settings.load())


if __name__ == "__main__":
    main()
