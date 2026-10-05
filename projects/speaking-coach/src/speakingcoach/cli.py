"""speaking-coach CLI.

  coach analyze talk.vtt --words my-list.txt --speaker "Sam Ortiz"   # report to output/
  coach analyze --words my-list.txt                                  # word list only: show how it will match
  coach all                                                          # every sample → output/ (offline demo)
  coach eval [--alias coach-candidate --baseline coach-disambiguator]
  coach promote coach-disambiguator <model>  ·  coach models-check  ·  coach cost-report  ·  coach history  ·  coach ui
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from . import evals, lexicon as lexmod, report, store, telemetry, workflow
from .llm import Registry
from .store import ROOT, Settings


def _opts(args, s) -> workflow.Options:
    words = Path(args.words).read_text() if getattr(args, "words", None) else None
    presets = args.presets.split(",") if getattr(args, "presets", None) is not None else None
    if presets == [""]:
        presets = []
    return workflow.Options(presets=presets, custom_words=words, ignore=args.ignore or None,
                            speaker=args.speaker, target=args.target, disambiguator_alias=args.alias,
                            coach_alias=args.alias, save_history=True if args.history else None)


RULE_HELP = {
    "always": "counted every time",
    "opener": "counted only when it starts a sentence — “So, we shipped it.” counts; “We tested it, so it works.” doesn't",
    "closer": "counted only when it ends a thought — “That's the plan, I guess.” counts; “I guess we could try.” doesn't",
    "context": "neighbour rules first, a model for the unclear ones — “It was, like, fine.” counts; “I like the plan.” doesn't",
}


def preview(lex: lexmod.Lexicon) -> str:
    """Word list only: each entry, its rule, and what the rule means."""
    lines = [f"{'phrase':24s} {'category':18s} {'weight':>6s}  rule"]
    lines += [f"{e.text:24s} {e.category:18s} {e.weight:6g}  {e.rule}" for e in lex.active()]
    lines.append("")
    lines += [f"{r}: {RULE_HELP[r]}" for r in RULE_HELP if any(e.rule == r for e in lex.active())]
    if lex.repetition:
        lines.append("repetition: “the the” and “I've, uh, I've” count; “had had” is allowed")
    if lex.ignore:
        lines.append("ignored: " + ", ".join(sorted(lex.ignore)))
    lines += [f"! {w}" for w in lex.warnings]
    return "\n".join(lines)


def cmd_analyze(args, s):
    o = _opts(args, s)
    if not args.file:
        lex = workflow.build_lexicon(s, o)
        print(preview(lex))
        out = store.workspace() / "output" / "word-list.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(lex.to_text())
        print(f"\nsaved {out.relative_to(store.workspace())}")
        return
    try:
        telemetry.require_enabled("analyze")
    except telemetry.WorkflowDisabled as e:
        sys.exit(str(e))
    t = workflow.load_file(args.file)
    if args.speaker is None and len(t.speakers) > 1:
        print(f"speakers found: {', '.join(t.speakers)} — analysing everyone; pick one with --speaker")
    res = workflow.analyze(t, o, s)
    _write(res, Path(args.file).stem)
    telemetry.flush()


def _write(res, stem: str) -> None:
    out = store.workspace() / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.report.md").write_text(report.markdown(res))
    (out / f"{stem}.report.html").write_text(report.html(res))
    sc = res.score
    print(f"{stem}: grade {sc.grade} · {sc.fillers} fillers / {sc.words} words = {sc.rate_per_100} per 100 "
          f"(target {sc.target_per_100:g}) · disputed {sc.disputed} · rewrites "
          f"{sum(1 for r in res.rewrites if r['status'] == 'ok')}/{len(res.rewrites)} · ${res.cost_usd:.4f}"
          + (f" · {sc.timing.words_per_minute:g} wpm" if sc.timing else "")
          + (f" · flags {','.join(res.flags)}" if res.flags else ""))


def cmd_all(args, s):
    samples = ROOT / "samples"
    if not samples.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")], check=True)
    lists = {"pitch": ("pitch-crutches.txt", []), "physics-lecture": ("lecturer.txt", [])}   # samples with their own list
    for f in sorted(samples.glob("*.*")):
        t = workflow.load_file(f)
        o = workflow.Options(speaker="Sam Ortiz" if "Sam Ortiz" in t.speakers else None)
        if f.stem in lists:
            o.custom_words = (samples / "word-lists" / lists[f.stem][0]).read_text()
            o.presets = lists[f.stem][1]
        _write(workflow.analyze(t, o, s), f.stem)
    telemetry.flush()


def cmd_eval(args, s):
    rep = evals.run(args.alias, s)
    m = rep["metrics"]
    print(json.dumps({k: m[k] for k in m if k not in ("tp", "fp", "fn", "atp", "afp", "afn")}, indent=2))
    ok = rep["passed"]
    for c in rep["cases"]:
        if c["problems"]:
            print(f"  ✗ {c['id']}: {'; '.join(c['problems'])}")
    if args.baseline:
        base = _latest(args.baseline) or evals.run(args.baseline, s)
        worse = [k for k in ("precision", "recall", "ambiguous_precision", "ambiguous_recall", "guard_accuracy")
                 if m[k] + 1e-9 < base["metrics"][k]]
        if worse:
            print("REGRESSION vs baseline:", ", ".join(f"{k} {m[k]} < {base['metrics'][k]}" for k in worse))
            ok = False
    print("EVAL GATE:", "PASS" if ok else "FAIL " + str([k for k, v in rep["gates"].items() if not v]))
    telemetry.flush()
    sys.exit(0 if ok else 1)


def _latest(alias: str) -> dict | None:
    p = store.workspace() / "output" / "evals" / f"latest-{alias}.json"
    return json.loads(p.read_text()) if p.exists() else None


def cmd_promote(args, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    reg.resolve(args.model)
    rep = next((r for r in (_latest(a) for a in [args.model, *[a for a, n in reg.aliases.items() if n == args.model]])
                if r and r["model"] == args.model), None)
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {args.model}: no passing eval on record (MODEL-02). "
                 f"Point coach-candidate at it and run `coach eval --alias coach-candidate`.")
    current = {r: workflow._prompt(s, r)[1] for r in ("disambiguator", "coach")}
    if rep["prompts"] != current:
        sys.exit("Refusing to promote: a prompt changed since that eval (MODEL-04). Re-run the eval.")
    reg.set_alias(args.alias, args.model)
    print(f"{args.alias} -> {args.model} (eval {rep['ts']} passed)")


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
            issues.append(f"deprecates {m.deprecation_date} — start the migration runbook")
        print(f"{alias:20s} -> {name:14s} {m.provider}:{m.model_id} {'OK' if not issues else '; '.join(issues)}")
        rc |= bool(issues)
    sys.exit(rc)


def cmd_cost_report(args, s):
    by: dict[tuple[str, str], list[float]] = {}
    blocked = 0
    for r in store.read_runs():
        for c in r.get("calls", []):
            if c["status"] == "budget_blocked":
                blocked += 1
                continue
            k = (r["ts"][:7], c["model"])
            v = by.setdefault(k, [0, 0, 0, 0.0])
            v[0] += 1; v[1] += c["input_tokens"]; v[2] += c["output_tokens"]; v[3] += c["cost_usd"]
    limit = s["cost"]["monthly_alert_usd"]
    print(f"{'month':8s} {'model':14s} {'calls':>6s} {'in_tok':>8s} {'out_tok':>8s} {'usd':>9s}")
    totals: dict[str, float] = {}
    for (mo, model), (n, ti, to, usd) in sorted(by.items()):
        totals[mo] = totals.get(mo, 0) + usd
        print(f"{mo:8s} {model:14s} {n:6d} {ti:8d} {to:8d} {usd:9.4f}")
    for mo, usd in totals.items():
        print(f"{mo} total ${usd:.4f} vs alert ${limit:.2f}" + ("  <-- OVER ALERT (COST-04)" if usd > limit else ""))
    print(f"budget-blocked calls: {blocked}")


def cmd_history(args, s):
    rows = store.history(s, args.speaker)
    if not rows:
        print("no history yet — run `coach analyze FILE --history` (history is off by default)")
    for r in rows:
        print(f"{r['ts'][:16]} {r['speaker']:12s} grade {r['grade']} · {r['rate']:5.2f}/100 · "
              f"{r['fillers']}/{r['words']} · top {', '.join(w for w, _ in json.loads(r['top'])[:3])}")


def cmd_ui(args, s):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py"))], cwd=ROOT)


def main(argv=None):
    p = argparse.ArgumentParser(prog="coach", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse a transcript (or preview a word list)")
    a.add_argument("file", nargs="?")
    a.add_argument("--words", help="your word list (one per line: phrase | category | weight | rule)")
    a.add_argument("--presets", help="comma-separated presets (default from settings; '' for none)")
    a.add_argument("--ignore", action="append", help="never flag this word (repeatable)")
    a.add_argument("--speaker", help="only this person's turns (meeting exports)")
    a.add_argument("--target", type=float, help="target fillers per 100 words")
    a.add_argument("--alias", help="model alias for both roles (default from settings)")
    a.add_argument("--history", action="store_true", help="save this run's numbers to your local history")
    a.set_defaults(fn=cmd_analyze)
    sub.add_parser("all", help="analyse every sample (offline demo)").set_defaults(fn=cmd_all)
    e = sub.add_parser("eval", help="golden-set eval; non-zero exit on failure (MODEL-02 gate)")
    e.add_argument("--alias"); e.add_argument("--baseline"); e.set_defaults(fn=cmd_eval)
    pr = sub.add_parser("promote", help="point an alias at a model that passed the eval")
    pr.add_argument("alias"); pr.add_argument("model"); pr.set_defaults(fn=cmd_promote)
    mc = sub.add_parser("models-check", help="approval, pricing and deprecation check")
    mc.add_argument("--today"); mc.set_defaults(fn=cmd_models_check)
    sub.add_parser("cost-report", help="tokens and $ by month and model").set_defaults(fn=cmd_cost_report)
    h = sub.add_parser("history", help="your progress across runs (if history is on)")
    h.add_argument("--speaker"); h.set_defaults(fn=cmd_history)
    sub.add_parser("ui", help="Streamlit app: input → run → output").set_defaults(fn=cmd_ui)
    args = p.parse_args(argv)
    args.fn(args, Settings.load())


if __name__ == "__main__":
    main()
