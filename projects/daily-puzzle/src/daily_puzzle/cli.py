"""Command line. `puzzle --help` lists everything; `puzzle all` is the offline end-to-end demo."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import warnings
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from sqlalchemy import Integer, String, func, select


def _s():
    from .config import Settings
    return Settings.load()


def _eng(s):
    from .store import engine
    return engine(s)


def cmd_serve(a):
    import uvicorn
    os.environ.setdefault("PUZZLE_SCHEDULER", "1")
    uvicorn.run("daily_puzzle.web:app_factory", factory=True, host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", a.port)), proxy_headers=True, forwarded_allow_ips="*")


def cmd_ui(a):
    from .config import PKG
    os.execvp(sys.executable, [sys.executable, "-m", "streamlit", "run", str(PKG / "ui.py"), *a.rest])


def cmd_tick(a):
    from . import cycle
    s = _s()
    at = datetime.fromisoformat(a.at).astimezone(timezone.utc) if a.at else None
    with _eng(s).begin() as c:
        for x in cycle.tick(c, s, at):
            print(json.dumps(x, default=str))


def cmd_reserve(a):
    from . import generate
    s = _s()
    with _eng(s).begin() as c:
        print(f"added {len(generate.build_reserve(c, s, a.per_track))} reserve puzzle(s)")


def cmd_generate(a):
    """Generate and verify one day's puzzle now (normally the scheduler does this)."""
    from . import generate
    s = _s()
    day = date.fromisoformat(a.day) if a.day else date.today()
    with _eng(s).begin() as c:
        res = generate.daily(c, s, day, scenario=a.scenario, kind=a.kind, every_round=a.every_round)
    print(json.dumps({k: v for k, v in res.items() if k not in ("report",)}, indent=2, default=str))


def cmd_simulate(a):
    from . import game, simulate
    s = _s()
    start = date.fromisoformat(a.start) if a.start else date.today() - timedelta(days=a.days)
    with _eng(s).begin() as c:
        log = simulate.week(c, s, start, a.days, a.players, a.seed)
        for x in log:
            if x["job"] in ("generate", "players", "reveal"):
                print(x)
        print("\nLeaderboard (top 10)")
        for r in game.leaderboard(c, s)[:10]:
            print(f"{r['rank']:>3} {r['handle']:20s} accepted {r['accepted']:>2} attempted {r['attempted']:>2} "
                  f"solved {r['solved']:>2} score {r['score']:>4}")


def cmd_pack(a):
    from . import generate, packs
    s = _s()
    tracks = a.tracks.split(",") if a.tracks and a.tracks != "random" else "random"
    with _eng(s).begin() as c:
        out = generate.pack(c, s, a.count, tracks, a.difficulty, a.seed)
        q, ans = packs.write(c, s, out["pack_id"], Path(a.out) if a.out else None)
    print(f"pack {out['pack_id']} (seed {out['seed']}): {len(out['puzzle_ids'])} puzzles, cost ${out['cost_usd']:.4f}")
    for d in out["dropped"]:
        print(f"  dropped a {d['track']}/{d['kind']} puzzle that couldn't be verified: {'; '.join(d['reasons'])}")
    print(f"questions:  {q}\nanswer key: {ans}")


def cmd_review(a):
    from . import generate
    s = _s()
    with _eng(s).begin() as c:
        generate.review(c, a.puzzle_id, a.reviewer, a.decision, a.note or "")
    print(f"#{a.puzzle_id}: {a.decision} by {a.reviewer}")


def cmd_eval(a):
    from . import evals
    rep = evals.run(role=a.role, alias=a.alias)
    for k, v in rep["metrics"].items():
        mark = "" if k not in rep["checks"] else ("✓" if rep["checks"][k] else "✗")
        print(f"  {mark:2s}{k:24s} {v if not isinstance(v, float) else round(v, 4)}")
    for c in rep["cases"]:
        if not c["ok"]:
            print(f"  ✗ {c['id']}: expected {c['expected']}, got {c['got']} {c.get('reasons', '')}")
    print(f"eval {'PASSED' if rep['passed'] else 'FAILED'} — generator {rep['generator_model']}, solver {rep['solver_model']}, "
          f"{rep['seconds']}s")
    sys.exit(0 if rep["passed"] else 1)


def cmd_promote(a):
    from . import evals, llm
    s = _s()
    role = "solver" if a.alias == s["llm"]["solver_alias"] else "generator"
    if not evals.last_passing(a.model, role):
        sys.exit(f"refusing: no passing eval for {a.model} as {role} on the current prompts "
                 f"(run: puzzle eval --role {role} --alias <alias pointing at {a.model}>)")
    llm.Registry(s.models_path).set_alias(a.alias, a.model)
    print(f"{a.alias} → {a.model}")


def cmd_models_check(a):
    from . import generate, llm
    s = _s()
    reg = llm.Registry(s.models_path)
    warn_days = s["governance"]["deprecation_warning_days"]
    bad = 0
    for alias, name in reg.aliases.items():
        m = reg.models[name]
        msg = "ok"
        if m.deprecation_date:
            left = (m.deprecation_date - date.today()).days
            if left <= warn_days:
                msg, bad = f"DEPRECATES in {left} days ({m.deprecation_date}) — see the migration runbook", bad + 1
        print(f"  {alias:18s} → {name:16s} {m.provider:9s} {msg}")
    for w in generate.model_warnings(s):
        print("  ⚠", w)
    sys.exit(1 if bad else 0)


def cmd_cost_report(a):
    from .store import ai_calls
    s = _s()
    with _eng(s).connect() as c:
        rows = c.execute(select(func.substr(func.cast(ai_calls.c.at, String), 1, 7).label("month"),
                                ai_calls.c.purpose, ai_calls.c.role, ai_calls.c.model, func.count().label("calls"),
                                func.sum(ai_calls.c.input_tokens), func.sum(ai_calls.c.output_tokens),
                                func.sum(ai_calls.c.cost_usd)).group_by("month", ai_calls.c.purpose, ai_calls.c.role,
                                                                        ai_calls.c.model)).all()
    total: dict[str, float] = {}
    print(f"{'month':8s} {'purpose':8s} {'role':10s} {'model':16s} {'calls':>6s} {'tokens in':>10s} {'out':>8s} {'USD':>9s}")
    for r in rows:
        print(f"{r[0]:8s} {r[1]:8s} {r[2]:10s} {r[3]:16s} {r[4]:>6d} {r[5] or 0:>10d} {r[6] or 0:>8d} {r[7] or 0:>9.4f}")
        if r[1] != "eval":
            total[r[0]] = total.get(r[0], 0) + (r[7] or 0)
    for m, v in total.items():
        flag = "  ⚠ over the monthly alert threshold" if v > s["cost"]["monthly_alert_usd"] else ""
        print(f"{m}: ${v:.4f} (alert at ${s['cost']['monthly_alert_usd']:.2f}){flag}")


def cmd_config_check(a):
    from .config import validate_puzzles
    p = validate_puzzles(_s().puzzles)
    print("\n".join(f"✗ {x}" for x in p) or "config/puzzles.yaml OK")
    sys.exit(1 if p else 0)


def cmd_stats(a):
    from .store import acceptances, puzzles as P
    s = _s()
    with _eng(s).connect() as c:
        rows = c.execute(select(P.c.track, P.c.difficulty, func.count(acceptances.c.player_id),
                                func.sum(func.cast(acceptances.c.solved_at.isnot(None), Integer)))
                         .select_from(P.join(acceptances, acceptances.c.puzzle_id == P.c.id))
                         .group_by(P.c.track, P.c.difficulty)).all()
    target = s.puzzles["difficulty"]["target_solve_rate"]
    for t, d, n, solved in rows:
        print(f"{t:8s} {d:6s} accepted {n:>4d}  solve rate {(solved or 0) / max(1, n):.0%}  (target {target[d]:.0%})")


def cmd_retention(a):
    from .store import ai_calls, attempts, jobs, outbox, sandbox_runs
    s = _s()
    cut = datetime.now(timezone.utc) - timedelta(days=s["privacy"]["retention_days"])
    with _eng(s).begin() as c:
        n = sum(c.execute(t.delete().where(col < cut)).rowcount for t, col in
                ((attempts, attempts.c.at), (ai_calls, ai_calls.c.at), (sandbox_runs, sandbox_runs.c.at),
                 (outbox, outbox.c.at), (jobs, jobs.c.at)))
    print(f"deleted {n} row(s) older than {s['privacy']['retention_days']} days")


def cmd_eval_candidates(a):
    """HITL-03: turn operator decisions on escalated drafts into candidate golden cases to review and paste."""
    import yaml
    from .store import fetch_all, puzzles as P, reviews
    s = _s()
    with _eng(s).connect() as c:
        rows = fetch_all(c, select(reviews.c.puzzle_id, reviews.c.decision, reviews.c.note, P.c.kind, P.c.track)
                         .select_from(reviews.join(P, P.c.id == reviews.c.puzzle_id)))
    out = [{"id": f"r{r['puzzle_id']}", "kind": r["kind"], "puzzle_id": r["puzzle_id"],
            "expected": "PUBLISH" if r["decision"] == "approve" else "REJECT", "why": r["note"] or ""} for r in rows]
    print(yaml.safe_dump(out, sort_keys=False) if out else "no reviewed escalations yet")


def cmd_reset(a):
    from .config import data_dir
    from .store import reset_engines
    reset_engines()
    for d in ("warehouse", "output"):
        shutil.rmtree(data_dir() / d, ignore_errors=True)
    print("demo data reset (warehouse/ and output/ removed)")


def cmd_all(a):
    """Offline end-to-end: fresh data, reserve, a simulated week, a pack with both PDFs, then the eval gate."""
    os.environ.setdefault("PUZZLE_ALL", "1")
    cmd_reset(a)
    s = _s()
    cmd_reserve(argparse.Namespace(per_track=2))
    cmd_simulate(argparse.Namespace(start="2026-10-05", days=7, players=25, seed=7))
    cmd_pack(argparse.Namespace(count=5, tracks="random", difficulty="mixed", seed=2026, out=None))
    cmd_eval(argparse.Namespace(role="solver", alias=None))


def main(argv=None):
    warnings.filterwarnings("ignore", message=".* not set: using the development default")
    p = argparse.ArgumentParser(prog="puzzle", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("serve", help="player site + scheduler (http://localhost:8800)"); x.add_argument("--port", default=8800); x.set_defaults(f=cmd_serve)
    x = sub.add_parser("ui", help="operator app (Streamlit)"); x.add_argument("rest", nargs="*"); x.set_defaults(f=cmd_ui)
    x = sub.add_parser("tick", help="run the scheduler once"); x.add_argument("--at", help="ISO time (simulate a clock)"); x.set_defaults(f=cmd_tick)
    x = sub.add_parser("reserve", help="top up pre-verified reserve puzzles"); x.add_argument("--per-track", type=int, default=3); x.set_defaults(f=cmd_reserve)
    x = sub.add_parser("generate", help="generate + verify a day's puzzle now"); x.add_argument("--day"); x.add_argument("--scenario")
    x.add_argument("--kind"); x.add_argument("--every-round", action="store_true"); x.set_defaults(f=cmd_generate)
    x = sub.add_parser("simulate", help="simulated players over N days"); x.add_argument("--start"); x.add_argument("--days", type=int, default=7)
    x.add_argument("--players", type=int, default=25); x.add_argument("--seed", type=int, default=7); x.set_defaults(f=cmd_simulate)
    x = sub.add_parser("pack", help="one-off puzzle pack → questions PDF + answer-key PDF")
    x.add_argument("--count", type=int, default=5); x.add_argument("--tracks", default="random", help="comma list, e.g. logic,ai_ml")
    x.add_argument("--difficulty", default="mixed"); x.add_argument("--seed", type=int); x.add_argument("--out"); x.set_defaults(f=cmd_pack)
    x = sub.add_parser("review", help="approve/reject an escalated draft (HITL-02)"); x.add_argument("puzzle_id", type=int)
    x.add_argument("decision", choices=["approve", "reject"]); x.add_argument("--reviewer", required=True); x.add_argument("--note"); x.set_defaults(f=cmd_review)
    x = sub.add_parser("eval", help="eval gate"); x.add_argument("--role", choices=["solver", "generator"], default="solver")
    x.add_argument("--alias"); x.set_defaults(f=cmd_eval)
    x = sub.add_parser("promote", help="point an alias at a model (needs a passing eval)"); x.add_argument("alias"); x.add_argument("model"); x.set_defaults(f=cmd_promote)
    sub.add_parser("models-check", help="deprecations + generator/solver independence").set_defaults(f=cmd_models_check)
    sub.add_parser("cost-report", help="tokens and $ by month, purpose, role, model").set_defaults(f=cmd_cost_report)
    sub.add_parser("config-check", help="validate config/puzzles.yaml").set_defaults(f=cmd_config_check)
    sub.add_parser("stats", help="solve rate by track and difficulty vs target").set_defaults(f=cmd_stats)
    sub.add_parser("retention", help="delete rows older than privacy.retention_days").set_defaults(f=cmd_retention)
    sub.add_parser("eval-candidates", help="operator decisions → candidate golden cases").set_defaults(f=cmd_eval_candidates)
    sub.add_parser("reset", help="delete local demo data").set_defaults(f=cmd_reset)
    sub.add_parser("all", help="offline end-to-end demo").set_defaults(f=cmd_all)
    a = p.parse_args(argv)
    a.f(a)
    from . import telemetry
    telemetry.flush()


if __name__ == "__main__":
    main()
