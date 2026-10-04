"""The generator agent loop, the daily choice of track/kind/difficulty, reserves, escalation and packs.

    choose(day) → generator writes a draft → verifier (verify.py) → PUBLISH, or feed the reasons back and try again
    (generation.max_rounds) → still failing: store the drafts as `escalated` for the operator (HITL-02) and schedule a
    pre-verified reserve puzzle instead, so the day still gets a puzzle with no one awake.
"""
from __future__ import annotations

import hashlib
import json
import random
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from . import assets as assets_mod
from . import grading, puzzles, telemetry, verify
from .config import WEEKDAYS, Settings
from .store import log_job, now, puzzles as P, reviews


# ---------------------------------------------------------------- what to make today
def choose(day: date, s: Settings) -> tuple[str, str, str]:
    """(track, kind, difficulty) for a day, from config/puzzles.yaml. Deterministic per day."""
    cfg = s.puzzles
    rng = random.Random(f"choose:{day.isoformat()}")
    enabled = s.enabled_tracks()
    wd = WEEKDAYS[day.weekday()]
    track = (cfg["rotation"].get("weekday") or {}).get(wd, "random") if cfg["rotation"]["mode"] == "weekday" else "random"
    if track == "random" or track not in enabled:
        weights = [float(s.track(t).get("weight", 1)) for t in enabled]
        track = rng.choices(enabled, weights=weights)[0]
    kind = rng.choice(s.track(track)["kinds"])
    diff = (cfg["difficulty"].get("by_track") or {}).get(track) or cfg["difficulty"]["weekday"].get(wd, "medium")
    return track, kind, diff


def window(day: date, s: Settings) -> tuple[datetime, datetime]:
    w = s.puzzles["window"]
    tz = ZoneInfo(w["timezone"])
    at = lambda hm: datetime.combine(day, datetime.strptime(hm, "%H:%M").time(), tz).astimezone(timezone.utc)  # noqa: E731
    return at(w["open_at"]), at(w["close_at"])           # stored in UTC (SQLite keeps no time zone)


# ---------------------------------------------------------------- the agent loop
def generate_one(ctx: verify.Ctx, track: str, kind: str, difficulty: str, seed: int,
                 scenario: str | None = None, every_round: bool = False) -> tuple[dict | None, verify.Report, list[dict]]:
    """Up to max_rounds drafts; returns the first that passes, else the last one, plus every round's report."""
    s = ctx.s
    system, sha = verify.prompt(s, "generator_prompt")
    allowed = {a["id"]: a["files"] for a in s.puzzles["data_sources"]["assets"]}
    system = system.format(assets=json.dumps(allowed))
    rounds: list[dict] = []
    feedback: list[str] = []
    d, rep = None, verify.Report()
    for r in range(int(s.puzzles["generation"]["max_rounds"])):
        req = {"track": track, "kind": kind, "difficulty": difficulty, "seed": seed * 10 + r,
               "target_solve_rate": s.puzzles["difficulty"]["target_solve_rate"].get(difficulty),
               "problems_with_previous_draft": feedback}
        if scenario and (r == 0 or every_round):
            req["scenario"] = scenario               # evals / operator demo only: force known-bad drafts
        try:
            res = verify.call_model(ctx, "generator", s["llm"]["generator_alias"], system,
                                    f"<request>{json.dumps(req)}</request>", sha)
            raw = res.text
        except Exception as e:  # noqa: BLE001 — budget or provider failure: stop and escalate
            rep = verify.Report()
            rep.step("generator", False, f"{type(e).__name__}: {str(e)[:160]}")
            rounds.append({"round": r + 1, **rep.as_dict()})
            break
        d, rep = verify.verify(raw, ctx)
        rounds.append({"round": r + 1, **rep.as_dict()})
        if rep.decision == "PUBLISH":
            break
        feedback = rep.reasons
    return d, rep, rounds


def store_puzzle(conn, s: Settings, d: dict, rep: verify.Report | dict, *, status: str, source: str,
                 day: str | None = None, run_id: str = "", pack_id: str | None = None, models: tuple = ("", ""),
                 prompt_sha: str = "") -> int:
    salt = secrets.token_hex(8)
    forms = list(dict.fromkeys([d["answer"], *d.get("accepted_forms", [])]))
    st, fp = verify.fingerprints(d)
    opens = closes = None
    if day:
        opens, closes = window(date.fromisoformat(day), s)
    report = rep.as_dict() if isinstance(rep, verify.Report) else rep
    res = conn.execute(P.insert().values(
        day=day, track=d["track"], kind=d["kind"], difficulty=d["difficulty"], title=d["title"],
        statement=d["statement"], starter=d.get("starter") or "",
        assets=[{**a, "revision": a.get("revision") or assets_mod.revision(a["id"])}
                for a in d.get("assets", [])],
        learning_objective=d.get("learning_objective") or "", skill_tags=d.get("skill_tags") or [],
        answer_format=d.get("answer_format") or "", answer_type=d["answer_type"], decimals=d.get("decimals"),
        salt=salt, answer_hashes=grading.key_hashes(salt, forms, d["answer_type"], d.get("decimals")),
        sealed_key=grading.seal({"answer": d["answer"], "forms": forms, "solution": d.get("solution", ""),
                                 "code": d.get("reference_code", "")}),
        status=status, source=source, opens_at=opens, closes_at=closes, verification=report,
        statement_hash=st, answer_fingerprint=fp, generator_model=models[0], solver_model=models[1],
        prompt_sha=prompt_sha, run_id=run_id, pack_id=pack_id, created_at=now()))
    return res.inserted_primary_key[0]


def _models(ctx: verify.Ctx) -> tuple[str, str]:
    reg = ctx.client.registry
    return reg.name_of(ctx.s["llm"]["generator_alias"]), reg.name_of(ctx.s["llm"]["solver_alias"])


def _record(ctx: verify.Ctx, action: str, status: str, items: int, t0: float, flags: list[str], detail: dict) -> None:
    telemetry.record(action, actor="scheduler", status=status, run_id=ctx.run_id, model=",".join(sorted(ctx.models)),
                     input_tokens=ctx.tokens_in, output_tokens=ctx.tokens_out, cost_usd=ctx.cost,
                     latency_ms=int((time.perf_counter() - t0) * 1000), items=items, rows_in=ctx.calls,
                     flags=flags, detail=detail)


def model_warnings(s: Settings) -> list[str]:
    reg = verify.make_client(s).registry
    g, v = reg.name_of(s["llm"]["generator_alias"]), reg.name_of(s["llm"]["solver_alias"])
    if s.puzzles["generation"].get("require_distinct_models") and g == v:
        return [f"generator and solver are the same model ({g}): the solver can't catch the generator's blind spots"]
    return []


# ---------------------------------------------------------------- daily
def daily(conn, s: Settings, day: date, scenario: str | None = None, kind: str | None = None,
          every_round: bool = False) -> dict:
    """Generate and verify the puzzle for `day`; escalate and fall back to a reserve puzzle if it can't be verified."""
    telemetry.require_enabled("generate", actor="scheduler")
    t0 = time.perf_counter()
    ctx = verify.Ctx(s, verify.make_client(s), conn, purpose="daily")
    track, chosen, diff = choose(day, s)
    if kind:                                         # operator demo: force a kind (e.g. to try a break-it case)
        from .puzzles import KINDS
        track, chosen = KINDS[kind]["track"], kind
    kind = chosen
    seed = int(hashlib.sha256(day.isoformat().encode()).hexdigest()[:8], 16)
    d, rep, rounds = generate_one(ctx, track, kind, diff, seed, scenario, every_round)
    _, sha = verify.prompt(s, "generator_prompt")
    out = {"day": day.isoformat(), "track": track, "kind": kind, "difficulty": diff, "rounds": len(rounds),
           "run_id": ctx.run_id, "cost_usd": round(ctx.cost, 6)}
    if rep.decision == "PUBLISH":
        pid = store_puzzle(conn, s, d, rep, status="scheduled", source="generated", day=day.isoformat(),
                           run_id=ctx.run_id, models=_models(ctx), prompt_sha=sha)
        log_job(conn, "generate", day.isoformat(), "ok", {**out, "puzzle_id": pid})
        _record(ctx, "generate", "ok", 1, t0, [], out)
        return {**out, "status": "published", "puzzle_id": pid, "report": rep.as_dict()}
    # escalate: keep the failed draft for the operator, publish a reserve puzzle instead
    esc_id = None
    if d:
        esc_id = store_puzzle(conn, s, d, {"rounds": rounds, **rep.as_dict()}, status="escalated", source="generated",
                              run_id=ctx.run_id, models=_models(ctx), prompt_sha=sha)
    flags = sorted({f for r in rounds for f in r.get("flags", [])} | {"escalated"})
    res_id = use_reserve(conn, s, day, track)
    from . import mailer
    mailer.escalation(conn, s, day.isoformat(), esc_id, rounds, res_id)
    log_job(conn, "generate", day.isoformat(), "escalated", {**out, "escalated_id": esc_id, "reserve_id": res_id})
    _record(ctx, "generate", "escalated", 1 if res_id else 0, t0, flags, {**out, "reserve_used": bool(res_id)})
    return {**out, "status": "escalated", "puzzle_id": res_id, "escalated_id": esc_id, "rounds_detail": rounds}


def use_reserve(conn, s: Settings, day: date, track: str) -> int | None:
    """Schedule a pre-verified reserve puzzle for the day (same track if one is left, else any enabled track)."""
    enabled = s.enabled_tracks()
    q = select(P.c.id, P.c.track).where(P.c.status == "reserve", P.c.track.in_(enabled)).order_by(P.c.id)
    rows = conn.execute(q).all()
    pick = next((r for r in rows if r.track == track), rows[0] if rows else None)
    if not pick:
        return None
    opens, closes = window(day, s)
    conn.execute(update(P).where(P.c.id == pick.id).values(day=day.isoformat(), status="scheduled",
                                                           opens_at=opens, closes_at=closes))
    return pick.id


def build_reserve(conn, s: Settings, per_track: int = 3, seed: int = 1) -> list[int]:
    """Pre-verified spare puzzles for days the generator can't produce one. Run once at setup and when low."""
    telemetry.require_enabled("reserve", actor="scheduler")
    t0 = time.perf_counter()
    ctx = verify.Ctx(s, verify.make_client(s, max_usd=s["cost"]["max_usd_per_run"] * per_track * 5), conn,
                     purpose="reserve")
    _, sha = verify.prompt(s, "generator_prompt")
    ids = []
    for t in s.enabled_tracks():
        have = conn.execute(select(P.c.id).where(P.c.status == "reserve", P.c.track == t)).all()
        kinds = s.track(t)["kinds"]
        for i in range(max(0, per_track - len(have))):
            d, rep, _ = generate_one(ctx, t, kinds[i % len(kinds)], "medium", seed * 1000 + i + len(have) * 7)
            if rep.decision == "PUBLISH":
                ids.append(store_puzzle(conn, s, d, rep, status="reserve", source="reserve", run_id=ctx.run_id,
                                        models=_models(ctx), prompt_sha=sha))
    log_job(conn, "reserve", "", "ok", {"added": len(ids)})
    _record(ctx, "reserve", "ok", len(ids), t0, [], {"added": len(ids)})
    return ids


def review(conn, puzzle_id: int, reviewer: str, decision: str, note: str = "") -> None:
    """HITL-02: the operator approves an escalated draft (it joins the reserve) or rejects it. Named reviewer."""
    if decision not in ("approve", "reject") or not reviewer.strip():
        raise ValueError("decision must be approve/reject and the reviewer must be named")
    telemetry.require_enabled("review", actor=reviewer)
    row = conn.execute(select(P.c.status).where(P.c.id == puzzle_id)).first()
    if not row or row.status != "escalated":
        raise ValueError(f"puzzle {puzzle_id} is not waiting for review")
    conn.execute(update(P).where(P.c.id == puzzle_id).values(status="reserve" if decision == "approve" else "rejected",
                                                             source="reserve" if decision == "approve" else "generated"))
    conn.execute(reviews.insert().values(puzzle_id=puzzle_id, reviewer=reviewer.strip()[:80], decision=decision,
                                         note=note[:2000], at=now()))
    telemetry.record("review", actor=reviewer, status="ok", items=1, detail={"decision": decision})


# ---------------------------------------------------------------- one-off packs
def pack(conn, s: Settings, count: int, tracks: list[str] | str = "random", difficulty: str = "mixed",
         seed: int | None = None, actor: str = "operator") -> dict:
    """Generate and verify `count` new puzzles (FR-7). They are stored as `pack` puzzles: never daily, never scored."""
    telemetry.require_enabled("pack", actor=actor)
    cfg = s.puzzles["packs"]
    count = max(1, min(int(count), int(cfg["max_puzzles"])))
    seed = seed if seed is not None else secrets.randbelow(10**6)
    rng = random.Random(f"pack:{seed}")
    enabled = s.enabled_tracks()
    chosen = [t for t in (tracks if isinstance(tracks, list) else []) if t in enabled] or enabled
    t0 = time.perf_counter()
    ctx = verify.Ctx(s, verify.make_client(s, max_usd=s["cost"]["max_usd_per_run"] * count * 2), conn, purpose="pack")
    _, sha = verify.prompt(s, "generator_prompt")
    pack_id = f"pk{seed}-{uuid.uuid4().hex[:6]}"
    ids, dropped = [], []
    for i in range(count):
        t = chosen[i % len(chosen)] if tracks != "random" else rng.choice(chosen)
        k = rng.choice(s.track(t)["kinds"])
        diff = difficulty if difficulty in ("easy", "medium", "hard") else rng.choice(["easy", "medium", "hard"])
        d, rep, rounds = generate_one(ctx, t, k, diff, seed * 100 + i)
        if rep.decision == "PUBLISH":
            ids.append(store_puzzle(conn, s, d, rep, status="pack", source="pack", pack_id=pack_id, run_id=ctx.run_id,
                                    models=_models(ctx), prompt_sha=sha))
        else:
            dropped.append({"track": t, "kind": k, "reasons": rep.reasons[:3]})
    out = {"pack_id": pack_id, "seed": seed, "puzzle_ids": ids, "dropped": dropped, "cost_usd": round(ctx.cost, 6),
           "actor": actor}
    log_job(conn, "pack", "", "ok", out)
    _record(ctx, "pack", "ok", len(ids), t0, ["dropped"] if dropped else [], {"requested": count, "made": len(ids)})
    return out
