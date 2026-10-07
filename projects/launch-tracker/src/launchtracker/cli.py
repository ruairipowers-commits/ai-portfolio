"""`launches` — the command line. Every step the app runs is also a command here."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta

from . import analytics, db, evals, reference, summaries, telemetry
from .config import ROOT, Settings, utcnow
from .llm import Registry


def _con(s: Settings):
    return db.connect(s)


def cmd_data(a, s):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")], check=True)


def cmd_build(a, s):
    from .refresh import refresh_once
    print(json.dumps(refresh_once(s, live=None), default=str))


def cmd_fetch(a, s):
    """Live data: Launch Library 2 (within the hourly budget), GCAT and SATCAT (at most daily)."""
    os.environ["LAUNCHES_MODE"] = "live"
    from .refresh import refresh_once
    print(json.dumps(refresh_once(Settings.load(), live=True), default=str))


def cmd_refresh_loop(a, s):
    from .refresh import loop
    os.environ["LAUNCHES_MODE"] = "live"
    loop(Settings.load())


def cmd_all(a, s):
    """Offline end to end: sample → load → headline → three summaries → digest → what changed."""
    from .refresh import refresh_once
    stats = refresh_once(s)
    con = _con(s)
    print(f"loaded: {stats['launches']} launches ({stats['ll2_records']} with detail), {stats['satcat']} catalogued "
          f"objects, {stats['discrepancies']} source disagreement(s)")
    print("headline:", json.dumps(analytics.headline(con, s)))
    for u in analytics.upcoming(con, s)[:3]:
        r = summaries.mission(con, s, u["launch_id"], actor="cli")
        print(f"- [{r.source}{', flags: ' + ','.join(r.flags) if r.flags else ''}] {r.text}")
    for r in (summaries.digest(con, s, actor="cli"), summaries.what_changed(con, s, actor="cli")):
        print(f"{r.purpose}: [{r.source}] {r.text}")
    print("delays:", json.dumps(analytics.delay_stats(con), default=str))


def cmd_summarise(a, s):
    con = _con(s)
    r = summaries.mission(con, s, a.launch_id, alias=a.alias, actor="cli")
    print(json.dumps({"text": r.text, "source": r.source, "flags": r.flags, "problems": r.problems,
                      "citations": r.citations, "cost_usd": r.cost_usd}, indent=2))


def cmd_digest(a, s):
    con = _con(s)
    r = summaries.digest(con, s, date.fromisoformat(a.week) if a.week else None, actor="cli")
    print(f"[{r.source}] {r.text}")


def cmd_changes(a, s):
    print(summaries.what_changed(_con(s), s, actor="cli").text)


def cmd_eval(a, s):
    con = _con(s)
    rep = evals.run_eval(con, s, a.alias)
    print(json.dumps({"passed": rep["passed"], "failures": rep["failures"], "metrics": rep["metrics"],
                      "model": rep["model"]}, indent=2))
    if a.baseline:
        base = evals.latest(Registry(ROOT / "config" / "models.yaml").name_of(a.baseline))
        reg = evals.compare(rep, base) if base else ["no baseline report: run eval on the baseline first"]
        print("regressions:", reg or "none")
        if reg:
            sys.exit(1)
    if not rep["passed"]:
        sys.exit(1)


def cmd_promote(a, s):
    """MODEL-02: point an alias at a model only if its latest eval passed."""
    reg = Registry(ROOT / "config" / "models.yaml")
    rep = evals.latest(a.model)
    if not rep or not rep["passed"]:
        sys.exit(f"refused: no passing eval for {a.model}; run `launches eval --alias <alias pointing at it>` first")
    reg.set_alias(a.alias, a.model)
    print(f"{a.alias} → {a.model}")


def cmd_review(a, s):
    con = _con(s)
    reference.review(con, a.entry_id, a.decision, a.reviewer, a.note or "")
    telemetry.record("review", actor=a.reviewer, items=1, detail={"decision": a.decision})
    print(f"{a.entry_id}: {a.decision} by {a.reviewer}")


def cmd_cost_report(a, s):
    con = _con(s)
    rows = db.rows(con, """select strftime(call_ts, '%Y-%m') as month, purpose, coalesce(model_name, '-') as model,
                           count(*) as calls, sum(input_tokens) as tokens_in, sum(output_tokens) as tokens_out,
                           round(sum(cost_usd), 6) as usd from audit.ai_calls group by 1, 2, 3 order by 1, 2""")
    for r in rows:
        print(r)
    month = db.scalar(con, "select coalesce(sum(cost_usd), 0) from audit.ai_calls where call_ts > ?",
                      [utcnow() - timedelta(days=30)])
    alert = s["cost"]["monthly_alert_usd"]
    print(f"last 30 days: ${month:.4f} (alert at ${alert:.2f}, reviewer: {s['workflow']['owner']})"
          + ("  ⚠ over threshold" if month > alert else ""))


def cmd_check_models(a, s):
    """MODEL-03: warn about models whose provider deprecation date is near."""
    reg = Registry(ROOT / "config" / "models.yaml")
    days = s["governance"]["deprecation_warning_days"]
    soon = [(n, m.deprecation_date) for n, m in reg.models.items()
            if m.deprecation_date and (m.deprecation_date - date.today()).days <= days]
    print("\n".join(f"⚠ {n} deprecates on {d}" for n, d in soon) or f"no deprecations within {days} days")


def cmd_ui(a, s):
    os.execvp("streamlit", ["streamlit", "run", str(ROOT / "src" / "launchtracker" / "ui.py")])


def cmd_flows(a, s):
    from .flows import serve_all
    serve_all()


def main(argv=None):
    p = argparse.ArgumentParser(prog="launches", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        x = sub.add_parser(name, help=help_)
        x.set_defaults(fn=fn)
        return x

    add("data", cmd_data, "write the offline (fictional) sample")
    add("build", cmd_build, "load the sources into the database (fixture or live, per settings.mode)")
    add("fetch", cmd_fetch, "live data from Launch Library 2, GCAT and SATCAT (needs network)")
    add("refresh-loop", cmd_refresh_loop, "keep refreshing live data (the hosted demo runs this)")
    add("all", cmd_all, "offline end to end")
    x = add("summarise", cmd_summarise, "cited plain-English summary of one launch")
    x.add_argument("launch_id"); x.add_argument("--alias")
    x = add("digest", cmd_digest, "weekly digest"); x.add_argument("--week", help="Monday, YYYY-MM-DD")
    add("changes", cmd_changes, "what changed since the last refresh")
    x = add("eval", cmd_eval, "golden-set eval and gate"); x.add_argument("--alias"); x.add_argument("--baseline")
    x = add("promote", cmd_promote, "point an alias at a model (eval-gated)"); x.add_argument("alias"); x.add_argument("model")
    for name, decision in (("approve", "approved"), ("reject", "rejected")):
        x = add(name, cmd_review, f"{name} a cost or reference entry")
        x.add_argument("entry_id"); x.add_argument("--reviewer", required=True); x.add_argument("--note")
        x.set_defaults(decision=decision)
    add("cost-report", cmd_cost_report, "AI spend by month, purpose and model")
    add("check-models", cmd_check_models, "model deprecation warnings")
    add("ui", cmd_ui, "the Streamlit app")
    add("flows", cmd_flows, "serve the Prefect flows (needs the flows extra)")
    a = p.parse_args(argv)
    telemetry.set_actor(os.getenv("USER", "cli"), "named")
    try:
        a.fn(a, Settings.load())
    except telemetry.WorkflowDisabled as e:
        sys.exit(f"⛔ {e}")
