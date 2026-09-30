"""CLI: `tradeops <command>` (or `python -m tradeops`)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import date, timedelta

from . import db, evals
from .llm import BudgetExceeded, Registry, RegistryError
from .runner import ROOT, db_url, decide, investigate, load_settings


def _con():
    s = load_settings()
    con = db.connect(db_url(s))
    db.ensure_audit(con, ROOT)
    return s, con


def cmd_data(a):
    from .data import generate

    s = load_settings()
    print(generate(db_url(s), ROOT))
    for f in (ROOT / s["checkpoint_db"], ROOT / (s["checkpoint_db"] + "-wal"), ROOT / (s["checkpoint_db"] + "-shm")):
        f.unlink(missing_ok=True)


def cmd_build_server(a):
    srv = ROOT / "mcp-server"
    subprocess.run(["npm", "ci" if (srv / "package-lock.json").exists() else "install", "--no-audit", "--no-fund"],
                   cwd=srv, check=True)
    subprocess.run(["npm", "run", "build"], cwd=srv, check=True)


def _need_server():
    if not (ROOT / "mcp-server" / "dist" / "index.js").exists():
        sys.exit("MCP server not built: run `tradeops build-server` (needs Node 22.13+).")


def cmd_investigate(a):
    _need_server()
    try:
        res = asyncio.run(investigate([a.exception] if a.exception else None, a.alias))
    except (BudgetExceeded, RegistryError) as e:
        sys.exit(f"Stopped: {e}")
    counts: dict[str, int] = {}
    for r in res:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        why = "; ".join(r["reasons"])
        print(f"{r['exception_id']}  {r['status']:17s} {str(r['category']):20s} {str(r['fix_type']):26s} "
              f"tools={r['tool_calls']} ${r['cost_usd']:.4f}  {why}")
    print(f"{len(res)} investigated: {counts}  spend ${sum(r['cost_usd'] for r in res):.4f}")


def cmd_queue(a):
    s, con = _con()
    rows = con.query("""select exception_id, status, category, fix_type, tool_calls, round(cost_usd, 4) as cost
                        from agent_runs where run_id not like 'eval-%' and status in ('awaiting_approval','escalated')
                        order by status, exception_id""")
    for r in rows:
        print(f"{r['exception_id']}  {r['status']:17s} {r['category']:20s} {r['fix_type']:26s} tools={r['tool_calls']} ${r['cost']}")
    print(f"{len(rows)} item(s)")


def cmd_show(a):
    s, con = _con()
    r = con.one("select * from agent_runs where exception_id = ? and run_id not like 'eval-%' order by started_at desc", (a.exception,))
    if not r:
        sys.exit("not investigated yet")
    p, f = json.loads(r["proposal_json"]), json.loads(r["policy_flags"])
    print(f"{a.exception}: {r['status']}  (model {r['model_name']}, {r['tool_calls']} tool calls, ${r['cost_usd']:.4f})")
    for k in ("category", "fix_type", "root_cause", "fix_details", "confidence"):
        print(f"  {k:12s} {p[k]}")
    print("  evidence:", *[f"{e['tool']}.{e['field']} = {e['value']}" for e in p["evidence"]], sep="\n    ")
    if p.get("email_draft"):
        e = p["email_draft"]
        print(f"  email to {e['recipient']}: {e['subject']}\n    {e['body']}")
    if f["reasons"]:
        print("  escalation reasons:", *f["reasons"], sep="\n    ")


def _decide(a, decision):
    _need_server()
    edits = {}
    if getattr(a, "fix_details", None):
        edits["fix_details"] = a.fix_details
    try:
        print(asyncio.run(decide(a.exception, decision, a.approver, a.note, edits)))
    except LookupError as e:
        sys.exit(str(e))


def cmd_replay(a):
    """OBS-01 / NFR-4: the full trajectory for an exception."""
    s, con = _con()
    r = con.one("select thread_id from agent_runs where exception_id = ? order by started_at desc", (a.exception,))
    if not r:
        sys.exit("no run")
    for st in con.query("select * from agent_steps where thread_id = ? order by step, ts", (r["thread_id"],)):
        extra = st["args_json"] or ""
        print(f"{st['step']:>2} {st['kind']:13s} {st['name'] or '':24s} {extra[:70]:70s} "
              f"{'tok ' + str(st['input_tokens']) + '/' + str(st['output_tokens']) if st['kind'] == 'llm' else ''} {st['flag'] or ''}")
    for ap in con.query("select * from approvals where thread_id = ?", (r["thread_id"],)):
        print(f"   decision      {ap['decision']} by {ap['approver']} ({ap['note']})")


def cmd_eval(a):
    _need_server()
    rep = asyncio.run(evals.run_eval(a.alias))
    print(json.dumps(rep["metrics"], indent=2))
    for c in rep["cases"]:
        if not (c["category_ok"] and c["fix_ok"] and c["status_ok"] and c["trajectory_ok"]):
            print("  MISS", c["exception_id"], "expected", c["expected"], "got", c["got"])
    ok = rep["passed"]
    if a.baseline:
        base_name = Registry(ROOT / "config" / "models.yaml").resolve(a.baseline).name
        base = evals.latest(base_name) or asyncio.run(evals.run_eval(a.baseline))
        reg = evals.compare(rep, base)
        if reg:
            print("REGRESSION vs baseline:", *reg, sep="\n  ")
            ok = False
    print("EVAL GATE:", "PASS" if ok else f"FAIL {rep['failures']}")
    sys.exit(0 if ok else 1)


def cmd_promote(a):
    s = load_settings()
    rep = evals.latest(a.model)
    sha = __import__("hashlib").sha256((ROOT / s["llm"]["prompt_file"]).read_bytes()).hexdigest()[:16]
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {a.model}: no passing eval on record (MODEL-02).")
    if rep["prompt_sha"] != sha:
        sys.exit("Refusing to promote: prompt changed since the last eval. Re-run eval.")
    Registry(ROOT / "config" / "models.yaml").set_alias(a.alias, a.model)
    print(f"{a.alias} -> {a.model} (eval {rep['run_id']} passed)")


def cmd_models_check(a):
    s = load_settings()
    reg = Registry(ROOT / "config" / "models.yaml")
    today = date.fromisoformat(a.today) if a.today else date.today()
    rc = 0
    for alias, name in reg.aliases.items():
        m = reg.models[name]
        issues = [x for x, bad in [("not approved", not m.approved), ("no pricing", not m.priced()),
                                    (f"deprecates {m.deprecation_date}", bool(m.deprecation_date and m.deprecation_date - today
                                     <= timedelta(days=s["governance"]["deprecation_warning_days"])))] if bad]
        print(f"{alias:24s} -> {name:12s} {m.provider}:{m.model_id} {'; '.join(issues) or 'OK'}")
        rc |= bool(issues)
    sys.exit(rc)


def cmd_cost_report(a):
    s, con = _con()
    rows = con.query("""select substr(cast(started_at as text), 1, 7) as mth, model_name,
                               case when run_id like 'eval-%' then 'eval' else 'prod' end as kind,
                               count(*) as exceptions, sum(tool_calls) as tool_calls, sum(input_tokens) as tin,
                               sum(output_tokens) as tout, round(sum(cost_usd), 4) as usd
                        from agent_runs group by 1, 2, 3 order by 1, 2, 3""")
    print(f"{'month':8s} {'model':12s} {'kind':5s} {'exc':>4s} {'tools':>6s} {'in_tok':>8s} {'out_tok':>7s} {'usd':>8s}")
    tot: dict[str, float] = {}
    for r in rows:
        tot[r["mth"]] = tot.get(r["mth"], 0) + r["usd"]
        print(f"{r['mth']:8s} {r['model_name']:12s} {r['kind']:5s} {r['exceptions']:4d} {r['tool_calls']:6d} "
              f"{r['tin']:8d} {r['tout']:7d} {r['usd']:8.4f}")
    for m, usd in tot.items():
        lim = s["cost"]["monthly_alert_usd"]
        print(f"{m} total ${usd:.4f} vs alert ${lim:.2f}" + ("  <-- OVER ALERT (COST-04)" if usd > lim else ""))


def cmd_ui(a):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "src" / "tradeops" / "ui.py")], cwd=ROOT)


def cmd_all(a):
    cmd_data(a)
    if not (ROOT / "mcp-server" / "dist" / "index.js").exists():
        cmd_build_server(a)
    a.exception, a.alias = None, None
    cmd_investigate(a)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tradeops", description="Trade-ops exception agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="(re)generate synthetic middle-office data").set_defaults(fn=cmd_data)
    sub.add_parser("build-server", help="npm install + build the MCP server").set_defaults(fn=cmd_build_server)
    i = sub.add_parser("investigate", help="run the agent on open exceptions (stops at human approval)")
    i.add_argument("--exception"); i.add_argument("--alias"); i.set_defaults(fn=cmd_investigate)
    sub.add_parser("queue", help="proposals awaiting approval + escalations").set_defaults(fn=cmd_queue)
    sh = sub.add_parser("show", help="show a proposal"); sh.add_argument("exception"); sh.set_defaults(fn=cmd_show)
    ap = sub.add_parser("approve", help="approve (optionally edit) and record via the gated write tool")
    ap.add_argument("exception"); ap.add_argument("--approver", required=True); ap.add_argument("--note", default="")
    ap.add_argument("--fix-details"); ap.set_defaults(fn=lambda a: _decide(a, "approve"))
    rj = sub.add_parser("reject", help="reject a proposal")
    rj.add_argument("exception"); rj.add_argument("--approver", required=True); rj.add_argument("--note", default="")
    rj.set_defaults(fn=lambda a: _decide(a, "reject"))
    rp = sub.add_parser("replay", help="print the agent trajectory"); rp.add_argument("exception"); rp.set_defaults(fn=cmd_replay)
    e = sub.add_parser("eval", help="golden-set eval gate (non-zero exit on failure)")
    e.add_argument("--alias", default="investigator-primary"); e.add_argument("--baseline"); e.set_defaults(fn=cmd_eval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed evals")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check"); mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report").set_defaults(fn=cmd_cost_report)
    sub.add_parser("ui", help="Streamlit approval queue").set_defaults(fn=cmd_ui)
    sub.add_parser("all", help="data -> build server -> investigate all").set_defaults(fn=cmd_all)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
