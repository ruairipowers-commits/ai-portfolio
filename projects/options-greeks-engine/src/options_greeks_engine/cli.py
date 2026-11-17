"""Command-line entry point: `options-greeks-engine <command>` or `python -m options_greeks_engine <command>`."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from . import _optlib as O, evals, telemetry
from .llm import Registry
from .schemas import parse_json_schema
from .store import ROOT, Settings, connect, rows, workspace
from .workflow import decide, process, prompt, report


def cmd_data(args, s):
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_sample_data
    generate_sample_data.main(workspace() / "data")


def show(tk) -> None:
    print(f"ticket {tk.ticket_id} [{tk.account}] → {tk.status}")
    if tk.parse and tk.parse.status == "CLARIFY":
        print("  clarification:", tk.parse.clarification)
    for l in (tk.parse.legs if tk.parse else []):
        print(f"  {l.side:4s} {l.quantity:5d} {l.option_type:4s} {l.strike:g} {l.expiry}")
    for e in tk.validation_errors:
        print("  invalid:", e)
    if tk.risk:
        sm = tk.risk["summary"]
        print("  " + ", ".join(f"{k}={sm[k]}" for k in ["net_premium_usd", "price_per_structure", "position_delta_shares",
                                                       "position_vega_usd", "max_loss_usd", "max_profit_usd"]))
        print("  cross-check:", tk.cross_check)
        for c in tk.checks:
            print(f"  {'PASS' if c['passed'] else 'FAIL'} {c['check']:18s} {c['value']} (limit {c['limit']})")
    for w in tk.warnings:
        print("  warning:", w)
    for b in tk.blockers:
        print("  blocked:", b)
    if tk.explanation:
        print("  explanation:", tk.explanation.summary)


def cmd_request(args, s):
    try:
        tk = process(s, args.text, args.account, args.alias)
    except telemetry.WorkflowDisabled as e:
        sys.exit(str(e))
    show(tk)


def cmd_all(args, s):
    cmd_data(args, s)
    reqs = yaml.safe_load((workspace() / "data" / "requests.yaml").read_text())["requests"]
    counts: dict[str, int] = {}
    for r in reqs[:7]:
        tk = process(s, r["request"], r["account"])
        counts[tk.status] = counts.get(tk.status, 0) + 1
        show(tk)
    print("summary:", json.dumps(counts))


def cmd_decide(args, s):
    ok, msg = decide(s, args.ticket, args.decision, args.approver, args.reason)
    print(msg)
    sys.exit(0 if ok else 1)


def cmd_eval(args, s):
    rep = evals.run_eval(s, args.alias)
    print(json.dumps(rep["metrics"], indent=2))
    for c in rep["cases"]:
        print(f"  {c['id']} {'PASS' if c['passed'] else 'FAIL'} {c['status']:16s} {c['problems']}")
    ok = rep["passed"]
    if args.baseline:
        base_name = Registry(ROOT / "config" / "models.yaml").resolve(args.baseline).name
        base = evals.latest_report(base_name) or evals.run_eval(s, args.baseline)
        reg = evals.compare(rep, base)
        if reg:
            print("REGRESSION vs baseline:", *reg, sep="\n  ")
            ok = False
    telemetry.emit("eval", status="ok" if ok else "failed", flags=[] if ok else ["eval_failed"],
                   run_id=rep["run_id"], cost_usd=rep["metrics"]["total_cost_usd"], detail={"metrics": rep["metrics"]})
    telemetry.flush()
    print("EVAL GATE:", "PASS" if ok else f"FAIL {rep['failures']}")
    sys.exit(0 if ok else 1)


def cmd_price(args, s):
    g = O.bs(args.spot, args.strike, args.days / 365, args.rate, args.div, args.vol, args.type == "call")
    lr = O.binomial(args.spot, args.strike, args.days / 365, args.rate, args.div, args.vol, 801, args.type == "call", args.american, "lr")
    mc = O.mc(args.spot, args.strike, args.days / 365, args.rate, args.div, args.vol, args.type == "call", "european", 400_000, 1, True, True)
    print(json.dumps({"bsm": g, "lr_tree_801": lr["price"], "mc_400k": mc["price"], "mc_ci95": mc["ci95"]}, indent=2))


def cmd_promote(args, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    rep = evals.latest_report(args.model)
    _, _, current = prompt(s, "parse_prompt", parse_json_schema())
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="options-greeks-engine", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="write the sample requests").set_defaults(fn=cmd_data)
    r = sub.add_parser("request", help="turn one free-text request into a ticket")
    r.add_argument("text"); r.add_argument("--account", default="DR-02"); r.add_argument("--alias"); r.set_defaults(fn=cmd_request)
    d = sub.add_parser("decide", help="a named approver signs or rejects a ticket")
    d.add_argument("ticket"); d.add_argument("decision", choices=["APPROVE", "REJECT"])
    d.add_argument("--approver", required=True); d.add_argument("--reason", default=""); d.set_defaults(fn=cmd_decide)
    pc = sub.add_parser("price", help="price one option three ways")
    pc.add_argument("--spot", type=float, default=100); pc.add_argument("--strike", type=float, default=100)
    pc.add_argument("--days", type=float, default=365); pc.add_argument("--vol", type=float, default=0.2)
    pc.add_argument("--rate", type=float, default=0.045); pc.add_argument("--div", type=float, default=0.01)
    pc.add_argument("--type", choices=["call", "put"], default="call"); pc.add_argument("--american", action="store_true")
    pc.set_defaults(fn=cmd_price)
    e = sub.add_parser("eval", help="golden-set evals; non-zero exit on failure")
    e.add_argument("--alias", default="parse-primary"); e.add_argument("--baseline"); e.set_defaults(fn=cmd_eval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed evals")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check", help="approval, pricing and deprecation check")
    mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report", help="tokens and $ by month and model").set_defaults(fn=cmd_cost_report)
    sub.add_parser("all", help="sample requests → tickets").set_defaults(fn=cmd_all)
    sub.add_parser("ui", help="Streamlit app: input → run → output, plus the pricing lab").set_defaults(fn=cmd_ui)
    args = p.parse_args(argv)
    args.fn(args, Settings.load())


if __name__ == "__main__":
    main()
