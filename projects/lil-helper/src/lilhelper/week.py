"""One week, end to end: draft → (swap, change nights, accept buy-aheads) → approve. Everything a person sees in the
app comes from here.

draft:   this week's app changes (who's away, nights switched to takeout) + confirmed specials + up to N new recipe
         ideas (checked) → meal plan (solver) → freezer nights from the freezer, dinners cooked extra to freeze →
         nights out with their budgets and card credits → the dog's week → shopping list → split across stores and the
         household's shopping trips (three ways: cheapest / balanced / fastest), counting fridge and freezer space →
         buy-ahead suggestions for later weeks' meals on sale now → jobs rota → notes → savings.
swap:    a person swaps or bans one meal; every other meal is locked and the week re-solves around it.
approve: a named adult approves (HITL-02); meals go into history, the pantry and freezer are updated, and the
         hand-offs become available. Nothing is ever bought by Lil'Helper.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from . import ai, chores, feedback, money, pets, planner, savings, shopping, spend, storage, store, telemetry
from .catalog import Catalog, Recipe, for_household
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
    eating_out: list[dict] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    @property
    def split(self) -> shopping.Split:
        return self.options[self.choice]

    def to_record(self) -> dict:
        return {"plan": self.plan.to_dict(),
                "split": {k: v.to_dict() for k, v in self.options.items()},
                "chores": [a.__dict__ for a in self.chores],
                "pets": [p.__dict__ for p in self.pets],
                "savings": self.savings.to_dict() if self.savings else None,
                "shopping_choice": self.choice,
                "eating_out": self.eating_out,
                "extras": self.extras}


def with_overrides(h: Household, con, week_of: dt.date) -> Household:
    away, nights = store.overrides(con, week_start(week_of).isoformat())
    h.away, h.night_overrides = away, nights
    return h


def db_specials(con, week_of: dt.date) -> list[dict]:
    """Specials the household entered or confirmed: this week's, and standing weekly ones still valid."""
    wk = week_start(week_of).isoformat()
    rows = con.execute("SELECT * FROM specials WHERE week_of = ? OR (repeat_weekly = 1 AND week_of <= ? AND "
                       "(valid_to IS NULL OR valid_to >= ?))", (wk, wk, wk))
    out = []
    for r in rows:
        d = dict(r)
        d["channel"] = d.get("channel") or "any"
        out.append(d)
    return out


def _nights_out(h: Household, con, week_of: dt.date) -> list[dict]:
    """Takeout and eat-out nights: budget, the card credit that applies (e.g. Uber Cash), the best card, the net."""
    out = []
    credit_used: dict[str, float] = {}
    for day, kind in sorted(h.special_nights().items(), key=lambda kv: DAYS.index(kv[0])):
        if kind not in ("takeout", "eat_out"):
            continue
        cfg = h.eating_out().get(kind, {})
        date = week_of + dt.timedelta(days=DAYS.index(day))
        budget = float(cfg.get("budget", 0) or 0)
        service = cfg.get("service") or ("restaurant" if kind == "eat_out" else "uber_eats")
        used = spend.credit_used(con, service, date) + credit_used.get(service, 0.0)
        left, credit_name = money.credits_for(h, service, date, used)
        mode = "delivery" if kind == "takeout" else "in_store"
        # the credit only applies when paying with the card that carries it, so compare cards on credit + rewards
        best = (money.best_card(h, service, mode, budget), 0.0)
        for cid, card in money.cards(h).items():
            if left and any(service in cr.get("applies_to", []) for cr in card.credits):
                credit = round(min(left, budget), 2)
                r, _ = money.rate(card, money.category(service))
                pick = money.Pick(cid, card.name, r, round((budget - credit) * r, 2), money.category(service),
                                  f"{credit_name} applies")
                if credit + pick.earned > best[1] + best[0].earned:
                    best = (pick, credit)
        pick, credit = best
        credit_used[service] = credit_used.get(service, 0.0) + credit
        eaters = [p.id for p in h.eaters("dinner", day)]
        out.append({"day": day, "kind": kind, "budget": budget, "service": service, "credit": credit,
                    "credit_name": credit_name if credit else "", "card": pick.card, "card_name": pick.name,
                    "rewards": round(pick.earned, 2), "net": round(budget - credit - pick.earned, 2),
                    "eaters": eaters, "per_person": round((budget - credit) / max(1, len(eaters)), 2)})
    return out


def _freezer_nights(h: Household, con, plan: planner.Plan, flags: list[str]) -> None:
    meals = store.freezer_meals(con)
    for day, kind in sorted(h.special_nights().items(), key=lambda kv: DAYS.index(kv[0])):
        if kind != "freezer":
            continue
        need = round(sum(p.portion for p in h.eaters("dinner", day)), 2)
        m = next((m for m in meals if m["portions"] >= need * 0.75), None)
        if not m:
            flags.append(f"{day}: freezer night, but nothing big enough is in the freezer — cook or change the night")
            continue
        m["portions"] -= need
        plan.entries.append(planner.Entry(day, "dinner", m["recipe"], f"From the freezer: {m['name']}", need, 0.0, 5,
                                          day, False, [f"frozen {m['frozen_on']}"], [p.id for p in h.eaters("dinner", day)],
                                          "freezer"))
        plan.entries[-1].__dict__["freezer_id"] = m["id"]
    plan.entries.sort(key=lambda e: (DAYS.index(e.day), planner.MEAL_ORDER.index(e.meal)))


def draft(week_of: dt.date, *, h: Household | None = None, s: Settings | None = None, ideas: bool = True,
          locks: dict | None = None, bans: dict | None = None, choice: str = "balanced",
          alias_overrides: dict | None = None, extra_specials: list[dict] | None = None,
          suggested: list[Recipe] | None = None, save: bool = True, actor: str = "planner") -> WeekResult:
    t0 = time.perf_counter()
    telemetry.require_enabled("plan")
    week_of = week_start(week_of)
    con = store.connect()
    h = with_overrides(h or load_household(), con, week_of)
    s = s or Settings.load()
    c: Catalog = for_household(h)
    pb = PriceBook(h, week_of, extra_specials=db_specials(con, week_of) + list(extra_specials or []),
                   observed=spend.observed_prices(con, today=week_of), catalog=c)
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
    # freezer nights need something in the freezer: nights the freezer can't cover are cooked instead
    stock = [m["portions"] for m in store.freezer_meals(con)]
    for day, kind in sorted(h.special_nights().items(), key=lambda kv: DAYS.index(kv[0])):
        if kind == "freezer":
            need = sum(p.portion for p in h.eaters("dinner", day)) * 0.75
            i = next((i for i, v in enumerate(stock) if v >= need), None)
            if i is None:
                h.night_overrides[day] = "cook"
                flags.append(f"{day}: freezer night, but the freezer has nothing big enough — planned a cooked dinner")
            else:
                stock[i] -= need
    hist, hist_all = store.history(con), store.history_all(con)
    port = store.portions(con)
    budget = float(h.info.get("budget_per_week", 0)) or None
    plan = planner.plan_week(h, c, pb, s, extra=suggested, history=hist, portions=port, locks=locks, bans=bans,
                             history_all=hist_all)
    _freezer_nights(h, con, plan, flags)
    free = storage.free_space(h, con, c)
    freeze = storage.freezer_plan(h, c, plan, free["freezer"],
                                  sum(1 for k in h.special_nights().values() if k == "freezer"),
                                  len(store.freezer_meals(con)))
    for e, portions in freeze:
        per = e.est_cost / e.servings if e.servings else 0
        e.servings, e.est_cost, e.to_freeze = round(e.servings + portions, 2), round(e.est_cost + per * portions, 2), portions
        e.why.append(f"cook {portions:g} extra portions to freeze")
    pantry = store.pantry(con)
    pw = pets.pet_week(h, c, plan, pantry, s)
    restock = {k: v for p in pw for k, v in p.restock.items()}
    items = shopping.needs(plan, c, pantry, restock) if plan.entries else []
    for e in plan.entries:                                   # suggested recipes aren't in the catalog's book
        if e.recipe.startswith("sugg_") and e.kind == "cook":
            r = next(r for r in suggested if r.id == e.recipe)
            items = _add_recipe(items, c, r, e.servings, pantry, DAYS.index(e.prep_day))
    ytd = spend.ytd_used(con, week_of.year)
    options = _options(h, c, pb, items, s, free, ytd)
    if budget and choice in options and options[choice].total > budget and plan.entries:
        # re-plan once with the food estimate scaled down by the overshoot, then keep whichever is cheaper
        scale = budget / options[choice].total
        tighter = planner.plan_week(h, c, pb, s, extra=suggested, history=hist, portions=port, locks=locks,
                                    bans=bans, budget=plan.est_food_cost * scale, history_all=hist_all)
        if tighter.entries and "over_budget" not in tighter.flags:
            _freezer_nights(h, con, tighter, [])
            pw2 = pets.pet_week(h, c, tighter, pantry, s)
            items2 = shopping.needs(tighter, c, pantry, {k: v for p in pw2 for k, v in p.restock.items()})
            opts2 = _options(h, c, pb, items2, s, free, ytd)
            if opts2[choice].total < options[choice].total:
                plan, pw, items, options = tighter, pw2, items2, opts2
                flags.append("replanned_for_budget")
        if options[choice].total > budget:
            flags.append(f"over_budget_by_{options[choice].total - budget:.2f}")
    nights_out = _nights_out(h, con, week_of)
    cooked = [d for d in DAYS if plan.at(d, "dinner")]
    rota, load, gaps = chores.rota(h, cooked, store.past_load(con, week_of.isoformat(),
                                                             int(h.raw.get("chores", {}).get("window_weeks", 4))))
    flags += [f"chores: {g}" for g in gaps]
    notes = ai.write_notes(ctx, h, plan) if plan.entries else {}
    prev = store.get_week(con, week_of.isoformat())
    approve_s = (prev or {}).get("approve_seconds") or 0
    sav = savings.compute(h, pb, items, options[choice], approve_s / 60, feedback.ratings(con, week_of.isoformat()),
                          feedback.ratings_before(con, week_of.isoformat())) if items else None
    this_shop = options[choice].storage_used
    after = {k: round(free[k] - this_shop.get(k, 0.0), 1) for k in free}
    ahead = storage.buy_ahead(h, c, pb, storage.upcoming(con, c, week_of, int(h.raw.get("plan_ahead_weeks", 3))),
                              after, {n.ingredient for n in items})
    extras = {"storage": {"capacity": h.storage(), "free_before": free, "this_shop": this_shop, "free_after": after},
              "buy_ahead": [a.__dict__ for a in ahead],
              "buy_ahead_added": (prev or {}).get("extras", {}).get("buy_ahead_added", []) if prev else [],
              "freezer": {"cook_extra": [{"day": e.day, "recipe": e.recipe, "portions": p} for e, p in freeze],
                          "in_freezer": store.freezer_meals(con)}}
    flags += options[choice].flags
    res = WeekResult(week_of, plan, pw, items, options, choice, rota, load, notes, sav, idea_res,
                     sorted(set(flags + plan.flags)), ctx.calls, ctx.cost, int((time.perf_counter() - t0) * 1000),
                     suggested, nights_out, extras)
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


def _add_recipe(items, c, r: Recipe, servings: float, pantry, day: int = 0) -> list:
    by = {n.ingredient: n for n in items}
    for iid, q in r.ing.items():
        if iid in by:
            by[iid].qty = round(by[iid].qty + q * servings, 3)
            by[iid].need_day = min(by[iid].need_day, day)
        else:
            left = q * servings - pantry.get(iid, 0)
            if left > 0:
                ing = c.ingredients[iid]
                by[iid] = shopping.Need(iid, ing.name, round(left, 3), ing.unit, [r.name], day)
    return sorted(by.values(), key=lambda n: (c.ingredients[n.ingredient].aisle, n.name))


def _options(h, c, pb, items, s, free=None, ytd=None) -> dict[str, shopping.Split]:
    out = {}
    base_value = h.info.get("time_value_per_hour", 20)
    for name, tv in OPTIONS.items():
        h.raw["household"]["time_value_per_hour"] = base_value if tv is None else tv
        out[name] = shopping.split(h, c, pb, items, s, storage_free=free, ytd=ytd)
    h.raw["household"]["time_value_per_hour"] = base_value
    return out


def swap(week_of: dt.date, day: str, meal: str, *, to: str | None = None, actor: str = "person", **kw) -> WeekResult:
    """Lock every other meal; for this slot either use `to` or ban the current recipe. The rest re-solves."""
    con = store.connect()
    w = store.get_week(con, week_start(week_of).isoformat())
    con.close()
    if not w:
        raise ValueError("no draft for that week")
    cooked = [e for e in w["plan"]["entries"] if e.get("kind", "cook") == "cook"]
    locks = {(e["day"], e["meal"]): e["recipe"] for e in cooked if (e["day"], e["meal"]) != (day, meal)}
    prev = _unk((w.get("locks") or {}).get("bans"))
    current = next((e["recipe"] for e in cooked if (e["day"], e["meal"]) == (day, meal)), None)
    bans = {k: list(v) for k, v in prev.items()}
    if to:
        locks[(day, meal)] = to
    elif current:
        bans.setdefault((day, meal), []).append(current)
    return draft(week_of, locks=locks, bans=bans, ideas=False, actor=actor, **kw)


def set_night(week_of: dt.date, day: str, kind: str, by: str) -> None:
    """Change one night this week (cook, leftovers, takeout, eat_out, freezer). Re-draft to apply."""
    from .config import NIGHT_KINDS
    if day not in DAYS or kind not in NIGHT_KINDS:
        raise ValueError("bad day or night kind")
    con = store.connect()
    con.execute("INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)",
                (week_start(week_of).isoformat(), day, "night", "", kind, by, store.now()))
    con.commit()
    store.audit(con, by, "set_night", {"week_of": week_start(week_of).isoformat(), "day": day, "kind": kind})
    con.close()


def set_away(week_of: dt.date, day: str, person: str, away: bool, by: str) -> None:
    if day not in DAYS:
        raise ValueError("bad day")
    con = store.connect()
    con.execute("INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)",
                (week_start(week_of).isoformat(), day, "away", person, "1" if away else "0", by, store.now()))
    con.commit()
    con.close()


def apply_to_approved(week_of: dt.date, by: str) -> dict:
    """An approved week's shopping is done, so a change can't re-plan it. Apply this week's nights and who's-away in
    place instead: a night switched away from cooking drops that dinner (what was bought for it stays in the pantry
    for later), nights out are re-costed, and each dinner's eaters follow who's home. Switching a night back to cooking
    needs ingredients, so that's refused here (Cook from what I've got can fill it)."""
    from .config import load_household
    con = store.connect()
    wk = week_start(week_of)
    rec = store.get_week(con, wk.isoformat())
    if not rec or rec.get("status") != "approved":
        con.close()
        raise ValueError("not an approved week")
    h = with_overrides(load_household(), con, wk)
    plan = rec["plan"]
    nights = dict(plan.get("special_nights") or {})
    entries = plan["entries"]
    for day, kind in h.night_overrides.items():
        cooked = [e for e in entries if e["day"] == day and e["meal"] == "dinner"]
        if kind == "cook":
            if cooked:                 # back to cooking a dinner that's still in the plan
                nights.pop(day, None)
            continue
        if cooked:
            entries = [e for e in entries if not (e["day"] == day and e["meal"] == "dinner")]
            entries = [e for e in entries if not (e.get("kind") == "leftovers" and e.get("prep_day") == day)]
        nights[day] = kind
    for e in entries:
        if e["meal"] == "dinner":
            e["eaters"] = [p.id for p in h.eaters("dinner", e["day"])]
    plan.update(entries=entries, special_nights=nights)
    eating_out = _nights_out(h, con, wk)
    store.save_week(con, wk.isoformat(), plan=plan, eating_out=eating_out)
    store.audit(con, by, "change_approved", {"week_of": wk.isoformat()})
    con.close()
    return {"plan": plan, "eating_out": eating_out}


def add_ahead(week_of: dt.date, ingredients: list[str], by: str) -> list[dict]:
    """Add buy-ahead suggestions to this week's list (they go into the store's order at hand-off)."""
    con = store.connect()
    wk = week_start(week_of).isoformat()
    w = store.get_week(con, wk)
    if not w:
        raise ValueError("no draft for that week")
    extras = w.get("extras") or {}
    sugg = {a["ingredient"]: a for a in extras.get("buy_ahead", [])}
    added = {a["ingredient"]: a for a in extras.get("buy_ahead_added", [])}
    for iid in ingredients:
        if iid in sugg:
            added[iid] = sugg[iid]
    extras["buy_ahead_added"] = list(added.values())
    store.save_week(con, wk, extras=extras)
    store.audit(con, by, "buy_ahead", {"week_of": wk, "added": sorted(added)})
    con.close()
    return extras["buy_ahead_added"]


def approve(week_of: dt.date, person: str, seconds: float, choice: str = "balanced") -> dict:
    """A named person approves the week (HITL-02). History, pantry, freezer and the hand-offs follow from this."""
    con = store.connect()
    h = with_overrides(load_household(), con, week_of)
    c = for_household(h)
    wk = week_start(week_of).isoformat()
    w = store.get_week(con, wk)
    if not w:
        raise ValueError("no draft for that week")
    if person not in h.people or h.people[person].is_kid:
        raise PermissionError("only an adult in the household can approve a week")
    split = w["split"][choice]
    pantry = store.pantry(con)
    frozen = store.frozen(con)
    for o in split["orders"]:
        for ln in o["lines"]:
            pantry[ln["ingredient"]] = pantry.get(ln["ingredient"], 0) + ln["packs"] * ln["pack"]
    for a in (w.get("extras") or {}).get("buy_ahead_added", []):
        q = a["packs"] * a["pack"]
        pantry[a["ingredient"]] = pantry.get(a["ingredient"], 0) + q
        if a["keep"] == "freeze":
            frozen[a["ingredient"]] = frozen.get(a["ingredient"], 0) + q
    for e in w["plan"]["entries"]:
        date = dt.date.fromisoformat(wk) + dt.timedelta(days=DAYS.index(e["day"]))
        kind = e.get("kind", "cook")
        if kind == "freezer" and e.get("freezer_id"):
            con.execute("UPDATE freezer SET portions = MAX(0, portions - ?) WHERE id = ?", (e["servings"], e["freezer_id"]))
            con.execute("UPDATE freezer SET used_on = ? WHERE id = ? AND portions <= 0.25", (date.isoformat(), e["freezer_id"]))
            continue
        if kind != "cook":
            continue
        r = c.recipes.get(e["recipe"])
        if r:
            for iid, q in r.ing.items():
                pantry[iid] = pantry.get(iid, 0) - q * e["servings"]
                if pantry[iid] < frozen.get(iid, 0):
                    frozen[iid] = max(0.0, pantry[iid])
        if e.get("to_freeze"):
            con.execute("INSERT INTO freezer (recipe, name, portions, frozen_on, use_by) VALUES (?,?,?,?,?)",
                        (e["recipe"], e["name"], e["to_freeze"], date.isoformat(),
                         (date + dt.timedelta(days=90)).isoformat()))
        con.execute("INSERT INTO history VALUES (?,?)", (e["recipe"], date.isoformat()))
    for p in h.pets.values():
        pantry[p.food["ingredient"]] = pantry.get(p.food["ingredient"], 0) - p.food["cups_per_day"] * 7
        pantry["dog_treats"] = pantry.get("dog_treats", 0) - p.treats_per_day * 7
    store.set_pantry(con, pantry, frozen)
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
                   records_in=len(res.plan.entries), records_out=len(res.items),
                   flags=[f for f in res.flags if not f.startswith(("kid chef", "this shop", "no scheduled"))],
                   detail={"total": sp.total, "minutes": sp.minutes, "stores": len(sp.orders),
                           "dollars_saved": res.savings.dollars_saved if res.savings else None,
                           "ideas_rejected": rec["ideas_rejected"]})
