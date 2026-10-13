"""Choose the week's meals with a constraint solver (OR-Tools CP-SAT).

Hard rules: allergies of anyone in the house and diets of everyone eating (safety.py), one recipe per slot, no recipe
twice in a week, no dinner repeated within `no_repeat_days`, hands-on minutes within each day's limit (batch recipes
may be cooked on the batch day instead), a household recipe only in its season and no more often than wanted, the
cost per serving under the household's maximum, a "leftovers" night fed by one earlier dinner cooked double,
health targets, and the household's required styles ("one pot on Mondays", "something a kid can make on Leo's night").
Soft (the objective, in cents): estimated ingredient cost + penalties for dislikes, out-of-season produce and
servings under the cost minimum − rewards for likes, in-season produce, specials, preferred styles, a household
recipe that's due again, and dinners that reheat well for tomorrow's lunch.

A model never chooses here. If a rule can't be met, the plan says which and by how much instead of quietly dropping it.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from . import safety
from .catalog import Catalog, Recipe
from .config import DAYS, Household, Settings
from .prices import PriceBook

CENTS = 100
MEAL_ORDER = ["breakfast", "lunch", "leftovers", "dinner"]
DAY_NAME = dict(zip(DAYS, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))


@dataclass
class Entry:
    day: str
    meal: str
    recipe: str
    name: str
    servings: float
    est_cost: float
    active: int
    prep_day: str
    double: bool = False                 # cooked double to feed a leftovers night
    why: list[str] = field(default_factory=list)
    eaters: list[str] = field(default_factory=list)
    kind: str = "cook"                   # cook | leftovers (a lunch from last night's dinner) | freezer
    cook: str | None = None              # a kid chef's id on their night
    to_freeze: float = 0.0               # extra portions cooked to freeze for a later night

    @property
    def per_serving(self) -> float:
        return round(self.est_cost / self.servings, 2) if self.servings else 0.0


@dataclass
class Plan:
    week_of: dt.date
    entries: list[Entry]
    special_nights: dict[str, str]
    flags: list[str]
    est_food_cost: float
    status: str
    solve_ms: int
    rejected: dict[str, list[str]]       # recipe → why it couldn't be used this week
    health: dict[str, float]
    unmet: list[str] = field(default_factory=list)

    def at(self, day: str, meal: str) -> Entry | None:
        return next((e for e in self.entries if e.day == day and e.meal == meal), None)

    def to_dict(self) -> dict:
        return {"week_of": self.week_of.isoformat(), "status": self.status, "flags": self.flags,
                "est_food_cost": self.est_food_cost, "special_nights": self.special_nights,
                "entries": [{**e.__dict__, "per_serving": e.per_serving} for e in self.entries],
                "health": self.health, "unmet": self.unmet, "rejected": self.rejected, "solve_ms": self.solve_ms}


def servings_for(h: Household, meal: str, recipe: str, portions: dict[str, float], day: str | None = None) -> float:
    return round(sum(p.portion for p in h.eaters(meal, day)) * portions.get(recipe, 1.0), 2)


def est_cost(r: Recipe, servings: float, pb: PriceBook) -> float:
    total = 0.0
    for iid, q in r.ing.items():
        u = pb.best_unit(iid)
        total += (u or 0) * q * servings
    return total


def _rules(h: Household, day: str, meal: str) -> tuple[list[str], list[str]]:
    """Tags this slot must have, and tags it should prefer: the meal's style, plus the day's style for dinner."""
    req = list(h.styles(meal).get("require", []))
    pref = list(h.styles(meal).get("prefer", []))
    if meal == "dinner":
        req += h.styles(day).get("require", [])
        pref += h.styles(day).get("prefer", [])
    return req, pref


def times_had(history_dates: dict[str, list[dt.date]], rid: str, since: dt.date) -> int:
    return sum(1 for d in history_dates.get(rid, []) if d >= since)


def candidates(h: Household, c: Catalog, pb: PriceBook, extra: list[Recipe], history: dict[str, dt.date],
               week_of: dt.date, portions: dict[str, float] | None = None,
               history_all: dict[str, list[dt.date]] | None = None
               ) -> tuple[dict[tuple[str, str], list[Recipe]], dict[str, list[str]], list[str]]:
    rejected: dict[str, list[str]] = {}
    notes: list[str] = []
    pool = list(c.recipes.values()) + [r for r in extra if r.id not in c.recipes]
    no_repeat = int(h.raw.get("health", {}).get("no_repeat_days", 0))
    batch_day = h.raw.get("batch_day")
    kid_chef = h.kid_chef()
    house = h.everyone_allergies()
    month = (week_of + dt.timedelta(days=3)).month
    history_all = history_all or {}
    out: dict[tuple[str, str], list[Recipe]] = {}
    for day, meal in h.slots():
        date = week_of + dt.timedelta(days=DAYS.index(day))
        eaters = h.eaters(meal, day)
        lo, hi = h.cost_range(meal)
        ok = []
        too_dear = []
        for r in pool:
            if r.meal != meal:
                continue
            v = safety.recipe_for(c, r, eaters, house)
            if not v.ok:
                rejected.setdefault(r.id, v.reasons)
                continue
            missing = [i for i in r.ing if not pb.sold_anywhere(i)]
            if missing:
                rejected.setdefault(r.id, [f"not sold at your stores this week: {', '.join(missing)}"])
                continue
            if r.season_months and month not in r.season_months:
                rejected.setdefault(r.id, ["out of its season"])
                continue
            if r.want.get("times"):
                window = int(r.want.get("per_weeks", 4)) * 7
                if times_had(history_all, r.id, date - dt.timedelta(days=window)) >= int(r.want["times"]):
                    rejected.setdefault(r.id, [f"had it {r.want['times']}× in {window // 7} weeks, as often as wanted"])
                    continue
            last = history.get(r.id)
            if meal == "dinner" and last and (date - last).days < no_repeat:
                rejected.setdefault(r.id, [f"had it {(date - last).days} days before"])
                continue
            limit = h.prep_limit(day)
            if r.active > limit and not (r.has("batch") and batch_day and r.active <= h.prep_limit(batch_day)
                                         and DAYS.index(batch_day) != DAYS.index(day)):
                continue                                   # too long for this day (not a reason to reject overall)
            if hi is not None:
                serv = servings_for(h, meal, r.id, portions or {}, day)
                if serv and est_cost(r, serv, pb) / serv > hi:
                    too_dear.append(r)
                    continue
            ok.append(r)
        if not ok and too_dear:
            ok = too_dear
            notes.append(f"{day} {meal}: nothing fits under ${hi:.2f} a serving, so the cheapest options were used")
        req, _ = _rules(h, day, meal)
        if meal == "dinner" and day in kid_chef:
            kid = h.people[kid_chef[day]]
            fit = [r for r in ok if r.has("kid_can_make") and 0 < r.kid_min_age <= kid.years]
            if fit:
                ok = fit
            else:
                notes.append(f"kid chef {day}: nothing on the list is easy enough for their age, so an adult cooks")
        if req:
            fit = [r for r in ok if all(r.has(t) for t in req)]
            if fit:
                ok = fit
            else:
                notes.append(f"{day} {meal}: no recipe is {' + '.join(req)}, so that rule was relaxed")
        out[(day, meal)] = ok
    return out, rejected, notes


def plan_week(h: Household, c: Catalog, pb: PriceBook, s: Settings, *, extra: list[Recipe] | None = None,
              history: dict[str, dt.date] | None = None, portions: dict[str, float] | None = None,
              locks: dict[tuple[str, str], str] | None = None, bans: dict[tuple[str, str], list[str]] | None = None,
              budget: float | None = None, history_all: dict[str, list[dt.date]] | None = None) -> Plan:
    t0 = time.perf_counter()
    extra, history, portions = extra or [], history or {}, portions or {}
    locks, bans = locks or {}, bans or {}
    week_of = pb.week_of
    w = s["planner"]["weights"]
    health = h.raw.get("health", {})
    month = (week_of + dt.timedelta(days=3)).month
    cands, rejected, style_notes = candidates(h, c, pb, extra, history, week_of, portions, history_all)
    special = h.special_nights()
    batch_day = h.raw.get("batch_day")
    lunch_from = h.leftover_lunches()                    # lunch day → dinner day that feeds it
    feeds_lunch = {v: k for k, v in lunch_from.items()}  # dinner day → lunch day
    pool = {r.id: r for r in list(extra)}
    rec = lambda rid: c.recipes.get(rid) or pool[rid]

    def build(hard_health: bool, cap_cents: int | None):
        m = cp_model.CpModel()
        x: dict[tuple[str, str, str], cp_model.IntVar] = {}
        cost_terms, obj = [], []
        info: dict[tuple[str, str, str], tuple[float, float, list[str]]] = {}
        for (day, meal), rs in cands.items():
            rs = [r for r in rs if r.id not in bans.get((day, meal), [])]
            if (day, meal) in locks:
                rs = [r for r in rs if r.id == locks[(day, meal)]] or rs
            if not rs:
                return None
            vs = []
            date = week_of + dt.timedelta(days=DAYS.index(day))
            lo, _ = h.cost_range(meal)
            for r in rs:
                pool.setdefault(r.id, r)
                v = m.NewBoolVar(f"x_{day}_{meal}_{r.id}")
                x[(day, meal, r.id)] = v
                vs.append(v)
                serv = servings_for(h, meal, r.id, portions, day)
                cost = est_cost(r, serv, pb)
                eaters = h.eaters(meal, day)
                why = []
                score = 0.0
                likes = [p for p in eaters if r.id in p.likes]
                dislikes = [p for p in eaters if r.id in p.dislikes]
                score += w["liked"] * len(likes) + w["disliked"] * len(dislikes)
                if likes:
                    why.append("a favourite")
                ins, outs = c.season_score(r, month)
                score += w["in_season"] * ins + w["out_of_season"] * outs
                if ins:
                    why.append("in season")
                specials = sum(1 for i in r.ing if pb.on_special(i))
                score += w["on_special"] * specials
                if specials:
                    why.append(f"{specials} on special")
                kids = sum(1 for p in eaters if p.is_kid)
                if r.has("kid_friendly") and kids:
                    score += w.get("kid_friendly", -1.0) * kids
                if r.source == "suggested":
                    score += w["new_suggestion"]
                    why.append("new idea")
                if r.source == "household":
                    score += w.get("household_recipe", -2.0)
                    if r.want.get("times"):
                        window = int(r.want.get("per_weeks", 4)) * 7
                        if times_had(history_all or {}, r.id, date - dt.timedelta(days=window)) < int(r.want["times"]):
                            score += w.get("household_due", -4.0)
                            why.append("due again")
                _, pref = _rules(h, day, meal)
                matched = [t for t in pref if r.has(t)]
                if matched:
                    score += w.get("style_prefer", -1.5) * len(matched)
                    why.append(", ".join(t.replace("_", " ") for t in matched))
                if meal == "dinner" and day in feeds_lunch and r.has("leftovers") and h.leftover_eaters():
                    score += w.get("leftovers_for_lunch", -1.0)
                    why.append("reheats well for tomorrow's lunch")
                if lo is not None and serv and cost / serv < lo:
                    score += w.get("under_cost_min", 1.0) * (lo - cost / serv) * serv
                info[(day, meal, r.id)] = (serv, cost, why)
                cost_terms.append(int(round(cost * CENTS)) * v)
                obj.append(int(round((cost + score) * CENTS)) * v)
            m.AddExactlyOne(vs)
        # no recipe twice in a week
        by_recipe: dict[str, list] = {}
        for (day, meal, rid), v in x.items():
            by_recipe.setdefault(rid, []).append(v)
        for vs in by_recipe.values():
            m.Add(sum(vs) <= 1)
        # leftovers nights: one earlier leftovers-tagged dinner is cooked double
        dbl: dict[tuple[str, str], cp_model.IntVar] = {}
        for night, kind in special.items():
            if kind != "leftovers" or not s["planner"].get("leftovers_cover_night", True):
                continue
            opts = []
            for (day, meal, rid), v in x.items():
                if meal == "dinner" and DAYS.index(day) < DAYS.index(night) and rec(rid).has("leftovers"):
                    d = m.NewBoolVar(f"dbl_{day}_{rid}")
                    m.AddImplication(d, v)
                    dbl[(day, rid)] = d
                    opts.append(d)
                    serv, cost, _ = info[(day, meal, rid)]
                    cost_terms.append(int(round(cost * CENTS)) * d)
                    obj.append(int(round(cost * CENTS)) * d)
            if opts:
                m.AddExactlyOne(opts)
        # health targets over dinners
        dinners = [(k, v) for k, v in x.items() if k[1] == "dinner"]
        n_dinners = len({(d, ml) for (d, ml, _) in x if ml == "dinner"})
        targets = {
            "fried": (sum(v for k, v in dinners if rec(k[2]).has("fried")), "<=", health.get("max_fried_per_week")),
            "processed": (sum(v for k, v in x.items() if rec(k[2]).has("processed")), "<=",
                          health.get("max_processed_per_week")),
            "fish": (sum(v for k, v in dinners if c.is_fish(rec(k[2]))), ">=", health.get("min_fish_per_week")),
            "vegetarian": (sum(v for k, v in dinners if c.is_vegetarian(rec(k[2]))), ">=",
                           health.get("min_vegetarian_per_week")),
            "veg_servings": (sum(int(rec(k[2]).veg * 10) * v for k, v in dinners), ">=",
                             int(health["min_veg_per_dinner"] * 10 * n_dinners) if health.get("min_veg_per_dinner") else None),
        }
        slack_vars = {}
        for name, (expr, op, target) in targets.items():
            if target is None or (isinstance(expr, int) and expr == 0 and op == ">="):
                continue
            if hard_health:
                m.Add(expr <= target) if op == "<=" else m.Add(expr >= target)
            else:
                sl = m.NewIntVar(0, 1000, f"slack_{name}")
                slack_vars[name] = sl
                m.Add(expr - sl <= target) if op == "<=" else m.Add(expr + sl >= target)
                obj.append(5000 * sl)                       # $50 per unit missed: only when there's no other way
        if cap_cents is not None:
            m.Add(sum(cost_terms) <= cap_cents)
        m.Minimize(sum(obj))
        return m, x, dbl, info, slack_vars, cost_terms

    def solve(hard_health: bool, cap: int | None):
        built = build(hard_health, cap)
        if built is None:
            return None, None
        m, x, dbl, info, slack, _ = built
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(s["planner"]["solver_seconds"])
        solver.parameters.num_workers = 1                # one worker: the same plan every run (reproducible)
        solver.parameters.random_seed = 1
        st = solver.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, solver.StatusName(st)
        return (solver, x, dbl, info, slack), solver.StatusName(st)

    flags: list[str] = []
    cap = int(budget * CENTS) if budget else None
    res, status = solve(True, cap)
    if res is None and cap is not None:
        res2, _ = solve(True, None)
        if res2 is not None:
            flags.append("over_budget")
            res, status = res2, "OVER_BUDGET"
    if res is None:
        res, status = solve(False, None)
        flags.append("health_targets_relaxed")
    if res is None:
        return Plan(week_of, [], special, ["no_plan"] + style_notes, 0.0, "INFEASIBLE",
                    int((time.perf_counter() - t0) * 1000), rejected, {},
                    ["no recipe fits one of the meals — add recipes or relax a rule"])
    solver, x, dbl, info, slack = res
    entries: list[Entry] = []
    for (day, meal, rid), v in x.items():
        if solver.Value(v):
            r = rec(rid)
            serv, cost, why = info[(day, meal, rid)]
            double = bool(dbl.get((day, rid)) is not None and solver.Value(dbl[(day, rid)]))
            limit = h.prep_limit(day)
            prep_day = batch_day if (r.active > limit and batch_day) else day
            if double:
                serv, cost = serv * 2, cost * 2
                why = why + [f"cooked double for {', '.join(n for n, k in special.items() if k == 'leftovers')} leftovers"]
            if prep_day != day:
                why = why + [f"prep on {prep_day}"]
            entries.append(Entry(day, meal, rid, r.name, round(serv, 2), round(cost, 2), r.active, prep_day, double,
                                 why, [p.id for p in h.eaters(meal, day)]))
    extra_p = h.extra_portions()
    kid_chef = h.kid_chef()
    for e in entries:
        if e.meal != "dinner":
            continue
        r = rec(e.recipe)
        if extra_p:
            per = e.est_cost / e.servings if e.servings else 0
            e.servings, e.est_cost = round(e.servings + extra_p, 2), round(e.est_cost + per * extra_p, 2)
            e.why.append(f"{extra_p:g} spare portion{'s' if extra_p != 1 else ''}")
        if e.day in kid_chef and r.has("kid_can_make") and 0 < r.kid_min_age <= h.people[kid_chef[e.day]].years:
            e.cook = kid_chef[e.day]
            e.why.append("kid chef night (an adult helps)")      # no name: `why` is sent to the notes model
    eaters = h.leftover_eaters()
    for lunch_day, dinner_day in lunch_from.items():
        src = next((e for e in entries if e.day == dinner_day and e.meal == "dinner"), None)
        lunch_eaters = [p for p in eaters if p.id not in h.away.get(lunch_day, set())]
        if not src or not lunch_eaters:
            continue
        add = round(sum(p.portion for p in lunch_eaters) * portions.get(src.recipe, 1.0), 2)
        per = src.est_cost / src.servings if src.servings else 0
        src.servings, src.est_cost = round(src.servings + add, 2), round(src.est_cost + per * add, 2)
        src.why.append(f"cooked extra for {DAY_NAME[lunch_day]}'s lunch")
        entries.append(Entry(lunch_day, "leftovers", src.recipe, f"Leftovers: {src.name}", 0.0, 0.0, 0, dinner_day,
                             False, [f"from {DAY_NAME[dinner_day]}'s dinner"], [p.id for p in lunch_eaters],
                             "leftovers"))
    entries.sort(key=lambda e: (DAYS.index(e.day), MEAL_ORDER.index(e.meal)))
    flags += style_notes
    unmet = [f"{k} target missed by {solver.Value(v)}" for k, v in slack.items() if solver.Value(v)]
    dinners = [e for e in entries if e.meal == "dinner"]
    health_out = {
        "veg_per_dinner": round(sum(rec(e.recipe).veg for e in dinners) / max(1, len(dinners)), 2),
        "fish": sum(c.is_fish(rec(e.recipe)) for e in dinners),
        "vegetarian": sum(c.is_vegetarian(rec(e.recipe)) for e in dinners),
        "fried": sum(rec(e.recipe).has("fried") for e in dinners),
        "processed": sum(rec(e.recipe).has("processed") for e in entries if e.kind == "cook"),
    }
    return Plan(week_of, entries, special, list(dict.fromkeys(flags)),
                round(sum(e.est_cost for e in entries), 2), status,
                int((time.perf_counter() - t0) * 1000), rejected, health_out, unmet)
