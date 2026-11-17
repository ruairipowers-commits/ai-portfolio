"""Command-line entry point: `event-backtester <command>` or `python -m event_backtester <command>`."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import evals, telemetry
from .data import load_csv
from .llm import Registry
from .store import ROOT, Settings, connect, rows, workspace
from .workflow import STRATEGIES, build_prompt, decide, report_run, run


def dataset_path(s: Settings) -> Path:
    return workspace() / s["dataset_path"]


def load_ticks(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix == ".parquet" else load_csv(path.read_bytes())


def cmd_data(args, s):
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_sample_data
    generate_sample_data.main(dataset_path(s).parent)


def cmd_run(args, s):
    p = Path(args.dataset) if args.dataset else dataset_path(s)
    if not p.exists():
        sys.exit(f"No dataset at {p}; run `event-backtester data` first.")
    params = json.loads(args.params) if args.params else None
    try:
        res = run(s, load_ticks(p), kind=args.strategy, params=params, notes=args.notes or "", trials=args.trials,
                  alias=args.alias, dataset=p.name)
    except telemetry.WorkflowDisabled as e:
        sys.exit(str(e))
    print(res.gate.message)
    if not res.gate.ok:
        sys.exit("Blocked (DATA-02): the tick data failed the gate; no backtest ran and the model was never called.")
    m = res.memo
    for c in res.checks:
        print(f"  {'PASS' if c['passed'] else 'FAIL'} {c['check']:16s} {c['value']} (needs {c['threshold']})")
    keys = ["net_sharpe", "gross_sharpe", "net_total_return", "max_drawdown", "fills", "oos_sharpe",
            "selection_adjusted_t", "sharpe_at_stress_costs", "kernel_parity_max_diff_usd"]
    print("metrics:", json.dumps({k: res.metrics.get(k) for k in keys}))
    out = workspace() / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "memo.md").write_text(render_memo(res))
    if res.error:
        sys.exit(f"Stopped: {res.error}")
    print(f"memo: model {m.model_recommendation} → final {m.final_recommendation}; promotable={m.promotable}")
    for b in m.blockers:
        print("  blocked:", b)
    print(f"run {res.run_id}: memo in output/memo.md, spend ${res.spend_usd:.4f}")


def render_memo(res) -> str:
    m = res.memo
    me = m.memo
    lines = [f"# Research memo — {me.strategy} (run {res.run_id})", "",
             f"**Final recommendation: {m.final_recommendation}** · promotable: **{m.promotable}**  ",
             f"Model draft: {m.model_recommendation} (model `{m.model_name}`)", "", me.thesis, "",
             "| Headline (net) | Value |", "|---|---|",
             *[f"| {k} | {v} |" for k, v in me.headline.model_dump().items()], "",
             "## Promotion checks (computed by code)", "| Check | Value | Threshold | Result |", "|---|---|---|---|",
             *[f"| {c['check']} | {c['value']} | {c['threshold']} | {'✅' if c['passed'] else '❌'} |" for c in res.checks],
             "", "## Figures (checked against the run)", "| Metric | Value |", "|---|---|",
             *[f"| {f.metric} | {f.value} |" for f in me.figures], "", "## Risks", *[f"- {r}" for r in me.risks or ["—"]],
             "", "## Disclosures", *[f"- {d}" for d in me.disclosures or ["— (missing)"]]]
    if m.blockers:
        lines += ["", "**Blocked:** " + "; ".join(m.blockers)]
    lines += ["", "_AI-drafted. A named PM approves or rejects promotion (`event-backtester decide`)._"]
    return "\n".join(lines) + "\n"


def cmd_decide(args, s):
    run_id = args.run or (rows(connect(s), "select run_id from runs where gate_ok=1 and run_id not like 'eval-%' "
                                           "order by started desc limit 1") or [{}])[0].get("run_id")
    ok, msg = decide(s, run_id, args.decision, args.reviewer, args.reason)
    print(msg)
    sys.exit(0 if ok else 1)


def cmd_eval(args, s):
    rep = evals.run_eval(s, args.alias)
    report_run(connect(s), rep["run_id"], 0, 0, event_type="eval", status="ok" if rep["passed"] else "failed",
               flags=() if rep["passed"] else ("eval_failed",), detail={"metrics": rep["metrics"]})
    print(json.dumps(rep["metrics"], indent=2))
    for c in rep["cases"]:
        print(f"  {c['id']} {'PASS' if c['passed'] else 'FAIL'} final={c['final']} {c['problems']}")
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


def cmd_ui(args, s):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], cwd=ROOT)


def cmd_all(args, s):
    cmd_data(args, s)
    args.dataset, args.alias, args.params, args.notes, args.trials, args.strategy = None, None, None, "", 1, "MA crossover"
    cmd_run(args, s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="event-backtester", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="generate synthetic ticks (seeded)").set_defaults(fn=cmd_data)
    r = sub.add_parser("run", help="gate → backtest + checks → memo")
    r.add_argument("--dataset"); r.add_argument("--strategy", default="MA crossover", choices=list(STRATEGIES))
    r.add_argument("--params", help='JSON, e.g. \'{"fast": 5, "slow": 30}\''); r.add_argument("--notes")
    r.add_argument("--trials", type=int, default=1, help="how many variants you tried (selection haircut)")
    r.add_argument("--alias"); r.set_defaults(fn=cmd_run)
    d = sub.add_parser("decide", help="a PM approves or rejects promotion to paper trading")
    d.add_argument("decision", choices=["APPROVE", "REJECT"]); d.add_argument("--reviewer", required=True)
    d.add_argument("--reason", default=""); d.add_argument("--run"); d.set_defaults(fn=cmd_decide)
    e = sub.add_parser("eval", help="golden-set evals; non-zero exit on failure")
    e.add_argument("--alias", default="memo-primary"); e.add_argument("--baseline"); e.set_defaults(fn=cmd_eval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed evals")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check", help="approval, pricing and deprecation check")
    mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report", help="tokens and $ by month and model").set_defaults(fn=cmd_cost_report)
    sub.add_parser("all", help="data → run").set_defaults(fn=cmd_all)
    sub.add_parser("ui", help="Streamlit app: input → run → output, plus the research lab").set_defaults(fn=cmd_ui)
    args = p.parse_args(argv)
    args.fn(args, Settings.load())


if __name__ == "__main__":
    main()
