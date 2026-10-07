"""N weeks of the full loop with the fictional family: draft → a named adult approves → after each meal, how much
was eaten and a rating → portions learn → next week. The family's reactions are simulated from their likes and
dislikes with a fixed seed, so a run is reproducible (NFR-6). Nothing here is real data.

What it reports is what the app's weekly report shows, plus the checks the eval cares about over time: every plan
free of the family's allergens, no unsafe dog extras, jobs fair over the window, and food left over falling as
portions learn.
"""
from __future__ import annotations

import datetime as dt
import random
import shutil
import time

from . import feedback, safety, store, week
from .catalog import get as get_catalog
from .config import Settings, load_household, work_root
from .feedback import EATEN


def _reaction(rng: random.Random, h, recipe: str, meal: str, learned: float) -> tuple[str, int]:
    """How the family reacts to one meal. Likes → eaten up and rated high; any dislike → left over and rated low;
    otherwise mostly eaten. Cooking more than they eat (portion factor > their appetite) leaves food over."""
    eaters = h.eaters(meal)
    liked = sum(recipe in p.likes for p in eaters)
    disliked = sum(recipe in p.dislikes for p in eaters)
    appetite = 0.88 + 0.04 * liked - 0.08 * disliked          # the share of a full portion they actually eat
    over = learned - appetite                                 # cooked minus eaten, as a share of a portion
    if disliked:
        eaten = "lots_left"
    elif over > 0.15 or rng.random() < 0.1:
        eaten = "some_left" if over < 0.35 else "lots_left"
    else:
        eaten = "all"
    base = 4 + (1 if liked else 0) - (2 if disliked else 0)
    rating = max(1, min(5, base + rng.choice([-1, 0, 0, 0, 1])))
    return eaten, rating


def run(weeks: int = 4, start: dt.date | None = None, seed: int = 7, fresh: bool = True,
        approver: str = "dana", choice: str = "balanced") -> dict:
    t0 = time.perf_counter()
    if fresh:
        shutil.rmtree(work_root() / "warehouse", ignore_errors=True)
    rng = random.Random(seed)
    h = load_household()
    s = Settings.load()
    c = get_catalog(h.info.get("region", "northeast-us"))
    start = start or dt.date(2026, 10, 5)
    out = []
    for n in range(weeks):
        wk = start + dt.timedelta(weeks=n)
        r = week.draft(wk, choice=choice, actor="simulation")
        unsafe = []
        for e in r.plan.entries:
            rec = c.recipes.get(e.recipe) or next((x for x in r.suggested if x.id == e.recipe), None)
            if rec is not None and not safety.recipe_for(c, rec, h.eaters(e.meal)).ok:
                unsafe.append(e.recipe)
        approve_seconds = rng.uniform(70, 130)                 # a person tapping through the week in the app
        week.approve(wk, approver, approve_seconds, choice)
        con = store.connect()
        sav = (store.get_week(con, wk.isoformat()) or {}).get("savings") or {}
        port = store.portions(con)
        left = []
        ratings = []
        for e in r.plan.entries:
            eaten, rating = _reaction(rng, h, e.recipe, e.meal, port.get(e.recipe, 1.0))
            feedback.record(con, wk.isoformat(), e.day, e.meal, e.recipe, eaten, rating, approver)
            left.append(1 - EATEN[eaten])
            ratings.append(rating)
        changed = feedback.learn(con, s, wk.isoformat())
        con.close()
        sp = r.split
        out.append({
            "week_of": wk.isoformat(), "status": r.plan.status, "meals": len(r.plan.entries),
            "total": sp.total, "stores": [f"{o.store_name} {o.mode}" for o in sp.orders],
            "dollars_saved": sav.get("dollars_saved"), "baseline": sav.get("baseline_dollars"),
            "minutes_saved": sav.get("minutes_saved"), "approve_seconds": round(approve_seconds),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "food_left_share": round(sum(left) / len(left), 3) if left else None,
            "portions_changed": len(changed), "unsafe_meals": unsafe,
            "dog_blocked": sum(len(p.blocked) for p in r.pets), "dog_extras": sum(len(p.extras) for p in r.pets),
            "chore_load": r.chore_load, "flags": r.flags, "model_cost_usd": round(r.cost_usd, 4),
            "plan_ms": r.ms,
        })
    con = store.connect()
    loads: dict[str, int] = {}
    for row in con.execute("SELECT person, SUM(load) AS l FROM loads GROUP BY person"):
        loads[row["person"]] = row["l"]
    con.close()
    saved = [w["dollars_saved"] for w in out if w["dollars_saved"] is not None]
    mins = [w["minutes_saved"] for w in out if w["minutes_saved"] is not None]
    adults = {k: v for k, v in loads.items() if k in h.people and not h.people[k].is_kid}
    return {
        "weeks": out,
        "summary": {
            "weeks": weeks,
            "dollars_saved_total": round(sum(saved), 2),
            "dollars_saved_per_week": round(sum(saved) / len(saved), 2) if saved else None,
            "minutes_saved_per_week": round(sum(mins) / len(mins), 1) if mins else None,
            "food_left_first_week": out[0]["food_left_share"] if out else None,
            "food_left_last_week": out[-1]["food_left_share"] if out else None,
            "avg_rating": round(sum(w["avg_rating"] for w in out if w["avg_rating"]) / max(1, len(out)), 2),
            "unsafe_meals": sum(len(w["unsafe_meals"]) for w in out),
            "dog_extras_blocked": sum(w["dog_blocked"] for w in out),
            "job_load_total": loads,
            "adult_load_gap": (max(adults.values()) - min(adults.values())) if len(adults) > 1 else 0,
            "model_cost_usd": round(sum(w["model_cost_usd"] for w in out), 4),
            "seconds": round(time.perf_counter() - t0, 1),
        },
    }
