"""Everything the planner needs, as one Excel workbook an admin can download, edit (Excel, Numbers, Google Sheets) and
upload again: the household, people (birthdays, allergies, likes), occasions, recipes (meals, steps, times, calories,
the youngest age that can make it) and their ingredients, ingredient preferences (brand, store, price), what's in the
fridge and pantry, and the freezer.

Uploading never deletes anything unless a row says so ("remove" column = yes) and always shows a preview first: what
would be added, changed and left alone, and any row it couldn't read and why. Lil'Helper's own recipes are in the
workbook for reference; edit a copy (give it a new name) to change one.
"""
from __future__ import annotations

import copy
import datetime as dt
import io
import json
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import recipebook, store
from .catalog import Catalog
from .config import DAYS, Household, HouseholdError, parse_household

HEAD = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="D7392A")
READONLY = PatternFill("solid", fgColor="F0E2CC")

SHEETS = {
    "Household": ["setting", "value"],
    "People": ["id", "name", "birthday", "age", "child_or_adult", "allergies", "diet", "portion", "home_days",
               "can_cook", "admin", "can_approve", "email", "likes", "dislikes"],
    "Occasions": ["id", "name", "date", "kind", "people", "recipe", "guests", "tags", "yearly", "remove"],
    "Recipes": ["id", "name", "source", "meals", "serves", "hands_on_min", "total_min", "kcal_per_serving",
                "kids_can_make_from_age", "tags", "season_months", "times_per_4_weeks", "credit", "link", "steps",
                "remove"],
    "Recipe ingredients": ["recipe", "ingredient", "qty", "unit"],
    "Ingredients": ["id", "name", "unit", "category", "allergens", "storage", "my_brand", "my_store", "my_price",
                    "my_pack", "only_that_store", "lil_helper_prices"],
    "Fridge and pantry": ["ingredient", "qty", "unit", "of_which_frozen"],
    "Freezer": ["id", "name", "recipe", "portions", "frozen_on", "use_by", "remove"],
}
HOUSEHOLD_KEYS = ["name", "timezone", "region", "budget_per_week", "time_value_per_hour", "planning_minutes_before"]


def _csv(v) -> str:
    return ", ".join(str(x) for x in v) if isinstance(v, (list, tuple, set)) else ("" if v is None else str(v))


def _list(v) -> list[str]:
    return [x.strip() for x in re.split(r"[,;\n]", str(v or "")) if x.strip()]


def _yes(v) -> bool:
    return str(v or "").strip().lower() in ("yes", "y", "true", "1", "x")


def _num(v, default=None):
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{v!r} isn't a number")


def export(h: Household, c: Catalog, con) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    readme = wb.create_sheet("Read me")
    for line in (__doc__ or "").strip().split("\n") + ["", "Lists go in one cell, separated by commas (allergies, days, "
                 "tags, meals). Dates are YYYY-MM-DD (birthdays and yearly occasions may be MM-DD).",
                 "Allergies use these names: peanut, tree_nut, dairy, egg, gluten, soy, fish, shellfish, sesame.",
                 "Shaded columns are for reference and are ignored on upload.",
                 f"Exported {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}."]:
        readme.append([line])
    readme.column_dimensions["A"].width = 120

    def sheet(name: str, rows: list[list], readonly: tuple[str, ...] = ()):
        ws = wb.create_sheet(name)
        ws.append(SHEETS[name])
        for i, col in enumerate(SHEETS[name], start=1):
            cell = ws.cell(row=1, column=i)
            cell.font, cell.fill = HEAD, FILL
            ws.column_dimensions[cell.column_letter].width = max(12, min(40, len(col) + 6))
        for r in rows:
            ws.append(r)
        for i, col in enumerate(SHEETS[name], start=1):
            if col in readonly:
                for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    for cell in row:
                        cell.fill = READONLY
        ws.freeze_panes = "A2"
        return ws

    sheet("Household", [[k, h.info.get(k)] for k in HOUSEHOLD_KEYS])
    sheet("People", [[p.id, p.name, p.birthday or "", p.age if not p.birthday else "",
                      "child" if p.is_kid else ("teen" if p.is_teen else "adult"), _csv(p.allergies), _csv(p.diet),
                      p.portion, _csv(p.home), "yes" if p.can_cook else "", "yes" if p.admin else "",
                      "yes" if p.can_approve else "", p.email or "", _csv(p.likes), _csv(p.dislikes)]
                     for p in h.people.values()], readonly=("child_or_adult",))
    sheet("Occasions", [[o.get("id", ""), o.get("name"), o.get("date"), o.get("kind", "custom"), _csv(o.get("people")),
                         o.get("recipe") or "", o.get("guests") or "", _csv(o.get("tags")),
                         "yes" if o.get("yearly") else "", ""] for o in h.raw.get("occasions") or []])
    rec_rows, ing_rows = [], []
    for r in sorted(c.recipes.values(), key=lambda r: (r.source == "book", r.name)):
        src = "Lil'Helper" if r.source == "book" else "household"
        rec_rows.append([r.id, r.name, src, _csv(r.meals), 4, r.active, r.total, r.kcal or "", r.kid_min_age or "",
                         _csv(t for t in r.tags if t != "kid_can_make"), _csv(r.season_months),
                         (r.want or {}).get("times", ""), r.credit or ("Lil'Helper" if r.source == "book" else ""),
                         r.url or "", "\n".join(r.instructions), ""])
        for iid, q in r.ing.items():
            ing = c.ingredients.get(iid)
            if ing:
                ing_rows.append([r.name, ing.name, round(q * 4, 3), ing.unit])
    ws = sheet("Recipes", rec_rows, readonly=("source",))
    for row in ws.iter_rows(min_row=2):
        row[SHEETS["Recipes"].index("steps")].alignment = Alignment(wrap_text=True, vertical="top")
    sheet("Recipe ingredients", ing_rows)
    prefs = h.raw.get("ingredient_prefs") or {}
    import yaml
    from .config import ROOT
    shelf = yaml.safe_load((ROOT / "data" / "prices.yaml").read_text())["stores"]
    rows = []
    for iid, ing in sorted(c.ingredients.items(), key=lambda kv: kv[1].name):
        p = prefs.get(iid) or {}
        book = "; ".join(f"{s}: {o['pack']:g} {ing.unit} ${o['price']:.2f} ({o['brand']})"
                         for s in (h.raw.get("stores") or []) for o in shelf.get(s, {}).get(iid, [])[:1])
        rows.append([iid, ing.name, ing.unit, ing.cat, _csv(ing.allergens), ing.storage, p.get("brand", ""),
                     p.get("store", ""), p.get("price", ""), p.get("pack", ""),
                     "yes" if p and p.get("only_store", True) and p.get("store") else "", book])
    sheet("Ingredients", rows, readonly=("lil_helper_prices",))
    pantry, frozen = store.pantry(con), store.frozen(con)
    sheet("Fridge and pantry", [[c.ingredients[i].name, round(q, 3), c.ingredients[i].unit, round(frozen.get(i, 0), 3) or ""]
                                for i, q in sorted(pantry.items()) if q > 0 and i in c.ingredients])
    sheet("Freezer", [[m["id"], m["name"], m.get("recipe") or "", m["portions"], m["frozen_on"], m.get("use_by") or "", ""]
                      for m in store.freezer_meals(con)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _rows(wb, name: str) -> list[dict]:
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    it = ws.iter_rows(values_only=True)
    head = [str(x or "").strip().lower() for x in next(it, [])]
    out = []
    for n, row in enumerate(it, start=2):
        if not any(v not in (None, "") for v in row):
            continue
        d = {head[i]: (v.strip() if isinstance(v, str) else v) for i, v in enumerate(row) if i < len(head) and head[i]}
        d["_row"] = n
        out.append(d)
    return out


def _date(v) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return (v.date() if isinstance(v, dt.datetime) else v).isoformat()
    return str(v).strip()


def plan_import(h: Household, c: Catalog, con, data: bytes) -> dict:
    """Read an uploaded workbook and work out what it would change. Nothing is saved here."""
    wb = load_workbook(io.BytesIO(data), data_only=True)
    raw = copy.deepcopy(h.raw)
    changes: dict[str, dict] = {k: {"add": [], "change": [], "remove": []} for k in SHEETS}
    problems: list[str] = []
    name_to_iid = {ing.name.lower(): iid for iid, ing in c.ingredients.items()}

    def iid_for(text: str) -> str | None:
        t = str(text or "").strip().lower()
        return t if t in c.ingredients else name_to_iid.get(t) or c.match(t)

    # household
    for r in _rows(wb, "Household"):
        k, v = str(r.get("setting") or ""), r.get("value")
        if k in HOUSEHOLD_KEYS and v not in (None, "") and str(raw["household"].get(k)) != str(v):
            raw["household"][k] = _num(v) if k in ("budget_per_week", "time_value_per_hour",
                                                   "planning_minutes_before") else str(v)
            changes["Household"]["change"].append(k)
    # people
    for r in _rows(wb, "People"):
        try:
            pid = str(r.get("id") or "").strip() or re.sub(r"[^a-z0-9]+", "_", str(r.get("name", "")).lower()).strip("_")
            if not pid or not r.get("name"):
                raise ValueError("needs a name")
            cur = dict(raw["people"].get(pid) or {})
            new = dict(cur)
            new["name"] = str(r["name"])
            bd = _date(r.get("birthday"))
            if bd:
                new["birthday"] = bd
            elif r.get("age") not in (None, ""):
                new["age"] = int(_num(r["age"]))
            for k in ("allergies", "diet", "likes", "dislikes"):
                if r.get(k) is not None:
                    new[k] = _list(r.get(k))
            if r.get("home_days") not in (None, ""):
                new["home"] = [d for d in _list(r["home_days"]) if d in DAYS]
            if r.get("portion") not in (None, ""):
                new["portion"] = _num(r["portion"])
            for k in ("can_cook", "admin", "can_approve"):
                if r.get(k) is not None:
                    new[k] = _yes(r.get(k))
            if r.get("email"):
                new["email"] = str(r["email"])
            age = None
            if new.get("birthday") and len(new["birthday"]) == 10:
                b = dt.date.fromisoformat(new["birthday"])
                t = dt.date.today()
                age = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
            elif new.get("age") is not None:
                age = int(new["age"])
            new["age_band"] = ("kid" if age < 12 else "adult") if age is not None else new.get("age_band", "adult")
            if new != cur:
                raw["people"][pid] = new
                changes["People"]["change" if cur else "add"].append(new["name"])
        except (ValueError, TypeError) as e:
            problems.append(f"People row {r['_row']}: {e}")
    # occasions
    occ = {o.get("id") or f"o_{i}": o for i, o in enumerate(raw.get("occasions") or [])}
    for r in _rows(wb, "Occasions"):
        oid = str(r.get("id") or "").strip()
        if _yes(r.get("remove")):
            if oid in occ:
                changes["Occasions"]["remove"].append(occ.pop(oid).get("name"))
            continue
        d = {"name": str(r.get("name") or ""), "date": _date(r.get("date")) or "", "kind": str(r.get("kind") or "custom"),
             "people": _list(r.get("people")), "recipe": r.get("recipe") or None,
             "guests": int(_num(r.get("guests"), 0) or 0), "tags": _list(r.get("tags")), "yearly": _yes(r.get("yearly"))}
        d = {k: v for k, v in d.items() if v not in (None, [], "", 0) or k == "yearly"}
        oid = oid or "o_" + re.sub(r"[^a-z0-9]+", "", d["name"].lower())[:12]
        d["id"] = oid
        if occ.get(oid) != d:
            changes["Occasions"]["change" if oid in occ else "add"].append(d["name"])
            occ[oid] = d
    raw["occasions"] = list(occ.values())
    # ingredient preferences
    prefs = dict(raw.get("ingredient_prefs") or {})
    for r in _rows(wb, "Ingredients"):
        iid = str(r.get("id") or "").strip() or iid_for(r.get("name"))
        if not iid or iid not in c.ingredients:
            if r.get("name"):
                problems.append(f"Ingredients row {r['_row']}: {r.get('name')!r} isn't a known ingredient "
                                "(add it in the app first)")
            continue
        try:
            p = {"brand": r.get("my_brand") or None, "store": r.get("my_store") or None,
                 "price": _num(r.get("my_price")), "pack": _num(r.get("my_pack")),
                 "only_store": _yes(r.get("only_that_store")) if r.get("only_that_store") not in (None, "") else True}
        except ValueError as e:
            problems.append(f"Ingredients row {r['_row']}: {e}")
            continue
        p = {k: v for k, v in p.items() if v not in (None, "")}
        if not any(p.get(k) for k in ("brand", "store", "price")):
            if iid in prefs:
                prefs.pop(iid)
                changes["Ingredients"]["remove"].append(c.ingredients[iid].name)
            continue
        if prefs.get(iid) != p:
            changes["Ingredients"]["change" if iid in prefs else "add"].append(c.ingredients[iid].name)
            prefs[iid] = p
    raw["ingredient_prefs"] = prefs
    raw["require_admin"] = True
    try:
        parse_household(copy.deepcopy(raw))
    except HouseholdError as e:
        problems.append(f"Settings: {e}")
    # recipes (household ones only)
    lines: dict[str, list[dict]] = {}
    for r in _rows(wb, "Recipe ingredients"):
        if r.get("recipe") and r.get("ingredient"):
            lines.setdefault(str(r["recipe"]).strip().lower(), []).append(
                {"text": str(r["ingredient"]), "qty": _num(r.get("qty"), 1) or 1, "unit": r.get("unit") or None})
    recipes = []
    by_name = {x.name.lower(): x for x in c.recipes.values()}
    for r in _rows(wb, "Recipes"):
        name = str(r.get("name") or "").strip()
        if not name or str(r.get("source") or "").lower().startswith("lil"):
            continue                                       # Lil'Helper's recipes are reference only
        existing = by_name.get(name.lower())
        if existing is not None and existing.source == "book":
            problems.append(f"Recipes row {r['_row']}: {name!r} is one of Lil'Helper's recipes; rename your copy")
            continue
        if _yes(r.get("remove")):
            if existing is not None:
                recipes.append(("remove", existing.id, None))
                changes["Recipes"]["remove"].append(name)
            continue
        try:
            body = {"name": name, "meals": _list(r.get("meals")) or ["dinner"], "serves": _num(r.get("serves"), 4),
                    "active": int(_num(r.get("hands_on_min"), 20)), "total": int(_num(r.get("total_min"), 30)),
                    "kcal": int(_num(r.get("kcal_per_serving"), 0) or 0),
                    "kid_min_age": int(_num(r.get("kids_can_make_from_age"), 0) or 0),
                    "tags": _list(r.get("tags")),
                    "season_months": [int(x) for x in _list(r.get("season_months"))],
                    "want": {"times": int(_num(r.get("times_per_4_weeks"))), "per_weeks": 4}
                    if r.get("times_per_4_weeks") not in (None, "") else {},
                    "credit": r.get("credit") or "", "url": r.get("link") or "",
                    "instructions": [s.strip() for s in str(r.get("steps") or "").split("\n") if s.strip()],
                    "ingredients": lines.get(name.lower()) or []}
        except (ValueError, TypeError) as e:
            problems.append(f"Recipes row {r['_row']}: {e}")
            continue
        unknown = [ln["text"] for ln in body["ingredients"] if not iid_for(ln["text"])]
        if unknown:
            problems.append(f"Recipes row {r['_row']} ({name}): unknown ingredients {', '.join(unknown)} — add them "
                            "in the app first")
            continue
        if not body["ingredients"]:
            problems.append(f"Recipes row {r['_row']} ({name}): no rows in Recipe ingredients")
            continue
        recipes.append(("save", existing.id if existing else None, body))
        changes["Recipes"]["change" if existing else "add"].append(name)
    # fridge and pantry
    pantry_new, frozen_new = {}, {}
    seen_pantry = False
    for r in _rows(wb, "Fridge and pantry"):
        seen_pantry = True
        iid = iid_for(r.get("ingredient"))
        if not iid:
            problems.append(f"Fridge and pantry row {r['_row']}: {r.get('ingredient')!r} isn't a known ingredient")
            continue
        try:
            pantry_new[iid] = max(0.0, _num(r.get("qty"), 0) or 0)
            if r.get("of_which_frozen") not in (None, ""):
                frozen_new[iid] = max(0.0, _num(r["of_which_frozen"]))
        except ValueError as e:
            problems.append(f"Fridge and pantry row {r['_row']}: {e}")
    if seen_pantry:
        old = store.pantry(con)
        for iid in set(old) | set(pantry_new):
            if round(old.get(iid, 0), 3) != round(pantry_new.get(iid, 0), 3):
                changes["Fridge and pantry"]["change"].append(c.ingredients[iid].name if iid in c.ingredients else iid)
    # freezer
    freezer_ops = []
    existing_fz = {str(m["id"]): m for m in store.freezer_meals(con)}
    for r in _rows(wb, "Freezer"):
        fid = str(r.get("id") or "").strip()
        if _yes(r.get("remove")):
            if fid in existing_fz:
                freezer_ops.append(("remove", fid, None))
                changes["Freezer"]["remove"].append(existing_fz[fid]["name"])
            continue
        try:
            d = {"name": str(r.get("name") or ""), "recipe": r.get("recipe") or None,
                 "portions": _num(r.get("portions"), 0), "frozen_on": _date(r.get("frozen_on")) or dt.date.today().isoformat(),
                 "use_by": _date(r.get("use_by"))}
        except ValueError as e:
            problems.append(f"Freezer row {r['_row']}: {e}")
            continue
        if len(d["name"]) < 2:
            continue
        old = existing_fz.get(fid)
        if not old or any(str(old.get(k) or "") != str(d.get(k) or "") for k in ("name", "portions", "use_by")):
            freezer_ops.append(("save", fid if old else None, d))
            changes["Freezer"]["change" if old else "add"].append(d["name"])
    summary = {k: {kk: vv for kk, vv in v.items() if vv} for k, v in changes.items()}
    return {"changes": {k: v for k, v in summary.items() if v}, "problems": problems,
            "_apply": {"raw": raw, "recipes": recipes, "pantry": pantry_new if seen_pantry else None,
                       "frozen": frozen_new, "freezer": freezer_ops}}


def apply_import(h: Household, c: Catalog, con, plan: dict, by: str) -> dict:
    from .config import save_household
    a = plan["_apply"]
    save_household(a["raw"])
    hh = parse_household(a["raw"])
    from .catalog import for_household
    cc = for_household(hh)
    done = {"recipes": 0, "freezer": 0}
    for op, rid, body in a["recipes"]:
        if op == "remove":
            con.execute("UPDATE custom_recipes SET active = 0, updated = ? WHERE id = ?", (store.now(), rid))
        else:
            recipebook.save(con, hh, cc, body, by, rid)
            done["recipes"] += 1
    con.commit()
    if a["pantry"] is not None:
        old = store.pantry(con)
        for iid in old:
            a["pantry"].setdefault(iid, 0.0)
        store.set_pantry(con, a["pantry"], a["frozen"])
    for op, fid, d in a["freezer"]:
        if op == "remove":
            con.execute("DELETE FROM freezer WHERE id = ?", (fid,))
        elif fid:
            con.execute("UPDATE freezer SET name=?, recipe=?, portions=?, use_by=COALESCE(?, use_by) WHERE id=?",
                        (d["name"], d["recipe"], d["portions"], d["use_by"], fid))
        else:
            use_by = d["use_by"] or (dt.date.fromisoformat(d["frozen_on"]) + dt.timedelta(days=90)).isoformat()
            con.execute("INSERT INTO freezer (recipe, name, portions, frozen_on, use_by) VALUES (?,?,?,?,?)",
                        (d["recipe"] or "h_freezer", d["name"], d["portions"], d["frozen_on"], use_by))
        done["freezer"] += 1
    con.commit()
    store.audit(con, by, "bulk_import", {k: len(v.get("add", [])) + len(v.get("change", []))
                                         for k, v in plan["changes"].items()})
    return {"applied": True, "changes": plan["changes"], **done}


def preview_json(plan: dict) -> str:
    return json.dumps({k: v for k, v in plan.items() if k != "_apply"})
