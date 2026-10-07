"""One week, end to end: draft → (swap) → approve. Everything a person sees in the app comes from here.

draft:   confirmed specials + up to N new recipe ideas (checked) → meal plan (solver) → dog's week → shopping list →
         three ways to shop it (cheapest / balanced / fastest) → budget check → jobs rota → notes → savings.
swap:    a person swaps or bans one meal; every other meal is locked and the week re-solves around it.
approve: a named person approves (HITL-02); the meals go into history, the pantry is updated, and the hand-offs
         become available. Nothing is ever bought by Lil'Helper.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from . import ai, chores, feedback, pets, planner, savings, shopping, store, telemetry
from .catalog import Catalog, Recipe, get as get_catalog
from .config import DAYS, Household, Settings, load_household
from .prices import PriceBook, week_start

OPTIONS = {"cheapest": 0.0, "balanced": None, "fastest": 200.0}      # $/hour of your time; None = household value


@dataclass
class WeekResult:
    week_of: dt.date
    plan: planner.Plan
    pets: list[pets.PetWeek]
    items: list[shopping.Need]
    options: dict[str, shopping.Split]
    choice: str
    chores: list[chores.Assignment]
    chore_load: dict[str, int]
    notes: dict[tuple[str, str], str]
    savings: savings.Savings | None
    ideas: ai.IdeaResult | None
    flags: list[str]
    calls: list[ai.Call]
    cost_usd: float
    ms: int
    suggested: list[Recipe] = field(default_factory=list)

    @property
    def split(self) -> shopping.Split:
        return self.options[self.choice]

    def to_record(self) -> dict:
        return {"plan": self.plan.to_dict(),
                "split": {k: v.to_dict() for k, v in self.options.items()},
                "chores": [a.__dict__ for a in self.chores],
                "pets": [p.__dict__ for p in self.pets],
                "savings": self.savings.to_dict() if self.savings else None,
                "shopping_choice": self.choice}


def _specials_from_db(con, week_of: dt.date) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM specials WHERE week_of=?", (week_of.isoformat(),))]


def draft(week_of: dt.date, *, h: Household | None = None, s: Settings | None = None, ideas: bool = True,
          locks: dict | None = None, bans: dict | None = None, choice: str = "balanced",
          alias_overrides: dict | None = None, extra_specials: list[dict] | None = None,
          suggested: list[Recipe] | None = None, save: bool = True, actor: str = "planner") -> WeekResult:
    t0 = time.perf_counter()
    telemetry.require_enabled("plan")
    h = h or load_household()
    s = s or Settings.load()
    c: Catalog = get_catalog(h.info.get("region", "northeast-us"))
    week_of = week_start(week_of)
    con = store.connect()
    pb = PriceBook(h, week_of, extra_specials=_specials_from_db(con, week_of) + list(extra_specials or []))
    ctx = ai.AIContext.make(s, alias_overrides)
    flags: list[str] = []
    idea_res = None
    if suggested is None:
        suggested = []
        if ideas and int(h.raw.get("suggestions", {}).get("per_week", 0)) > 0:
            on_sp = sorted({sp["ingredient"] for sp in pb.specials})
            idea_res = ai.suggest_recipes(ctx, h, c, (week_of + dt.timedelta(days=3)).month, on_sp)
            suggested = idea_res.accepted
            flags += idea_res.flags
    hist = store.history(con)
    port = store.portions(con)
    budget = float(h.info.get("budget_per_week", 0)) or None
    plan = planner.plan_week(h, c, pb, s, extra=suggested, history=hist, portions=port, locks=locks, bans=bans)
    pantry = store.pantry(con)
    pw = pets.pet_week(h, c, plan, pantry, s)
    restock = {k: v for p in pw for k, v in p.restock.items()}
    items = shopping.needs(plan, c, pantry, restock) if plan.entries else []
    for e in plan.entries:                                   # suggested recipes aren't in the catalog's book
        if e.recipe.startswith("sugg_"):
            r = next(r for r in suggested if r.id == e.recipe)
            items = _add_recipe(items, c, r, e.servings, pantry)
    options = _options(h, c, pb, items, s)
    if budget and choice in options and options[choice].total > budget and plan.entries:
        # re-plan once with the food estimate scaled down by the overshoot, then keep whichever is cheaper
        scale = budget / options[choice].total
        tighter = planner.plan_week(h, c, pb, s, extra=suggested, history=hist, portions=port, locks=locks,
                                    bans=bans, budget=plan.est_food_cost * scale)
        if tighter.entries and "over_budget" not in tighter.flags:
            pw2 = pets.pet_week(h, c, tighter, pantry, s)
            items2 = shopping.needs(tighter, c, pantry, {k: v for p in pw2 for k, v in p.restock.items()})
            opts2 = _options(h, c, pb, items2, s)
            if opts2[choice].total < options[choice].total:
                plan, pw, items, options = tighter, pw2, items2, opts2
                flags.append("replanned_for_budget")
        if options[choice].total > budget:
            flags.append(f"over_budget_by_{options[choice].total - budget:.2f}")
    cooked = [d for d in DAYS if plan.at(d, "dinner")]
    rota, load, gaps = chores.rota(h, cooked, store.past_load(con, week_of.isoformat(),
                                                             int(h.raw.get("chores", {}).get("window_weeks", 4))))
    flags += [f"chores: {g}" for g in gaps]
    notes = ai.write_notes(ctx, h, plan) if plan.entries else {}
    prev = store.get_week(con, week_of.isoformat())
    approve_s = (prev or {}).get("approve_seconds") or 0
    sav = savings.compute(h, pb, items, options[choice], approve_s / 60, feedback.ratings(con, week_of.isoformat()),
                          feedback.ratings_before(con, week_of.isoformat())) if items else None
    res = WeekResult(week_of, plan, pw, items, options, choice, rota, load, notes, sav, idea_res,
                     sorted(set(flags + plan.flags)), ctx.calls, ctx.cost, int((time.perf_counter() - t0) * 1000),
                     suggested)
    if save:
        store.save_week(con, week_of.isoformat(), status="draft", locks={"locks": _k(locks), "bans": _k(bans)},
                        **res.to_record())
        store.audit(con, actor, "draft", {"week_of": week_of.isoformat(), "flags": res.flags})
    _log(res, h)
    con.close()
    return res


def _k(d: dict | None) -> dict:
    return {f"{k[0]}|{k[1]}": v for k, v in (d or {}).items()}


def _unk(d: dict | None) -> dict:
    return {tuple(k.split("|")): v for k, v in (d or {}).items()}


def _add_recipe(items, c, r: Recipe, servings: float, pantry) -> list:
    by = {n.ingredient: n for n in items}
    for iid, q in r.ing.items():
        if iid in by:
            by[iid].qty = round(by[iid].qty + q * servings, 3)
        else:
            left = q * servings - pantry.get(iid, 0)
            if left > 0:
                ing = c.ingredients[iid]
                by[iid] = shopping.Need(iid, ing.name, round(left, 3), ing.unit, [r.name])
    return sorted(by.values(), key=lambda n: (c.ingredients[n.ingredient].aisle, n.name))


def _options(h, c, pb, items, s) -> dict[str, shopping.Split]:
    out = {}
    base_value = h.info.get("time_value_per_hour", 20)
    for name, tv in OPTIONS.items():
        h.raw["household"]["time_value_per_hour"] = base_value if tv is None else tv
        out[name] = shopping.split(h, c, pb, items, s)
    h.raw["household"]["time_value_per_hour"] = base_value
    return out


def swap(week_of: dt.date, day: str, meal: str, *, to: str | None = None, actor: str = "person", **kw) -> WeekResult:
    """Lock every other meal; for this slot either use `to` or ban the current recipe. The rest re-solves."""
    con = store.connect()
    w = store.get_week(con, week_start(week_of).isoformat())
    con.close()
    if not w:
        raise ValueError("no draft for that week")
    locks = {(e["day"], e["meal"]): e["recipe"] for e in w["plan"]["entries"] if (e["day"], e["meal"]) != (day, meal)}
    prev = _unk((w.get("locks") or {}).get("bans"))
    current = next((e["recipe"] for e in w["plan"]["entries"] if (e["day"], e["meal"]) == (day, meal)), None)
    bans = {k: list(v) for k, v in prev.items()}
    if to:
        locks[(day, meal)] = to
    elif current:
        bans.setdefault((day, meal), []).append(current)
    return draft(week_of, locks=locks, bans=bans, ideas=False, actor=actor, **kw)


def approve(week_of: dt.date, person: str, seconds: float, choice: str = "balanced") -> dict:
    """A named person approves the week (HITL-02). History, pantry and the hand-offs follow from this."""
    h = load_household()
    c = get_catalog(h.info.get("region", "northeast-us"))
    con = store.connect()
    wk = week_start(week_of).isoformat()
    w = store.get_week(con, wk)
    if not w:
        raise ValueError("no draft for that week")
    if person not in h.people or h.people[person].is_kid:
        raise PermissionError("only an adult in the household can approve a week")
    split = w["split"][choice]
    pantry = store.pantry(con)
    for o in split["orders"]:
        for ln in o["lines"]:
            pantry[ln["ingredient"]] = pantry.get(ln["ingredient"], 0) + ln["packs"] * ln["pack"]
    for e in w["plan"]["entries"]:
        r = c.recipes.get(e["recipe"])
        if r:
            for iid, q in r.ing.items():
                pantry[iid] = pantry.get(iid, 0) - q * e["servings"]
        date = dt.date.fromisoformat(wk) + dt.timedelta(days=DAYS.index(e["day"]))
        con.execute("INSERT INTO history VALUES (?,?)", (e["recipe"], date.isoformat()))
    for p in h.pets.values():
        pantry[p.food["ingredient"]] = pantry.get(p.food["ingredient"], 0) - p.food["cups_per_day"] * 7
        pantry["dog_treats"] = pantry.get("dog_treats", 0) - p.treats_per_day * 7
    store.set_pantry(con, pantry)
    load: dict[str, int] = {}
    for a in w.get("chores") or []:
        load[a["person"]] = load.get(a["person"], 0) + chores.WEIGHT.get(a["job"], 1)
    con.executemany("INSERT OR REPLACE INTO loads VALUES (?,?,?)", [(p, wk, l) for p, l in load.items()])
    sav = dict(w.get("savings") or {})
    if sav:                                    # time saved uses the minutes this person actually spent approving
        sav["planning_after"] = round(seconds / 60, 1)
        sav["minutes_saved"] = round((sav["planning_before"] - seconds / 60) +
                                     (sav["baseline_minutes"] - split["minutes"]), 1)
    store.save_week(con, wk, status="approved", approved_by=person, approved_at=store.now(), approve_seconds=seconds,
                    shopping_choice=choice, savings=sav or None)
    store.audit(con, person, "approve", {"week_of": wk, "choice": choice, "total": split["total"],
                                         "orders": [(o["store"], o["mode"], o["total"]) for o in split["orders"]]})
    telemetry.emit("approve", actor=person, records_in=len(w["plan"]["entries"]), records_out=len(split["orders"]),
                   detail={"choice": choice, "total": split["total"], "seconds": round(seconds)})
    con.close()
    return {"week_of": wk, "approved_by": person, "choice": choice, "total": split["total"]}


def _log(res: WeekResult, h: Household) -> None:
    sp = res.split
    rec = {"event": "draft", "week_of": res.week_of.isoformat(), "status": res.plan.status, "flags": res.flags,
           "meals": len(res.plan.entries), "items": len(res.items), "total": sp.total, "minutes": sp.minutes,
           "stores": [o.store for o in sp.orders], "solve_ms": res.plan.solve_ms + sp.solve_ms, "ms": res.ms,
           "cost_usd": res.cost_usd, "calls": [c.__dict__ for c in res.calls],
           "ideas_accepted": len(res.ideas.accepted) if res.ideas else 0,
           "ideas_rejected": len(res.ideas.rejected) if res.ideas else 0}
    store.runlog(rec)
    models = sorted({c.model for c in res.calls})
    telemetry.emit("plan", status="ok" if res.plan.entries else "failed", model=",".join(models),
                   input_tokens=sum(c.input_tokens for c in res.calls),
                   output_tokens=sum(c.output_tokens for c in res.calls), cost_usd=res.cost_usd, latency_ms=res.ms,
                   records_in=len(res.plan.entries), records_out=len(res.items), flags=res.flags,
                   detail={"total": sp.total, "minutes": sp.minutes, "stores": len(sp.orders),
                           "dollars_saved": res.savings.dollars_saved if res.savings else None,
                           "ideas_rejected": rec["ideas_rejected"]})
