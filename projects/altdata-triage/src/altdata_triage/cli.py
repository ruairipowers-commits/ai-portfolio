"""Command-line entry point: `altdata-triage <command>` or `python -m altdata_triage <command>`."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from . import evals, telemetry
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError
from .store import ROOT, Settings, connect, ingest
from .workflow import (DataQualityGateError, assert_dbt_tests_passed, build_prompt, get_vendor_facts, list_vendors,
                       new_run_id, render_memo_md, report_run, triage_vendor)


def cmd_data(args, s):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")], check=True)


def cmd_ingest(args, s):
    con = connect(s)
    print(f"Ingested {ingest(con)} vendor deliveries into raw.*")


def cmd_transform(args, s):
    env = {**os.environ, "DUCKDB_PATH": str(s.db_path)}
    vars_ = json.dumps({"as_of_date": s["as_of_date"]})
    rc = subprocess.run(["dbt", "build", "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
                         "--vars", vars_], env=env, cwd=ROOT).returncode
    if rc:
        sys.exit("dbt build failed — AI triage is blocked until data tests pass (DATA-02).")


def _client(s: Settings) -> LLMClient:
    c = s["cost"]
    return LLMClient(Registry(ROOT / "config" / "models.yaml"),
                     Budget(c["max_usd_per_run"], c["max_input_tokens_per_call"], c["allow_unpriced_models"]),
                     s["llm"]["retries"])


def cmd_triage(args, s):
    try:
        telemetry.require_enabled("triage")
    except telemetry.WorkflowDisabled as e:
        sys.exit(str(e))
    t0 = time.perf_counter()
    if s["data"]["require_dbt_tests_pass"]:
        assert_dbt_tests_passed()
    con = connect(s)
    client, run_id = _client(s), new_run_id()
    vendors = [args.vendor] if args.vendor else list_vendors(con)
    out = ROOT / "output" / "memos"
    out.mkdir(parents=True, exist_ok=True)
    summary = ["| Vendor | Rule score | Model draft | Final | Overrides |", "|---|---|---|---|---|"]
    try:
        for v in vendors:
            r = triage_vendor(con, v, s, client, run_id, alias=args.alias)
            facts = get_vendor_facts(con, v)
            (out / f"{v}.md").write_text(render_memo_md(r, facts))
            summary.append(f"| {facts['vendor_name']} ({v}) | {facts['rule_score']} | {r.llm_recommendation} | "
                           f"**{r.final_recommendation}** | {'; '.join(r.policy_overrides) or '—'} |")
            print(f"{v}: {r.final_recommendation:9s} (draft {r.llm_recommendation}) {'; '.join(r.policy_overrides)}")
    except (BudgetExceeded, RegistryError) as e:
        sys.exit(f"Stopped: {e}")
    report_run(con, run_id, "triage", int((time.perf_counter() - t0) * 1000))
    telemetry.flush()
    (ROOT / "output" / "triage_summary.md").write_text(
        f"# Vendor triage — run {run_id}\n\nSpend this run: ${client.budget.spent:.4f}\n\n" + "\n".join(summary) + "\n")
    print(f"run {run_id}: memos in output/memos/, spend ${client.budget.spent:.4f}")


def cmd_review(args, s):
    con = connect(s)
    row = con.execute("""select run_id, final_recommendation from audit.triage_results
                         where vendor_id = ? and run_id not like 'eval-%' order by result_ts desc limit 1""",
                      [args.vendor]).fetchone()
    if not row:
        sys.exit(f"No triage result for {args.vendor}; run triage first.")
    con.execute("insert into audit.reviews values (now(),?,?,?,?,?,?,?)",
                [row[0], args.vendor, args.reviewer, row[1], args.decision, row[1] == args.decision, args.note])
    telemetry.emit("review", actor=args.reviewer, actor_type="named", records_in=1, run_id=row[0],
                    flags=[] if row[1] == args.decision else ["human_override"])
    telemetry.flush()
    print(f"Recorded {args.reviewer}: {args.vendor} -> {args.decision} (AI said {row[1]})")


def cmd_eval(args, s):
    assert_dbt_tests_passed()
    con = connect(s)
    rep = evals.run_eval(con, s, args.alias)
    report_run(con, rep["run_id"], "eval", 0, status="ok" if rep["passed"] else "failed",
               extra_flags=() if rep["passed"] else ("eval_failed",), detail={"metrics": rep["metrics"]})
    telemetry.flush()
    print(json.dumps(rep["metrics"], indent=2))
    ok = rep["passed"]
    if args.baseline:
        base_name = Registry(ROOT / "config" / "models.yaml").resolve(args.baseline).name
        base = evals.latest_report(base_name) or evals.run_eval(con, s, args.baseline)
        reg = evals.compare(rep, base)
        if reg:
            print("REGRESSION vs baseline:", *reg, sep="\n  ")
            ok = False
    print("EVAL GATE:", "PASS" if ok else f"FAIL {rep['failures']}")
    sys.exit(0 if ok else 1)


def cmd_promote(args, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    rep = evals.latest_report(args.model)
    _, _, current_prompt = build_prompt(s)
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {args.model}: no passing eval on record (MODEL-02).")
    if rep["prompt_sha"] != current_prompt:
        sys.exit("Refusing to promote: prompt changed since the last eval. Re-run eval.")
    reg.set_alias(args.alias, args.model)
    print(f"{args.alias} -> {args.model} (eval {rep['run_id']} passed)")


def cmd_models_check(args, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    warn = s["governance"]["deprecation_warning_days"]
    today = date.fromisoformat(args.today) if args.today else date.today()
    rc = 0
    for alias, name in reg.aliases.items():
        m = reg.models[name]
        issues = []
        if not m.approved:
            issues.append("not approved")
        if not m.priced():
            issues.append("no pricing")
        if m.deprecation_date and m.deprecation_date - today <= timedelta(days=warn):
            issues.append(f"deprecates {m.deprecation_date} — start migration runbook")
        print(f"{alias:18s} -> {name:14s} {m.provider}:{m.model_id} {'OK' if not issues else '; '.join(issues)}")
        rc |= bool(issues)
    sys.exit(rc)


def cmd_cost_report(args, s):
    con = connect(s)
    rows = con.execute("""select strftime(call_ts, '%Y-%m') as mth, model_name,
                                 case when run_id like 'eval-%' then 'eval' else 'prod' end as kind,
                                 count(*) as calls, sum(input_tokens) as tin, sum(output_tokens) as tout,
                                 round(sum(cost_usd), 4) as usd
                          from audit.ai_calls where status = 'ok' group by all order by all""").fetchall()
    limit = s["cost"]["monthly_alert_usd"]
    print(f"{'month':8s} {'model':14s} {'kind':5s} {'calls':>6s} {'in_tok':>8s} {'out_tok':>8s} {'usd':>8s}")
    totals: dict[str, float] = {}
    for mo, mn, kind, c, ti, to, usd in rows:
        totals[mo] = totals.get(mo, 0) + usd
        print(f"{mo:8s} {mn:14s} {kind:5s} {c:6d} {ti:8d} {to:8d} {usd:8.4f}")
    for mo, usd in totals.items():
        print(f"{mo} total ${usd:.4f} vs alert ${limit:.2f}" + ("  <-- OVER ALERT (COST-04)" if usd > limit else ""))
    blocked = con.execute("select count(*) from audit.ai_calls where status = 'budget_blocked'").fetchone()[0]
    print(f"budget-blocked calls: {blocked}")


def cmd_ui(args, s):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], cwd=ROOT)


def cmd_all(args, s):
    for f in (cmd_data, cmd_ingest, cmd_transform):
        f(args, s)
    args.vendor, args.alias = None, None
    cmd_triage(args, s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="altdata-triage", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="generate synthetic vendor deliveries").set_defaults(fn=cmd_data)
    sub.add_parser("ingest", help="land raw files into DuckDB").set_defaults(fn=cmd_ingest)
    sub.add_parser("transform", help="dbt build (models + data tests)").set_defaults(fn=cmd_transform)
    t = sub.add_parser("triage", help="AI triage memos (blocked unless dbt tests passed)")
    t.add_argument("--vendor"); t.add_argument("--alias"); t.set_defaults(fn=cmd_triage)
    r = sub.add_parser("review", help="record a human decision")
    r.add_argument("vendor"); r.add_argument("decision", choices=["PURSUE", "PARK", "REJECT", "ESCALATE"])
    r.add_argument("--reviewer", required=True); r.add_argument("--note", default=""); r.set_defaults(fn=cmd_review)
    e = sub.add_parser("eval", help="run golden-set evals; non-zero exit on failure")
    e.add_argument("--alias", default="triage-primary"); e.add_argument("--baseline"); e.set_defaults(fn=cmd_eval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed evals")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check", help="approval, pricing and deprecation check")
    mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report", help="token and $ by month and model").set_defaults(fn=cmd_cost_report)
    sub.add_parser("all", help="data -> ingest -> transform -> triage").set_defaults(fn=cmd_all)
    sub.add_parser("ui", help="Streamlit app: input -> run -> output").set_defaults(fn=cmd_ui)
    args = p.parse_args(argv)
    try:
        args.fn(args, Settings.load())
    except DataQualityGateError as e:
        sys.exit(f"Blocked (DATA-02): {e}")


if __name__ == "__main__":
    main()
