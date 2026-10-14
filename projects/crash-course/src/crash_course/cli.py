"""Command line. `course --help` lists everything; `course all` is the offline end-to-end run."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def _s():
    from .config import Settings
    return Settings.load()


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------- serving
def cmd_serve(a):
    import uvicorn
    from .web import create_app
    uvicorn.run(create_app(start_worker=not a.no_worker), host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", a.port)), proxy_headers=True, forwarded_allow_ips="*")


def cmd_ui(a):
    from .config import PKG
    os.execvp(sys.executable, [sys.executable, "-m", "streamlit", "run", str(PKG / "ui.py"), *a.rest])


def cmd_worker(a):
    from . import jobs
    s = _s()
    while True:
        for j in jobs.run_pending(s):
            print(f"job {j['id']} {j['kind']} {j['course']}/{j['level']}: {j['status']} {json.dumps(j['detail'])[:200]}")
        if a.once:
            return
        time.sleep(a.every)


# ---------------------------------------------------------------- content
def cmd_sources(a):
    """Refresh sources/tech from the site's tech pages and list levels built from an older copy (DATA-01)."""
    from . import catalog
    from .config import LEVELS, root
    src = Path(a.src) if a.src else root().parents[1] / "site" / "tech"
    if not src.is_dir():
        sys.exit(f"no tech pages at {src} (pass --src)")
    dst = catalog.sources_dir()
    dst.mkdir(parents=True, exist_ok=True)
    changed = []
    for p in sorted(src.glob("*.md")):
        if p.stem == "index":
            continue
        old = (dst / p.name).read_text() if (dst / p.name).exists() else None
        if old != p.read_text():
            shutil.copyfile(p, dst / p.name)
            changed.append(p.stem)
    stale = []
    for slug, c in catalog.bundled().items():
        for lv in LEVELS:
            x = catalog.load_level(slug, lv, include_drafts=True)
            if x and x.source.sha and x.source.sha != c.source_sha:
                stale.append(f"{slug}/{lv}")
    print(f"{len(changed)} source page(s) updated: {', '.join(changed) or '-'}")
    print(f"{len(stale)} level(s) built from an older copy of their page: {', '.join(stale) or '-'}")


def cmd_check(a):
    """Run the content checks on every level file (bundled and drafts)."""
    from . import catalog, checks
    from .config import LEVELS
    s = _s()
    courses = catalog.all_courses()
    bad, n, mins = 0, 0, []
    for slug in sorted(courses):
        if a.course and slug != a.course:
            continue
        for lv_name in LEVELS:
            try:
                lv = catalog.load_level(slug, lv_name, include_drafts=True)
            except Exception as e:  # noqa: BLE001 — a file that doesn't parse is a failure, not a crash
                n += 1
                bad += 1
                print(f"FAIL  {slug}/{lv_name}: doesn't match the schema")
                print(f"        - {str(e).splitlines()[0]}: {' | '.join(str(e).splitlines()[1:3])}")
                continue
            if not lv:
                continue
            n += 1
            rep = checks.check_level(lv, courses[slug], s)
            mins.append(rep.stats["minutes"])
            if rep.ok:
                if a.verbose:
                    print(f"ok    {slug}/{lv_name} v{lv.version} {lv.status}: ~{rep.stats['minutes']} min, "
                          f"{rep.stats['questions']} questions")
            else:
                bad += 1
                print(f"FAIL  {slug}/{lv_name} v{lv.version} {lv.status}")
                for p in rep.problems:
                    print(f"        - {p}")
    if mins:
        print(f"{n - bad} of {n} level(s) pass every check; estimated {min(mins)}–{max(mins)} min")
    else:
        print("no level files found")
    sys.exit(1 if bad else 0)


def cmd_build(a):
    from . import builder
    from .store import connect
    s = _s()
    with connect() as conn:
        lv, rep, err = builder.build(conn, s, a.course, a.level)
    if err:
        sys.exit(f"build failed: {err}")
    print(f"draft {a.course}/{a.level} v{lv.version}: checks {'passed' if rep.ok else 'FAILED'} "
          f"(~{rep.stats['minutes']} min, {rep.stats['questions']} questions)")
    for p in rep.problems:
        print("  -", p)


def cmd_publish(a):
    """Owner: publish (or reject) a draft. `--all` publishes every pending draft that passes its checks, after
    you have reviewed them (each one is re-checked and logged as your approval)."""
    from . import builder, catalog
    from .config import LEVELS
    from .store import connect
    s = _s()
    if a.all:
        if a.reject or a.course:
            sys.exit("--all takes no course and can't reject")
        n, failed = 0, []
        with connect() as conn:
            for slug in sorted(catalog.all_courses(conn)):
                for lv in LEVELS:
                    if a.level and lv != a.level:
                        continue
                    if catalog.has_pending_draft(slug, lv):
                        ok, problems = builder.publish(conn, s, slug, lv, a.reviewer)
                        n += ok
                        if not ok:
                            failed.append(f"{slug}/{lv}: {problems[0]}")
        print(f"published {n} level(s) as {a.reviewer}" + (f"; {len(failed)} not published:" if failed else ""))
        for f in failed:
            print("  -", f)
        sys.exit(1 if failed else 0)
    if not (a.course and a.level):
        sys.exit("give a course and level, or --all")
    with connect() as conn:
        if a.reject:
            ok = builder.reject(conn, s, a.course, a.level, a.reviewer, a.note)
            print("rejected" if ok else "no draft")
            return
        ok, problems = builder.publish(conn, s, a.course, a.level, a.reviewer)
    print("published" if ok else "not published: " + "; ".join(problems))
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- suggestions and approvals
def cmd_suggest(a):
    from . import moderation
    from .store import connect, insert, now, one
    s = _s()
    with connect() as conn:
        u = one(conn, "SELECT id FROM learners WHERE email=?", a.email.lower())
        lid = u["id"] if u else insert(conn, "learners", email=a.email.lower(), name=a.email.split("@")[0],
                                       created_at=now(), last_seen=now())
        row = moderation.suggest(conn, s, lid, a.text)
    _print(moderation.parse(row))


def cmd_queue(a):
    """What's waiting for the owner: suggestions, drafts, revision proposals."""
    from . import catalog, moderation
    from .config import LEVELS
    from .store import connect, rows
    with connect() as conn:
        sugg = [moderation.parse(r) for r in rows(conn, "SELECT * FROM suggestions WHERE status='pending' ORDER BY id")]
        props = rows(conn, "SELECT id, course, level, version, created_at FROM proposals WHERE status='pending'")
        courses = catalog.all_courses(conn)
    drafts = [f"{slug}/{lv}" for slug in courses for lv in LEVELS if catalog.has_pending_draft(slug, lv)]
    print(f"Suggestions waiting: {len(sugg)}")
    for r in sugg:
        x = r["assessment"]
        print(f"  #{r['id']} {r['text']!r} → {x.get('verdict')} {x.get('categories') or ''} {x.get('reasons', [''])[0]}")
    print(f"Drafts waiting to publish: {len(drafts)} {', '.join(drafts)}")
    print(f"Revision proposals: {len(props)}")
    for p in props:
        print(f"  #{p['id']} {p['course']}/{p['level']} v{p['version']}")


def cmd_decide(a):
    from . import moderation
    from .store import connect
    s = _s()
    with connect() as conn:
        row = moderation.decide(conn, s, a.id, "approve" if a.approve else "reject", a.reviewer, title=a.title or "",
                                docs=a.docs or "", notes=a.notes or "")
    print(f"suggestion #{a.id}: {row['status']}" + (f" → course {row['course_slug']}" if row["course_slug"] else ""))


def cmd_revise(a):
    from . import revise
    from .store import connect
    s = _s()
    with connect() as conn:
        if a.decide is not None:
            acc = [int(x) for x in a.accept.split(",") if x.strip()] if a.accept else []
            _print(revise.decide(conn, s, a.decide, acc, a.reviewer))
            return
        pid, why = revise.propose(conn, s, a.course, a.level)
    print(f"proposal #{pid}" if pid else f"no proposal: {why}")


# ---------------------------------------------------------------- models, cost, retention
def cmd_eval(a):
    from . import evals
    s = _s()
    out = evals.run(s, a.alias)
    m, c, t, f = out["moderation"], out["content"], out["tracker"], out["feedback"]
    print(f"moderation  {m['cases']} cases: accuracy {m['accuracy']}, must-reject recall {m['must_reject_recall']}, "
          f"false-reject {m['false_reject_rate']}, duplicates {m['duplicate_accuracy']}")
    for x in m["misses"]:
        print(f"    miss {x['id']}: expected {x['expect']} got {x['got']}"
              + (f" (dup {x['dup_got']} vs {x['dup_expect']})" if x["dup_expect"] else ""))
    print(f"content     {c['levels']} levels, {c['cases']} cases: pass rate {c['pass_rate']}")
    for x in c["failing_levels"][:10]:
        print(f"    FAIL {x['course']}/{x['level']}: {x['problems'][0]}")
    for grp, res in (("tracker", t), ("feedback", f)):
        print(f"{grp:<11} {res['cases']} cases: pass rate {res['pass_rate']}")
        for x in res["results"]:
            print(f"    {'ok  ' if x['ok'] else 'FAIL'} {x['id']}: {x.get('note', '')}")
    print("gate:", "PASSED" if out["passed"] else "FAILED",
          "; ".join(f"{k} {g['value']} {g['op']} {g['threshold']}" for k, g in out["gates"].items() if not g["ok"]))
    from .config import data_dir
    p = data_dir() / "output" / "eval.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out["passed"] else 1)


def cmd_promote(a):
    """MODEL-02: point an alias at a model, only after `course eval --alias <model>` passes."""
    from . import ai, evals
    s = _s()
    if not a.skip_eval:
        out = evals.run(s, a.model) if a.alias == "course-moderator" else evals.run(s)
        if not out["passed"]:
            sys.exit("eval gate failed; not promoted")
    ai.registry().set_alias(a.alias, a.model)
    print(f"{a.alias} → {a.model}")


def cmd_deprecations(a):
    """MODEL-03: models in use with a deprecation date inside the warning window."""
    from datetime import date
    from . import ai
    reg = ai.registry()
    warn = 0
    for alias, name in reg.aliases.items():
        spec = reg.resolve(name)
        if spec.deprecation_date:
            days = (date.fromisoformat(str(spec.deprecation_date)) - date.today()).days
            flag = "WARN" if days <= a.days else "ok"
            warn += flag == "WARN"
            print(f"{flag:5} {alias} → {name}: deprecated in {days} days")
        else:
            print(f"ok    {alias} → {name}: no deprecation date")
    sys.exit(1 if warn else 0)


def cmd_report(a):
    """COST-02 / COST-04: model spend by action and alias, approvals, and the monthly threshold."""
    from .store import connect, rows
    s = _s()
    with connect() as conn:
        by = rows(conn, "SELECT action, alias, model, COUNT(*) calls, SUM(input_tokens) tin, SUM(output_tokens) tout, "
                        "ROUND(SUM(cost_usd), 4) usd, SUM(used_fallback) fb FROM runs GROUP BY action, alias, model")
        month = rows(conn, "SELECT ROUND(COALESCE(SUM(cost_usd),0), 4) usd FROM runs WHERE substr(at,1,7)=substr(datetime('now'),1,7)")[0]["usd"]
        appr = rows(conn, "SELECT kind, decision, COUNT(*) n FROM approvals GROUP BY kind, decision")
        learners = rows(conn, "SELECT COUNT(*) n FROM learners")[0]["n"]
        attempts = rows(conn, "SELECT COUNT(*) n, ROUND(AVG(passed)*100) pass_pct FROM attempts WHERE submitted_at IS NOT NULL")[0]
    print(f"Model calls by action ({len(by)} groups)")
    for r in by:
        print(f"  {r['action']:<8} {r['alias']:<18} {r['model']:<16} {r['calls']:>4} calls  {r['tin'] or 0:>8} in "
              f"{r['tout'] or 0:>8} out  ${r['usd'] or 0:.4f}  fallback {r['fb'] or 0}")
    lim = s["cost"]["monthly_alert_usd"]
    print(f"This month: ${month:.4f} of the ${lim} alert threshold (reviewer {s['cost']['reviewer']})"
          + ("  ← OVER THRESHOLD" if month > lim else ""))
    print("Owner decisions: " + (", ".join(f"{r['kind']} {r['decision']} {r['n']}" for r in appr) or "none"))
    print(f"Learners {learners}; quiz attempts {attempts['n']} ({attempts['pass_pct'] or 0}% passed)")
    sys.exit(1 if month > lim else 0)


def cmd_prune(a):
    from . import accounts
    from .store import connect
    with connect() as conn:
        n = accounts.prune_inactive(conn, _s())
    print(f"deleted {n} inactive learner(s)")


# ---------------------------------------------------------------- the offline end-to-end run
def cmd_all(a):
    """Offline end to end on a fresh data folder: checks, learners, quizzes, unlocks, an on-demand build that the
    owner publishes, suggestions (legit and abusive) with an approval, feedback → revision, then the eval gate."""
    from . import simulate
    from .config import data_dir
    t0 = time.time()
    if not a.keep:
        for rel in ("warehouse", "output"):
            shutil.rmtree(data_dir() / rel, ignore_errors=True)
    summary = simulate.run(_s(), seed=a.seed, learners=a.learners)
    summary["seconds"] = round(time.time() - t0, 1)
    out = data_dir() / "output" / "run_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    simulate.print_summary(summary)
    print(f"\nwrote {out.relative_to(data_dir()) if out.is_relative_to(data_dir()) else out}")
    sys.exit(0 if summary["ok"] else 1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="course", description="Crash course: learner site, approvals, builds, evals")
    sp = p.add_subparsers(dest="cmd", required=True)

    x = sp.add_parser("serve", help="learner site (and the background worker)")
    x.add_argument("--port", default=8810, type=int)
    x.add_argument("--no-worker", action="store_true")
    x.set_defaults(fn=cmd_serve)
    x = sp.add_parser("ui", help="owner's operator app (Streamlit)")
    x.add_argument("rest", nargs=argparse.REMAINDER)
    x.set_defaults(fn=cmd_ui)
    x = sp.add_parser("worker", help="run queued builds and revisions")
    x.add_argument("--once", action="store_true")
    x.add_argument("--every", type=float, default=10)
    x.set_defaults(fn=cmd_worker)

    x = sp.add_parser("sources", help="refresh sources/tech from the site's tech pages")
    x.add_argument("--src")
    x.set_defaults(fn=cmd_sources)
    x = sp.add_parser("check", help="content checks on every level file")
    x.add_argument("--course")
    x.add_argument("-v", "--verbose", action="store_true")
    x.set_defaults(fn=cmd_check)
    x = sp.add_parser("build", help="draft one level with the writer model (held for approval)")
    x.add_argument("course")
    x.add_argument("level", choices=["familiar", "beginner", "intermediate"])
    x.set_defaults(fn=cmd_build)
    x = sp.add_parser("publish", help="owner: publish (or --reject) a draft level, or --all pending drafts")
    x.add_argument("course", nargs="?")
    x.add_argument("level", nargs="?", choices=["familiar", "beginner", "intermediate"])
    x.add_argument("--all", action="store_true")
    x.add_argument("--reviewer", required=True)
    x.add_argument("--reject", action="store_true")
    x.add_argument("--note", default="")
    x.set_defaults(fn=cmd_publish)

    x = sp.add_parser("suggest", help="suggest a topic as a learner (runs the review, emails the owner)")
    x.add_argument("text")
    x.add_argument("--email", default="learner@example.com")
    x.set_defaults(fn=cmd_suggest)
    x = sp.add_parser("queue", help="what is waiting for the owner")
    x.set_defaults(fn=cmd_queue)
    x = sp.add_parser("decide", help="owner: approve or reject a suggestion")
    x.add_argument("id", type=int)
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--reject", action="store_true")
    x.add_argument("--reviewer", required=True)
    x.add_argument("--title")
    x.add_argument("--docs", help="official docs URL the course is grounded in (https)")
    x.add_argument("--notes")
    x.set_defaults(fn=cmd_decide)
    x = sp.add_parser("revise", help="propose edits from feedback, or --decide a proposal")
    x.add_argument("course", nargs="?")
    x.add_argument("level", nargs="?")
    x.add_argument("--decide", type=int)
    x.add_argument("--accept", default="", help="comma-separated edit indexes to accept")
    x.add_argument("--reviewer", default="")
    x.set_defaults(fn=cmd_revise)

    x = sp.add_parser("eval", help="the eval gate (moderation, content, tracker, feedback)")
    x.add_argument("--alias", help="moderator model or alias to evaluate instead of course-moderator")
    x.set_defaults(fn=cmd_eval)
    x = sp.add_parser("promote", help="point an alias at a model after the eval gate passes")
    x.add_argument("alias")
    x.add_argument("model")
    x.add_argument("--skip-eval", action="store_true")
    x.set_defaults(fn=cmd_promote)
    x = sp.add_parser("deprecations", help="models near their deprecation date")
    x.add_argument("--days", type=int, default=60)
    x.set_defaults(fn=cmd_deprecations)
    x = sp.add_parser("report", help="cost, approvals and usage")
    x.set_defaults(fn=cmd_report)
    x = sp.add_parser("prune", help="delete learners inactive past the retention period")
    x.set_defaults(fn=cmd_prune)

    x = sp.add_parser("all", help="offline end-to-end run on a fresh data folder")
    x.add_argument("--seed", type=int, default=7)
    x.add_argument("--learners", type=int, default=12)
    x.add_argument("--keep", action="store_true", help="keep the existing data folder")
    x.set_defaults(fn=cmd_all)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
