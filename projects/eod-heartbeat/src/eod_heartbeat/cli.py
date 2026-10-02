"""eodhb — EOD heartbeat command line. Runs offline: embedded Postgres + mock models by default."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from . import evals, kb, telemetry
from .explain import prompt, record_feedback, run_eod, send_pending
from .llm import Registry
from .loader import business_dates, generate, load
from .retention import apply_retention
from .store import ROOT, Settings, connect
from .transform import run_dbt


def reset_all(s: Settings, actor: str = "cli") -> dict:
    """Fresh synthetic feeds + knowledge base copy, loaded and indexed; audit history cleared."""
    generate(s)
    kb.reset_kb(s)
    counts = load(s)
    with connect(s) as con:
        for t in ("audit.runs", "audit.explanations", "audit.alerts", "audit.feedback"):
            con.execute(f"truncate {t}")
        con.commit()
    stats = kb.index(s, full=True, actor=actor)
    return {"loaded": counts, "kb": stats}


def cmd_data(a, s):
    print(generate(s))
    kb.reset_kb(s)


def cmd_load(a, s):
    print(json.dumps(load(s), indent=2))


def cmd_dbt(a, s):
    r = run_dbt(s, f"{a.date} {a.as_of}")
    print(r["summary"] or r["log"][-2000:])
    sys.exit(0 if r["ok"] else 1)


def cmd_kb_index(a, s):
    print(json.dumps(kb.index(s, full=a.full), indent=2))


def cmd_check(a, s):
    r = run_eod(s, a.date, a.as_of, actor=a.actor, trigger="cli", alias=a.alias, reload=not a.no_reload)
    sm = r["summary"]
    print(f"{a.date} as of {a.as_of}: {sm['breaks']} break(s), {sm['critical']} critical · NAV {sm['nav_signoff']} · "
          f"dbt {r['dbt']['summary'] or 'FAILED'} · ${r['cost_usd']:.5f} · {r['seconds']}s")
    for b in r["breaks"]:
        e = r["explanations"].get(b["break_id"], {})
        print(f"\n[{b['severity'].upper()}] {b['break_type']} · {b['entity']}: {b['detail']}")
        if e:
            print(f"  {e['status']}: {e['likely_cause']}\n  next: {e['next_step']}\n"
                  f"  cites: {', '.join(e['runbook_refs'] + e['incident_refs'])}  flags: {e['flags']}")


def cmd_backfill(a, s):
    """Run the check for every business date (what the DAG does over a week)."""
    load(s)
    for d in business_dates(s):
        r = run_eod(s, d, a.as_of, actor=a.actor, trigger="cli", reload=False)
        print(f"{d}: {r['summary']}")


def cmd_feedback(a, s):
    record_feedback(s, a.explanation_id, a.rating, a.actor, a.note)
    print("recorded")


def cmd_send_alerts(a, s):
    print(f"sent {send_pending(s)} alert(s)")


def cmd_eval(a, s):
    rep = evals.run_eval(s, a.alias)
    print(json.dumps(rep["metrics"], indent=2))
    for c in rep["cases"]:
        if not (c["detected"] and c["runbook_ok"] and c["human_ok"]):
            print(f"  FAIL {c['date']} {c['type']} {c['entity']}: {c}")
    ok = rep["passed"]
    if a.baseline:
        base_name = Registry(ROOT / "config" / "models.yaml").resolve(a.baseline).name
        base = evals.latest_report(base_name) or evals.run_eval(s, a.baseline)
        regress = evals.compare(rep, base)
        if regress:
            print("REGRESSION vs baseline:", *regress, sep="\n  ")
            ok = False
    print("EVAL GATE:", "PASS" if ok else f"FAIL {rep['failures']}")
    sys.exit(0 if ok else 1)


def cmd_promote(a, s):
    rep = evals.latest_report(a.model)
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {a.model}: no passing eval on record (MODEL-02).")
    if rep["prompt_sha"] != prompt(s)[1]:
        sys.exit("Refusing to promote: prompt changed since the last eval. Re-run eval.")
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
        print(f"{alias:18s} -> {name:20s} {m.provider}:{m.model_id} {'OK' if not issues else '; '.join(issues)}")
        rc |= bool(issues)
    sys.exit(rc)


def cmd_cost_report(a, s):
    with connect(s) as con:
        rows = con.execute("""select to_char(ts, 'YYYY-MM') as mth, coalesce(nullif(model_name, ''), '(none)') as model,
                                     case when run_id like 'eval-%%' then 'eval' else 'prod' end as kind, count(*) as n,
                                     sum(input_tokens) as tin, sum(output_tokens) as tout, round(sum(cost_usd), 5) as usd
                              from audit.explanations group by 1, 2, 3 order by 1, 2, 3""").fetchall()
    limit = s["cost"]["monthly_alert_usd"]
    totals: dict[str, float] = {}
    print(f"{'month':8s} {'model':20s} {'kind':5s} {'explained':>9s} {'in_tok':>8s} {'out_tok':>8s} {'usd':>9s}")
    for r in rows:
        totals[r["mth"]] = totals.get(r["mth"], 0) + float(r["usd"])
        print(f"{r['mth']:8s} {r['model']:20s} {r['kind']:5s} {r['n']:9d} {r['tin']:8d} {r['tout']:8d} {float(r['usd']):9.5f}")
    for mo, usd in totals.items():
        print(f"{mo} total ${usd:.4f} vs alert ${limit:.2f}" + ("  <-- OVER ALERT (COST-04)" if usd > limit else ""))


def cmd_retention(a, s):
    print(json.dumps(apply_retention(s, a.days, a.apply), indent=2))


def cmd_ui(a, s):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], cwd=ROOT)


def cmd_all(a, s):
    print(json.dumps(reset_all(s)["kb"], indent=2))
    a.date, a.no_reload = s["default_business_date"], True
    cmd_check(a, s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="eodhb", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s0 = Settings.load()
    dflt = s0["default_business_date"]

    def add(name, fn, help_):
        x = sub.add_parser(name, help=help_)
        x.set_defaults(fn=fn)
        return x

    add("data", cmd_data, "regenerate synthetic feeds and reset the knowledge-base working copy")
    add("load", cmd_load, "land feeds into Postgres raw.*")
    x = add("dbt", cmd_dbt, "dbt build (models + tests) for an as-of time")
    x.add_argument("--date", default=dflt); x.add_argument("--as-of", default="21:00")
    x = add("kb-index", cmd_kb_index, "index runbooks + incidents into pgvector (incremental)")
    x.add_argument("--full", action="store_true")
    for name in ("check", "all"):
        x = add(name, cmd_check if name == "check" else cmd_all,
                "load → dbt → breaks → explain → alert for one date" if name == "check" else "reset everything, then check the default date")
        x.add_argument("--date", default=dflt); x.add_argument("--as-of", default="21:00")
        x.add_argument("--alias"); x.add_argument("--actor", default="cli")
        x.add_argument("--no-reload", action="store_true")
    x = add("backfill", cmd_backfill, "run the check for every business date")
    x.add_argument("--as-of", default="21:00"); x.add_argument("--actor", default="cli")
    x = add("feedback", cmd_feedback, "on-call rating of an explanation")
    x.add_argument("explanation_id"); x.add_argument("rating", choices=["useful", "wrong"])
    x.add_argument("--actor", required=True); x.add_argument("--note", default="")
    add("send-alerts", cmd_send_alerts, "send outbox alerts (Slack, only if configured)")
    x = add("eval", cmd_eval, "golden-set eval gate; non-zero exit on failure")
    x.add_argument("--alias", default="explain-primary"); x.add_argument("--baseline")
    x = add("promote", cmd_promote, "point an alias at a model that passed evals")
    x.add_argument("alias"); x.add_argument("model")
    x = add("models-check", cmd_models_check, "approval, pricing and deprecation check")
    x.add_argument("--today")
    add("cost-report", cmd_cost_report, "tokens and $ by month, model, prod vs eval")
    x = add("retention", cmd_retention, "archive + delete audit rows past retention (dry run unless --apply)")
    x.add_argument("--days", type=int); x.add_argument("--apply", action="store_true")
    add("ui", cmd_ui, "Streamlit app")
    a = p.parse_args(argv)
    telemetry.register(ROOT)
    try:
        a.fn(a, s0)
    except telemetry.WorkflowDisabled as e:
        sys.exit(f"Blocked: {e}")


if __name__ == "__main__":
    main()
