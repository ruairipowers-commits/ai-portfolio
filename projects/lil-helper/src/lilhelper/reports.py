"""Cost reports: per week, per meal and per person, with a plain-language analysis. All arithmetic, no model.

Where the numbers come from
  meal cost      what the meal uses: each ingredient × servings at that week's best price (specials included). A
                 week's shopping bill differs from the meals it feeds — whole packs, stocking up, using what's in the
                 pantry — so each week shows both, and the difference as "stocked up (+) / used from the pantry (−)".
  per serving    meal cost ÷ servings cooked (spare, lunch and freezer portions included).
  per person     each meal's cost per serving × that person's portion, for every meal they ate: dinners they were
                 home for, lunchboxes, leftover lunches, leftovers nights. Spare and freezer portions aren't anyone's
                 yet; they're shown separately. Nights out: the bill minus card credits, split by who went.
  actual         what the spending record (statements, receipts, manual entries) says was spent that week.
"""
from __future__ import annotations

import datetime as dt
import statistics

from . import store
from .catalog import Catalog
from .config import DAYS, Household
from .prices import week_start

PET_ITEMS = {"dog_food", "dog_treats"}


def _weeks(con, end: dt.date, n: int) -> list[tuple[dt.date, dict]]:
    out = []
    for i in range(n - 1, -1, -1):
        wk = week_start(end) - dt.timedelta(weeks=i)
        rec = store.get_week(con, wk.isoformat())
        if rec:
            out.append((wk, rec))
    return out


def _week_costs(h: Household, c: Catalog, wk: dt.date, rec: dict) -> dict:
    choice = rec.get("shopping_choice") or "balanced"
    sp = (rec.get("split") or {}).get(choice) or {}
    pet = sum(ln["cost"] for o in sp.get("orders", []) for ln in o["lines"] if ln["ingredient"] in PET_ITEMS)
    food_bill = max(0.0, float(sp.get("total", 0.0)) - pet)
    entries = rec["plan"]["entries"]
    cooked = [e for e in entries if e.get("kind", "cook") == "cook"]
    est_total = sum(e["est_cost"] for e in cooked) or 1.0
    scale = 1.0                                        # meals cost what they use; the bill is reported beside them
    people = {p.id: p for p in h.people.values()}
    per_person: dict[str, float] = {pid: 0.0 for pid in people}
    allocated = 0.0
    meals = []
    by_slot = {(e["day"], e["meal"]): e for e in cooked}
    for e in cooked:
        cost = round(e["est_cost"] * scale, 2)
        per = cost / e["servings"] if e["servings"] else 0.0
        meals.append({"week_of": wk.isoformat(), "day": e["day"], "meal": e["meal"], "name": e["name"],
                      "recipe": e["recipe"], "servings": e["servings"], "cost": cost, "per_serving": round(per, 2),
                      "eaters": len(e.get("eaters") or [])})
        for pid in e.get("eaters") or []:
            if pid in people:
                share = per * people[pid].portion
                per_person[pid] += share
                allocated += share
    for e in entries:
        kind = e.get("kind", "cook")
        if kind == "leftovers":                                    # lunch from last night's dinner
            src = by_slot.get((e.get("prep_day"), "dinner"))
            if src and src["servings"]:
                per = src["est_cost"] * scale / src["servings"]
                for pid in e.get("eaters") or []:
                    if pid in people:
                        per_person[pid] += per * people[pid].portion
                        allocated += per * people[pid].portion
    for night, kind in (rec["plan"].get("special_nights") or {}).items():
        if kind != "leftovers":
            continue
        src = next((x for x in cooked if x.get("double") and DAYS.index(x["day"]) < DAYS.index(night)), None)
        if src and src["servings"]:
            per = src["est_cost"] * scale / src["servings"]
            for p in h.eaters("dinner", night):
                per_person[p.id] += per * p.portion
                allocated += per * p.portion
    out_cost = 0.0
    for n in rec.get("eating_out") or []:
        net = float(n.get("budget", 0)) - float(n.get("credit", 0))
        out_cost += net
        for pid in n.get("eaters") or []:
            if pid in per_person:
                per_person[pid] += net / max(1, len(n["eaters"]))
    cooked_food = round(sum(m["cost"] for m in meals), 2)
    return {"week_of": wk.isoformat(), "status": rec.get("status"), "food_bill": round(food_bill, 2),
            "food_used": cooked_food, "stock_change": round(food_bill - cooked_food, 2),
            "pet_food": round(pet, 2), "eating_out": round(out_cost, 2),
            "total": round(food_bill + pet + out_cost, 2), "meals": meals,
            "per_person": {pid: round(v, 2) for pid, v in per_person.items()},
            "spare_and_freezer": round(max(0.0, cooked_food - allocated), 2),
            "servings": round(sum(m["servings"] for m in meals), 1)}


def cost_report(h: Household, c: Catalog, *, end: dt.date, weeks: int = 8) -> dict:
    con = store.connect()
    recs = _weeks(con, end, weeks)
    actual = {r["week_of"]: dict(r) for r in con.execute(
        "SELECT week_of, SUM(CASE WHEN category='groceries' THEN amount ELSE 0 END) AS groceries, "
        "SUM(CASE WHEN category!='groceries' THEN amount ELSE 0 END) AS eating_out, SUM(credit) AS credits, "
        "SUM(rewards) AS rewards FROM spend GROUP BY week_of")}
    con.close()
    rows = [_week_costs(h, c, wk, rec) for wk, rec in recs]
    for r in rows:
        a = actual.get(r["week_of"])
        r["actual"] = {k: round(v or 0, 2) for k, v in a.items() if k != "week_of"} if a else None
    meals = [m for r in rows for m in r["meals"]]
    names = {p.id: p.name for p in h.people.values()}
    people = []
    for pid, name in names.items():
        tot = sum(r["per_person"].get(pid, 0) for r in rows)
        people.append({"person": pid, "name": name, "total": round(tot, 2),
                       "per_week": round(tot / max(1, len(rows)), 2),
                       "per_day": round(tot / max(1, 7 * len(rows)), 2)})
    by_meal = {}
    for kind in ("breakfast", "lunch", "dinner"):
        ms = [m for m in meals if m["meal"] == kind]
        if ms:
            by_meal[kind] = {"meals": len(ms), "avg_cost": round(statistics.mean(m["cost"] for m in ms), 2),
                             "avg_per_serving": round(statistics.mean(m["per_serving"] for m in ms), 2)}
    return {"weeks": rows, "people": people, "by_meal": by_meal, "pets": round(sum(r["pet_food"] for r in rows), 2),
            "analysis": analyse(h, c, rows, meals), "basis": __doc__.split("Where the numbers come from")[1].strip()}


def analyse(h: Household, c: Catalog, rows: list[dict], meals: list[dict]) -> list[str]:
    """A few sentences a person can act on, each computed from the numbers above."""
    out = []
    if not rows:
        return ["No weeks planned yet."]
    totals = [r["total"] for r in rows]
    out.append(f"Food averaged ${statistics.mean(totals):.2f} a week over {len(rows)} week"
               f"{'s' if len(rows) != 1 else ''} (groceries ${statistics.mean(r['food_bill'] for r in rows):.2f}, "
               f"nights out ${statistics.mean(r['eating_out'] for r in rows):.2f}, pet food "
               f"${statistics.mean(r['pet_food'] for r in rows):.2f}).")
    if len(rows) >= 4:
        half = len(rows) // 2
        a, b = statistics.mean(totals[:half]), statistics.mean(totals[half:])
        if a:
            out.append(f"The last {len(rows) - half} weeks averaged ${b:.2f}, {abs(b - a) / a:.0%} "
                       f"{'more' if b > a else 'less'} than the {half} before.")
    dinners = [m for m in meals if m["meal"] == "dinner"]
    if dinners:
        lo, hi = h.cost_range("dinner")
        if hi is not None:
            over = [m for m in dinners if m["per_serving"] > hi]
            out.append(f"{len(over)} of {len(dinners)} dinners came in over your ${hi:.2f} a serving"
                       + (f" (most: {max(over, key=lambda m: m['per_serving'])['name']}, "
                          f"${max(m['per_serving'] for m in over):.2f})." if over else "."))
        ranked = sorted(dinners, key=lambda m: -m["per_serving"])
        med = statistics.median(m["per_serving"] for m in dinners)
        top = ranked[0]
        out.append(f"Priciest dinner per serving: {top['name']} (${top['per_serving']:.2f}); cheapest: "
                   f"{ranked[-1]['name']} (${ranked[-1]['per_serving']:.2f}); the middle is ${med:.2f}.")
        saving = (top["per_serving"] - med) * top["servings"]
        if saving > 2:
            out.append(f"Swapping one {top['name']} for a middle-priced dinner saves about ${saving:.2f} each time.")
    from .prices import PriceBook
    try:
        pb = PriceBook(h, dt.date.fromisoformat(rows[-1]["week_of"]), catalog=c)
        spend_by: dict[str, float] = {}
        for m in meals:
            r = c.recipes.get(m["recipe"])
            if not r:
                continue
            for iid, q in r.ing.items():
                spend_by[iid] = spend_by.get(iid, 0.0) + (pb.best_unit(iid) or 0) * q * m["servings"]
        tot = sum(spend_by.values()) or 1
        top5 = sorted(spend_by.items(), key=lambda kv: -kv[1])[:5]
        out.append("Biggest costs: " + ", ".join(f"{c.ingredients[i].name} {v / tot:.0%}" for i, v in top5) + ".")
    except Exception:
        pass
    acts = [r for r in rows if r.get("actual")]
    if acts:
        planned = sum(r["food_bill"] + r["pet_food"] for r in acts)
        spent = sum(r["actual"]["groceries"] for r in acts)
        if planned:
            out.append(f"Recorded grocery spending was ${spent:.2f} against ${planned:.2f} planned for those weeks "
                       f"({(spent - planned) / planned:+.0%}).")
    share_out = sum(r["eating_out"] for r in rows) / max(1e-9, sum(totals))
    if share_out > 0.25:
        out.append(f"Nights out were {share_out:.0%} of food spending.")
    return out
