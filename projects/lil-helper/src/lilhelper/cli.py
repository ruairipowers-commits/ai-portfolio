"""Command line: `helper <command>`. Everything the app does, runnable offline with the mock model.

  helper plan [--week 2026-10-05] [--no-ideas]   draft a week (plan, list, options, jobs, savings)
  helper show [--week …]                         print the stored draft
  helper swap DAY MEAL [--to RECIPE]             swap one meal; the rest stays put
  helper approve PERSON [--choice balanced]      a named adult approves (HITL-02)
  helper flyer IMAGE_OR_TXT --store STORE        read a flyer into unconfirmed specials
  helper feedback DAY MEAL all|some_left|lots_left [--rating 4] [--by dana]
  helper print [--week …] [--month 2026-10]      fridge PDFs → output/
  helper ics                                      calendar feed → output/meals.ics
  helper email [--week …]                         weekly email → Resend, or output/outbox/
  helper simulate --weeks 4                      draft, approve and give feedback for N weeks
  helper eval [--alias helper-candidate]         golden set gate (EVAL-02, MODEL-02)
  helper promote ALIAS MODEL                     move an alias after a passing eval
  helper cost-report | check-models              COST-02/04, MODEL-03
  helper job draft|email|restock|tick            run one scheduled job now (tick: everything due, every household)
  helper cookfrom "chicken, spinach, rice"       make a meal from what I've got
  helper forecast INGREDIENT [--weeks 4]         how much the coming plans need, when, and what to buy
  helper report [--weeks 8]                      cost per week, meal and person, with analysis
  helper spend-import FILE.csv [--card ID]       food purchases from a card statement
  helper receipt FILE.txt [--card ID]            read and record a receipt (text; photos go through the app)
  helper household create NAME --email E --you N  a household with you as admin (server setup without the app)
  helper household import FILE --email E --person ID   bring an existing household.yaml into an account
  helper household list                          households on this server
  helper serve | ui                              API (FastAPI) | Streamlit demo

  --household ID  (any command) work in that household's folder on this server
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import os
import sys
from pathlib import Path

from . import telemetry
from .config import ROOT, Settings, load_household, work_root

DEFAULT_WEEK = dt.date(2026, 10, 5)


def _week(a) -> dt.date:
    return dt.date.fromisoformat(a.week) if getattr(a, "week", None) else DEFAULT_WEEK


def cmd_plan(a) -> int:
    from . import week
    r = week.draft(_week(a), ideas=not a.no_ideas, choice=a.choice)
    _print_week(r)
    return 0 if r.plan.entries else 1


def _print_week(r) -> None:
    print(f"Week of {r.week_of}: {r.plan.status} · {len(r.plan.entries)} meals · {r.ms} ms · model ${r.cost_usd:.4f}")
    if r.flags:
        print("  flags:", ", ".join(r.flags))
    for e in r.plan.entries:
        print(f"  {e.day} {e.meal:9} {e.name}  ({e.servings} servings, ~${e.est_cost:.2f})  — "
              f"{r.notes.get((e.day, e.meal), '')}")
    for n, k in r.plan.special_nights.items():
        print(f"  {n} dinner    {k} night")
    if r.ideas:
        for x in r.ideas.rejected:
            print(f"  idea rejected: {x['name']} — {'; '.join(x['why'])}")
    print("  shopping options:")
    for name, sp in r.options.items():
        stores = ", ".join(f"{o.store_name} {o.mode.replace('_', ' ')} ${o.total:.2f}" for o in sp.orders)
        print(f"    {name:9} ${sp.total:7.2f}  {sp.minutes:3d} min  {stores}")
    if r.savings:
        s = r.savings
        print(f"  saved ${s.dollars_saved:.2f} vs ${s.baseline_dollars:.2f} at the home store (specials "
              f"${s.specials_saved:.2f}, credits ${s.credits:.2f}); ~{s.minutes_saved:.0f} min")
    for p in r.pets:
        print(f"  {p.name}: restock {p.restock or 'nothing'}; {len(p.extras)} extras; blocked {len(p.blocked)}")
    load = ", ".join(f"{k} {v}" for k, v in r.chore_load.items())
    print(f"  jobs: {len(r.chores)} assignments; load {load}")


def cmd_show(a) -> int:
    from . import store
    w = store.get_week(store.connect(), _week(a).isoformat())
    print(json.dumps(w, indent=1, default=str) if w else "no draft for that week")
    return 0 if w else 1


def cmd_swap(a) -> int:
    from . import week
    r = week.swap(_week(a), a.day, a.meal, to=a.to)
    _print_week(r)
    return 0


def cmd_approve(a) -> int:
    from . import week
    print(json.dumps(week.approve(_week(a), a.person, a.seconds, a.choice)))
    return 0


def cmd_flyer(a) -> int:
    from . import ai, catalog
    from .prices import PriceBook
    h = load_household()
    s = Settings.load()
    c = catalog.get(h.info.get("region", "northeast-us"))
    pb = PriceBook(h, _week(a))
    p = Path(a.path)
    image = p.read_bytes() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else None
    side = p.with_suffix(".txt")
    text = p.read_text() if p.suffix == ".txt" else (side.read_text() if side.exists() else None)
    res = ai.read_flyer(ai.AIContext.make(s), h, c, pb, a.store, image=image, text=text)
    print(json.dumps({"flags": res.flags, "other": res.other, "items": res.items}, indent=1))
    return 0


def cmd_feedback(a) -> int:
    from . import feedback, store
    con = store.connect()
    w = store.get_week(con, _week(a).isoformat())
    e = next((e for e in w["plan"]["entries"] if e["day"] == a.day and e["meal"] == a.meal), None) if w else None
    if not e:
        print("no such meal in that week")
        return 1
    feedback.record(con, _week(a).isoformat(), a.day, a.meal, e["recipe"], a.eaten, a.rating, a.by)
    print("recorded; portion changes:", feedback.learn(con, Settings.load(), _week(a).isoformat()))
    return 0


def cmd_print(a) -> int:
    from . import outputs, store
    h = load_household()
    con = store.connect()
    out = work_root() / "output"
    out.mkdir(parents=True, exist_ok=True)
    w = store.get_week(con, _week(a).isoformat())
    if w:
        (out / f"week-{_week(a)}.pdf").write_bytes(outputs.week_pdf(h, w))
        print("wrote", out / f"week-{_week(a)}.pdf")
    y, m = map(int, (a.month or _week(a).strftime("%Y-%m")).split("-"))
    weeks = [store.get_week(con, r["week_of"]) for r in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
    (out / f"month-{y}-{m:02d}.pdf").write_bytes(outputs.month_pdf(h, y, m, weeks))
    print("wrote", out / f"month-{y}-{m:02d}.pdf")
    return 0


def cmd_ics(a) -> int:
    from . import outputs, store
    con = store.connect()
    weeks = [store.get_week(con, r["week_of"]) for r in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
    p = work_root() / "output" / "meals.ics"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(outputs.ics(load_household(), weeks))
    print("wrote", p)
    return 0


def cmd_email(a) -> int:
    from . import outputs, store
    w = store.get_week(store.connect(), _week(a).isoformat())
    print(outputs.send_week_email(load_household(), w, {}))
    return 0


def cmd_simulate(a) -> int:
    from . import simulate
    res = simulate.run(a.weeks, start=_week(a))
    print(json.dumps(res, indent=1, default=str))
    return 0


def cmd_eval(a) -> int:
    from . import evals
    rep = evals.run(alias=a.alias)
    print(json.dumps(rep["metrics"], indent=1))
    for c in rep["cases"]:
        if not c["passed"]:
            print("FAIL", c["id"], c.get("detail"))
    print("EVAL GATE:", "PASS" if rep["passed"] else "FAIL")
    return 0 if rep["passed"] else 1


def cmd_promote(a) -> int:
    from . import evals
    from .llm import Registry
    if not evals.latest_passed(a.model):
        print(f"No passing eval report for {a.model}. Run: helper eval --alias helper-candidate (pointed at it).")
        return 1
    Registry(ROOT / "config" / "models.yaml").set_alias(a.alias, a.model)
    print(f"{a.alias} → {a.model}")
    return 0


def cmd_cost(a) -> int:
    from . import evals
    print(json.dumps(evals.cost_report(), indent=1))
    return 0


def cmd_check_models(a) -> int:
    from .llm import Registry
    reg = Registry(ROOT / "config" / "models.yaml")
    warn = int(Settings.load()["governance"]["deprecation_warning_days"])
    bad = 0
    for alias, name in reg.aliases.items():
        m = reg.models[name]
        if m.deprecation_date and (m.deprecation_date - dt.date.today()).days < warn:
            print(f"WARN {alias} → {name} deprecates {m.deprecation_date}")
            bad += 1
        else:
            print(f"ok   {alias} → {name}")
    return 1 if bad else 0


def cmd_job(a) -> int:
    from . import schedule
    if a.name == "tick":
        print(json.dumps(schedule.tick_all(), default=str))
        return 0
    print(json.dumps({"draft": schedule.job_draft, "email": schedule.job_email,
                      "restock": schedule.job_restock}[a.name](), default=str))
    return 0


def _ctx():
    from . import catalog
    from .prices import PriceBook
    h = load_household()
    c = catalog.for_household(h)
    return h, c, PriceBook(h, dt.date.today(), catalog=c)


def cmd_cookfrom(a) -> int:
    from . import cookfrom
    h, c, pb = _ctx()
    r = cookfrom.suggest(h, c, pb, text=a.text, day=a.day)
    if r["not_recognised"]:
        print("not recognised:", ", ".join(r["not_recognised"]))
    for i in r["ideas"]:
        miss = ", ".join(m["name"] for m in i["missing"]) or "nothing"
        print(f"{i['name']:55} {i['coverage']:.0%} in the house; missing {miss} (~${i['missing_cost']:.2f})"
              + (f" — {'; '.join(i['why'])}" if i["why"] else ""))
    return 0


def cmd_forecast(a) -> int:
    from . import forecast
    h, c, pb = _ctx()
    print(json.dumps(forecast.forecast(h, c, pb, a.ingredient, _week(a), a.weeks), indent=1, default=str))
    return 0


def cmd_report(a) -> int:
    from . import catalog, reports
    h = load_household()
    r = reports.cost_report(h, catalog.for_household(h), end=_week(a), weeks=a.weeks)
    for w in r["weeks"]:
        print(f"{w['week_of']}  bill ${w['food_bill']:7.2f}  meals used ${w['food_used']:7.2f}  out ${w['eating_out']:6.2f}"
              f"  pet ${w['pet_food']:6.2f}")
    for p in r["people"]:
        print(f"  {p['name']:10} ${p['per_week']:.2f} a week (${p['per_day']:.2f} a day)")
    print("\n".join("• " + x for x in r["analysis"]))
    return 0


def cmd_spend_import(a) -> int:
    from . import spend, store
    print(json.dumps(spend.import_statement(store.connect(), load_household(), Path(a.file).read_text(), a.card,
                                            "cli")))
    return 0


def cmd_receipt(a) -> int:
    from . import ai, spend, store
    h, c, pb = _ctx()
    res = ai.read_receipt(ai.AIContext.make(Settings.load()), h, c, pb, text=Path(a.file).read_text())
    print(json.dumps(res.__dict__, indent=1, default=str))
    if a.confirm:
        print(spend.confirm_receipt(store.connect(), h, res, a.card, "cli"))
    return 0


def cmd_mail_test(a) -> int:
    """Send one test email the way sign-in links go out, and say exactly what happened."""
    from . import outputs
    from .config import data_root
    print(f"sender: {outputs.mail_from()}")
    print(f"resend key: {'set' if os.getenv('RESEND_API_KEY') else 'NOT SET (emails go to a file, not to anyone)'}")
    res = outputs.send_mail(a.to, "DinnerPeace test email", "<p>If you can read this, sign-in emails will arrive.</p>",
                            "test", data_root() / "outbox")
    print(f"result: {res}")
    if res.startswith("failed"):
        print("Most often: the sender's domain isn't verified in Resend (resend.com → Domains), or the key is wrong.")
    elif res == "outbox":
        print(f"Written to {data_root() / 'outbox'}; set RESEND_API_KEY to send for real.")
    return 0 if res == "sent" else 1


def cmd_household(a) -> int:
    from . import accounts
    con = accounts.connect()
    if a.action == "list":
        for hh in accounts.households(con):
            print(hh["id"], hh["name"], [m["email"] for m in accounts.members(con, hh["id"])])
        return 0
    u = accounts.get_or_create_user(con, a.email)
    if a.action == "create":
        hid = accounts.create_household(con, u["id"], a.name, "northeast-us",
                                        {"id": re.sub(r"[^a-z0-9]+", "_", a.you.lower()).strip("_"), "name": a.you,
                                         "email": a.email, "can_cook": True})
    else:
        hid = accounts.import_household(con, u["id"], a.name, a.person)
    print(f"household {hid}; {a.email} is its admin. Sign in to the app with that email.")
    return 0


def cmd_serve(a) -> int:
    import uvicorn
    uvicorn.run("lilhelper.api:app", host=a.host, port=a.port)
    return 0


def cmd_ui(a) -> int:
    import subprocess
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="helper", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.set_defaults(fn=fn)
        sp.add_argument("--week")
        sp.add_argument("--household", help="a household id on this server")
        return sp

    sp = add("plan", cmd_plan)
    sp.add_argument("--no-ideas", action="store_true")
    sp.add_argument("--choice", default="balanced", choices=["cheapest", "balanced", "fastest"])
    add("show", cmd_show)
    sp = add("swap", cmd_swap)
    sp.add_argument("day")
    sp.add_argument("meal")
    sp.add_argument("--to")
    sp = add("approve", cmd_approve)
    sp.add_argument("person")
    sp.add_argument("--choice", default="balanced")
    sp.add_argument("--seconds", type=float, default=90)
    sp = add("flyer", cmd_flyer)
    sp.add_argument("path")
    sp.add_argument("--store", required=True)
    sp = add("feedback", cmd_feedback)
    sp.add_argument("day")
    sp.add_argument("meal")
    sp.add_argument("eaten", choices=["all", "some_left", "lots_left"])
    sp.add_argument("--rating", type=int)
    sp.add_argument("--by", default="dana")
    sp = add("print", cmd_print)
    sp.add_argument("--month")
    add("ics", cmd_ics)
    add("email", cmd_email)
    sp = add("simulate", cmd_simulate)
    sp.add_argument("--weeks", type=int, default=4)
    sp = add("eval", cmd_eval)
    sp.add_argument("--alias")
    sp = add("promote", cmd_promote)
    sp.add_argument("alias")
    sp.add_argument("model")
    add("cost-report", cmd_cost)
    add("check-models", cmd_check_models)
    sp = add("job", cmd_job)
    sp.add_argument("name", choices=["draft", "email", "restock", "tick"])
    sp = add("cookfrom", cmd_cookfrom)
    sp.add_argument("text")
    sp.add_argument("--day")
    sp = add("forecast", cmd_forecast)
    sp.add_argument("ingredient")
    sp.add_argument("--weeks", type=int, default=4)
    sp = add("report", cmd_report)
    sp.add_argument("--weeks", type=int, default=8)
    sp = add("spend-import", cmd_spend_import)
    sp.add_argument("file")
    sp.add_argument("--card")
    sp = add("receipt", cmd_receipt)
    sp.add_argument("file")
    sp.add_argument("--card")
    sp.add_argument("--confirm", action="store_true")
    sp = add("mail-test", cmd_mail_test)
    sp.add_argument("to", help="an address to send the test email to")
    sp = add("household", cmd_household)
    sp.add_argument("action", choices=["create", "import", "list"])
    sp.add_argument("name", nargs="?", help="household name (create) or household.yaml path (import)")
    sp.add_argument("--email")
    sp.add_argument("--you", default="Me")
    sp.add_argument("--person")
    sp = add("serve", cmd_serve)
    sp.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    sp.add_argument("--port", type=int, default=int(os.getenv("PORT", "8650")))
    add("ui", cmd_ui)
    a = p.parse_args(argv)
    from .config import tenant
    try:
        with tenant(getattr(a, "household", None)):
            return a.fn(a)
    except telemetry.WorkflowDisabled as e:
        print(f"Paused by the governance console: {e}")
        return 3
    finally:
        telemetry.flush()


if __name__ == "__main__":
    sys.exit(main())
