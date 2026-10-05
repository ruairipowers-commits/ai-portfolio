"""EVAL-01..03, MODEL-02: run the golden set and gate on thresholds (and on no regression vs a baseline).

Metrics
  precision / recall            counted hits vs hand-labelled filler spans, all words
  ambiguous precision / recall  the same, only for words that need context (like, so, you know, kind of, right…)
  schema_valid_rate             model replies that parsed into the schema
  guard_accuracy                rewrite guard decisions vs expected PASS/REJECT
  checks                        per-case expectations (counts, grade, pace, flags, nothing private sent)
  feedback                      the speaker's own corrections (evals/feedback.yaml) still decided their way
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import ingest, lexicon as lexmod, rewrite, store, workflow
from .detect import counted
from .ingest import Segment, Transcript
from .text import norm

AMBIGUOUS = {"like", "so", "you know", "kind of", "sort of", "right", "i mean", "well", "actually", "just"}
MARK = re.compile(r"\[\[(.+?)\]\]")


def parse_marked(text: str) -> tuple[str, list[tuple[int, int, str]]]:
    clean, labels, pos, out = "", [], 0, []
    for m in MARK.finditer(text):
        out.append(text[pos:m.start()])
        start = sum(len(x) for x in out)
        out.append(m.group(1))
        labels.append((start, start + len(m.group(1)), norm(m.group(1))))
        pos = m.end()
    out.append(text[pos:])
    clean = "".join(out)
    return clean, labels


def _match(preds, labels):
    used, tp, fp = set(), [], []
    for h in preds:
        hit = next((k for k, (a, b, _) in enumerate(labels) if k not in used and h.start < b and a < h.end), None)
        if hit is None:
            fp.append(h)
        else:
            used.add(hit)
            tp.append((h, labels[hit]))
    fn = [l for k, l in enumerate(labels) if k not in used]
    return tp, fp, fn


def _is_amb(word: str) -> bool:
    return norm(word) in AMBIGUOUS


def run(alias: str | None = None, settings: store.Settings | None = None, write: bool = True) -> dict:
    s = settings or store.Settings.load()
    g = yaml.safe_load((store.ROOT / s["eval"]["golden_set"]).read_text())
    tdir = store.ROOT / "evals" / "transcripts"
    totals = {"tp": 0, "fp": 0, "fn": 0, "atp": 0, "afp": 0, "afn": 0}
    cases, calls = [], []
    held = {"tp": 0, "fp": 0, "fn": 0}          # cases written after the rules, never tuned against
    cost = 0.0

    def opts(c, **kw):
        return workflow.Options(presets=c.get("presets", []), custom_words=c.get("custom_words", ""),
                                ignore=c.get("ignore", []), speaker=c.get("speaker"), target=c.get("target"),
                                disambiguator_alias=alias, coach_alias=alias, **kw)

    for c in g.get("detection", []):
        raw = (tdir / c["file"]).read_text()
        marked_text = ingest.load(c["file"], raw).text(c.get("speaker"))
        want_text, labels = parse_marked(marked_text)
        res = workflow.analyze(ingest.load(c["file"], MARK.sub(r"\1", raw)), opts(c), s)
        assert res.text == want_text, f"{c['id']}: layout mismatch"
        tp, fp, fn = _match(counted(res.hits), labels)
        totals["tp"] += len(tp); totals["fp"] += len(fp); totals["fn"] += len(fn)
        totals["atp"] += sum(1 for h, _ in tp if _is_amb(h.entry))
        totals["afp"] += sum(1 for h in fp if _is_amb(h.entry))
        totals["afn"] += sum(1 for *_, w in fn if _is_amb(w))
        problems = _expect(c.get("expect", {}), res)
        if c.get("must_not_flag") and fp:
            problems.append("flagged normal uses: " + ", ".join(f"{h.text}@{h.start}" for h in fp))
        for secret in c.get("never_sent", []):
            if any(secret in p for p in res.model_payloads):
                problems.append(f"'{secret}' was sent to a model")
        if c.get("never_sent") and res.rewrites and not any(
                any(n in r["rewrite"] for n in c["never_sent"]) for r in res.rewrites if r["status"] == "ok"):
            problems.append("rewrites lost the real names (placeholders not restored)")
        if c.get("held_out"):
            held["tp"] += len(tp); held["fp"] += len(fp); held["fn"] += len(fn)
        cases.append({"id": c["id"], "tp": len(tp), "fp": [f"{h.text}@{h.start}" for h in fp],
                      "fn": [f"{w}@{a}" for a, _, w in fn], "problems": problems, "grade": res.score.grade,
                      "rate": res.score.rate_per_100})
        calls += res.calls
        cost += res.cost_usd

    for c in g.get("scoring", []) + g.get("config", []):
        res = workflow.analyze(Transcript([Segment(c["text"])]), opts(c, coach=False), s)
        cases.append({"id": c["id"], "problems": _expect(c.get("expect", {}), res)})
        calls += res.calls
        cost += res.cost_usd

    lex = lexmod.build(store.ROOT, ["starter"], repetition_allow=s["lexicon"].get("repetition_allow"))
    guard = []
    for c in g.get("rewrites", []):
        problems = rewrite.check(c["marked"], c["rewrite"], lex)
        got = "REJECT" if problems else "PASS"
        guard.append({"id": c["id"], "expected": c["expect"], "got": got, "problems": problems})

    fb = _feedback(s, alias)
    for c in fb:
        cost += c.pop("cost", 0.0)

    p = lambda t, f: round(t / (t + f), 3) if t + f else 1.0
    schema_ok = sum(1 for c in calls if c["status"] != "schema_invalid")
    metrics = {
        "precision": p(totals["tp"], totals["fp"]), "recall": p(totals["tp"], totals["fn"]),
        "ambiguous_precision": p(totals["atp"], totals["afp"]), "ambiguous_recall": p(totals["atp"], totals["afn"]),
        "schema_valid_rate": round(schema_ok / len(calls), 3) if calls else 1.0,
        "guard_accuracy": round(sum(1 for x in guard if x["got"] == x["expected"]) / len(guard), 3) if guard else 1.0,
        "held_out_precision": p(held["tp"], held["fp"]), "held_out_recall": p(held["tp"], held["fn"]),
        "checks_passed": sum(1 for c in cases if not c["problems"]), "checks_total": len(cases),
        "feedback_agreement": round(sum(1 for c in fb if c["ok"]) / len(fb), 3) if fb else None,
        "total_cost_usd": round(cost, 6), "model_calls": len(calls),
        **{k: v for k, v in totals.items()},
    }
    e = s["eval"]
    gates = {
        "precision": metrics["precision"] >= e["min_precision"],
        "recall": metrics["recall"] >= e["min_recall"],
        "ambiguous_precision": metrics["ambiguous_precision"] >= e["min_ambiguous_precision"],
        "ambiguous_recall": metrics["ambiguous_recall"] >= e["min_ambiguous_recall"],
        "schema_valid_rate": metrics["schema_valid_rate"] >= e["min_schema_valid_rate"],
        "guard_accuracy": metrics["guard_accuracy"] >= e["min_guard_accuracy"],
        "checks": metrics["checks_passed"] == metrics["checks_total"],
        "cost": metrics["total_cost_usd"] <= e["max_total_cost_usd"],
    }
    reg = workflow._client(s).registry
    model = reg.resolve(alias or s["llm"]["disambiguator_alias"]).name
    report = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "alias": alias or "default",
              "model": model, "prompts": {r: workflow._prompt(s, r)[1] for r in ("disambiguator", "coach")},
              "passed": all(gates.values()), "gates": gates, "metrics": metrics, "cases": cases, "guard": guard,
              "feedback": fb}
    if write:
        out = store.workspace() / "output" / "evals"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"eval-{report['alias']}-{report['ts'][:19].replace(':', '')}.json").write_text(json.dumps(report, indent=2))
        (out / f"latest-{report['alias']}.json").write_text(json.dumps(report, indent=2))
    from . import telemetry
    telemetry.emit("eval", status="ok" if report["passed"] else "failed", model=model,
                   cost_usd=metrics["total_cost_usd"], records_in=metrics["checks_total"],
                   records_out=metrics["checks_passed"], flags=[] if report["passed"] else ["eval_failed"],
                   detail={k: metrics[k] for k in ("precision", "recall", "ambiguous_precision", "ambiguous_recall",
                                                   "guard_accuracy", "schema_valid_rate")})
    return report


def _expect(exp: dict, res: workflow.Result) -> list[str]:
    sc, out = res.score, []
    for k in ("words", "fillers", "grade"):
        if k in exp and getattr(sc, k) != exp[k]:
            out.append(f"{k} {getattr(sc, k)} ≠ {exp[k]}")
    for k in ("weighted", "rate_per_100"):
        if k in exp and abs(getattr(sc, k) - exp[k]) > 0.01:
            out.append(f"{k} {getattr(sc, k)} ≠ {exp[k]}")
    if "wpm" in exp and (not sc.timing or abs(sc.timing.words_per_minute - exp["wpm"]) > 0.1):
        out.append(f"wpm {sc.timing.words_per_minute if sc.timing else None} ≠ {exp['wpm']}")
    if "pauses" in exp and (not sc.timing or sc.timing.pauses != exp["pauses"]):
        out.append(f"pauses {sc.timing.pauses if sc.timing else None} ≠ {exp['pauses']}")
    for f in exp.get("flags", []):
        if f not in res.flags:
            out.append(f"missing flag {f}")
    if "warnings_min" in exp and len(res.warnings) < exp["warnings_min"]:
        out.append(f"{len(res.warnings)} warnings < {exp['warnings_min']}")
    if "warnings_contain" in exp and not any(exp["warnings_contain"] in w for w in res.warnings):
        out.append(f"no warning containing '{exp['warnings_contain']}'")
    return out


def feedback_path() -> Path:
    return store.workspace() / "evals" / "feedback.yaml"


def add_feedback(word: str, before: str, after: str, is_filler: bool) -> None:
    """HITL-03: a speaker's correction becomes an eval case. Only the few words around it are kept, and they're
    saved only when the speaker ticks 'save as a test case'."""
    p = feedback_path()
    data = yaml.safe_load(p.read_text()) if p.exists() else None
    data = data or {"cases": []}
    data["cases"].append({"word": word, "before": before[-80:], "after": after[:80], "is_filler": bool(is_filler),
                          "added": store.now()})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _feedback(s: store.Settings, alias: str | None) -> list[dict]:
    paths = [store.ROOT / "evals" / "feedback.yaml", feedback_path()]
    seen, out = set(), []
    for p in paths:
        if not p.exists() or p in seen:
            continue
        seen.add(p)
        for c in (yaml.safe_load(p.read_text()) or {}).get("cases", []):
            text = c["before"] + c["word"] + c["after"]
            res = workflow.analyze(Transcript([Segment(text)]),
                                   workflow.Options(presets=[], custom_words=c["word"], coach=False,
                                                    disambiguator_alias=alias), s)
            h = next((h for h in res.hits if h.start == len(c["before"])), None)
            got = h.verdict if h else "missing"
            want = "filler" if c["is_filler"] else "not_filler"
            out.append({"word": c["word"], "want": want, "got": got, "ok": got == want, "cost": res.cost_usd})
    return out
