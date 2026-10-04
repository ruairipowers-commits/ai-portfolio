"""Eval gate (EVAL-01/02, MODEL-02): is the verifier strict enough, is grading right, does the generator deliver?

    puzzle eval                                   # current aliases
    puzzle eval --role solver --alias puzzle-candidate      # try a new SOLVER model against the golden drafts
    puzzle eval --role generator --alias puzzle-candidate   # try a new GENERATOR model (fresh puzzles, one per kind)

Writes output/evals/<timestamp>.json; exits non-zero when any threshold fails. `puzzle promote` refuses a model
without a passing report on the current prompts.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import yaml

from . import generate, grading, puzzles, verify
from .config import Settings, data_dir


def _settings_with(s: Settings, role: str | None, alias: str | None) -> Settings:
    if not alias:
        return s
    s2 = copy.copy(s)
    s2.raw = copy.deepcopy(s.raw)
    s2.raw["llm"]["solver_alias" if role == "solver" else "generator_alias"] = alias
    return s2


def run(s: Settings | None = None, role: str = "solver", alias: str | None = None) -> dict:
    s = s or Settings.load()
    s = _settings_with(s, role, alias)
    gold = yaml.safe_load(s.path(s["eval"]["golden_set"]).read_text())
    t0 = time.perf_counter()
    ctx = verify.Ctx(s, verify.make_client(s, max_usd=s["eval"]["max_total_cost_usd"]), None, purpose="eval")
    cases = []
    # ---- verifier on golden drafts
    for g in gold["generation"]:
        d = puzzles.make(g["kind"], g["seed"], g["difficulty"], g.get("scenario"))
        ctx.history = [puzzles.make(g["kind"], g["seed"], g["difficulty"])] if g.get("history_same") else []
        _, rep = verify.verify(copy.deepcopy(d), ctx)
        cases.append({"id": g["id"], "part": "generation", "expected": g["expected"], "got": rep.decision,
                      "ok": rep.decision == g["expected"], "must_reject": "must_reject" in g.get("tags", []),
                      "reasons": rep.reasons, "flags": rep.flags})
    ctx.history = []
    # ---- grading (code only)
    for g in gold["grading"]:
        if g.get("closed"):
            got = _closed_case(s, g)
        else:
            forms = g.get("forms") or [g["key"]]
            hashes = grading.key_hashes("eval", forms, g["answer_type"], g.get("decimals"))
            ok, _ = grading.grade(g["submit"], g["answer_type"], g.get("decimals"), hashes, "eval")
            got = "CORRECT" if ok else "INCORRECT"
        cases.append({"id": g["id"], "part": "grading", "expected": g["expected"], "got": got, "ok": got == g["expected"]})
    # ---- scoring
    for g in gold["scoring"]:
        got = [grading.points(n, True, s.puzzles["scoring"]) for n in range(1, len(g["expected"]) + 1)]
        ok = got == g["expected"] and grading.points(3, False, s.puzzles["scoring"]) == g["unsolved"]
        cases.append({"id": g["id"], "part": "scoring", "expected": g["expected"], "got": got, "ok": ok})
    # ---- generator: one fresh puzzle per enabled kind, first round only
    gen = []
    if role == "generator" or not alias:
        s1 = copy.copy(s)
        s1.puzzles = copy.deepcopy(s.puzzles)
        s1.puzzles["generation"]["max_rounds"] = 1
        gctx = verify.Ctx(s1, ctx.client, None, purpose="eval")
        for t in s.enabled_tracks():
            for k in s.track(t)["kinds"]:
                d, rep, _ = generate.generate_one(gctx, t, k, "medium", seed=4242)
                learn = not verify.learning_problems(d, s) if d else False
                gen.append({"kind": k, "passed": rep.decision == "PUBLISH", "schema_valid": d is not None,
                            "learning_ok": learn or t not in s.puzzles["learning"]["require_objective_for"],
                            "reasons": rep.reasons[:3]})
        ctx.cost += gctx.cost if gctx is not ctx else 0
    return _report(s, role, alias, cases, gen, ctx, time.perf_counter() - t0)


def _closed_case(s: Settings, g: dict) -> str:
    """a05: submit to a puzzle whose window has closed, through the real game code on a throwaway database."""
    from . import game, store
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{d}/eval.db"
        try:
            eng = store.engine(s)
            with eng.begin() as c:
                pz = puzzles.make("cipher", 1, "easy")
                pz.update(answer=g["key"], accepted_forms=[g["key"]])
                pid = generate.store_puzzle(c, s, pz, {}, status="open", source="generated", day="2026-01-05")
                c.execute(store.puzzles.update().where(store.puzzles.c.id == pid).values(
                    opens_at=store.now() - timedelta(days=2), closes_at=store.now() - timedelta(days=1)))
                pl = c.execute(store.players.insert().values(email="e@x.invalid", handle="evaluser", tracks=[],
                                                             created_at=store.now())).inserted_primary_key[0]
                c.execute(store.acceptances.insert().values(player_id=pl, puzzle_id=pid, accepted_at=store.now(), attempts=0, points=0))
                res = game.submit(c, s, pl, pid, g["submit"])
            eng.dispose()
            store._engines.pop(f"sqlite:///{d}/eval.db", None)
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
    return res["status"].upper()


def _report(s, role, alias, cases, gen, ctx, secs) -> dict:
    e = s["eval"]
    genc = [c for c in cases if c["part"] == "generation"]
    must = [c for c in genc if c["must_reject"]]
    grad = [c for c in cases if c["part"] != "generation"]
    m = {
        "verifier_accuracy": sum(c["ok"] for c in genc) / max(1, len(genc)),
        "must_reject_recall": sum(c["got"] == "REJECT" for c in must) / max(1, len(must)),
        "grading_accuracy": sum(c["ok"] for c in grad) / max(1, len(grad)),
        "total_cost_usd": round(ctx.cost, 6),
    }
    checks = {
        "verifier_accuracy": m["verifier_accuracy"] >= e["min_verifier_accuracy"],
        "must_reject_recall": m["must_reject_recall"] >= e["min_must_reject_recall"],
        "grading_accuracy": m["grading_accuracy"] >= e["min_grading_accuracy"],
        "total_cost_usd": m["total_cost_usd"] <= e["max_total_cost_usd"],
    }
    if gen:
        m.update({"generation_pass_rate": sum(g["passed"] for g in gen) / len(gen),
                  "schema_valid_rate": sum(g["schema_valid"] for g in gen) / len(gen),
                  "learning_fields_rate": sum(g["learning_ok"] for g in gen) / len(gen)})
        checks.update({"generation_pass_rate": m["generation_pass_rate"] >= e["min_generation_pass_rate"],
                       "schema_valid_rate": m["schema_valid_rate"] >= e["min_schema_valid_rate"],
                       "learning_fields_rate": m["learning_fields_rate"] >= e["min_learning_fields_rate"]})
    reg = ctx.client.registry
    _, gsha = verify.prompt(s, "generator_prompt")
    _, ssha = verify.prompt(s, "solver_prompt")
    rep = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "role": role, "alias": alias,
           "generator_model": reg.name_of(s["llm"]["generator_alias"]), "solver_model": reg.name_of(s["llm"]["solver_alias"]),
           "prompt_sha": {"generator": gsha, "solver": ssha}, "metrics": m, "checks": checks,
           "passed": all(checks.values()), "seconds": round(secs, 1), "cases": cases, "generator_cases": gen}
    out = data_dir() / "output" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{time.strftime('%Y%m%d-%H%M%S')}-{role}.json").write_text(json.dumps(rep, indent=2, default=str))
    return rep


def last_passing(model: str, role: str) -> dict | None:
    s = Settings.load()
    _, gsha = verify.prompt(s, "generator_prompt")
    _, ssha = verify.prompt(s, "solver_prompt")
    for f in sorted((data_dir() / "output" / "evals").glob("*.json"), reverse=True):
        r = json.loads(f.read_text())
        if r.get("passed") and r.get(f"{role}_model") == model and r.get("prompt_sha") == {"generator": gsha, "solver": ssha}:
            return r
    return None
