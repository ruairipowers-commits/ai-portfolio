"""The household's recipe book: save, export, import, share with another household, and add a recipe from the web.

Recipes from the web come from the page's own structured data (schema.org Recipe, which most recipe sites publish
for search engines). DinnerPeace keeps the name, ingredients, times, servings, the site's name and a link back; the
method stays on the source page (it's the author's writing), and the household can add their own notes. Nothing is
saved until a person has looked at the draft and pressed Save.

Fetching a page the user names is the server making a request for them, so it only goes to public web addresses:
http(s), ports 80/443, every resolved address public, at most three redirects (each re-checked), 3 MB, 10 seconds.
"""
from __future__ import annotations

import html as htmllib
import ipaddress
import json
import os
import re
import socket
from fractions import Fraction
from urllib.parse import quote_plus, urljoin, urlparse

from . import store
from .catalog import Catalog, Recipe
from .config import MEALS, Household

FORMAT = "lilhelper-recipes"

UNIT_TO = {("tbsp", "cup"): 1 / 16, ("cup", "tbsp"): 16, ("tsp", "tbsp"): 1 / 3, ("tsp", "cup"): 1 / 48,
           ("oz", "lb"): 1 / 16, ("lb", "oz"): 16, ("g", "lb"): 1 / 453.6, ("g", "oz"): 1 / 28.35, ("kg", "lb"): 2.2046,
           ("ml", "cup"): 1 / 236.6, ("l", "cup"): 4.227, ("tbsp", "oz"): 0.5, ("cup", "oz"): 8, ("oz", "cup"): 1 / 8,
           ("g", "cup"): 1 / 200, ("clove", "each"): 0.1, ("head", "each"): 1, ("bunch", "each"): 1, ("can", "cup"): 1.75}


class RecipeError(ValueError):
    def __init__(self, message: str, unknown: list[str] | None = None):
        super().__init__(message)
        self.unknown = unknown or []


def convert(qty: float, frm: str | None, to: str) -> float:
    if not frm or frm == to:
        return qty
    f = UNIT_TO.get((frm.lower().rstrip("s") if frm.lower() not in ("tbsp", "tsp") else frm.lower(), to))
    if f is None:
        raise RecipeError(f"can't convert {frm} to {to}; use {to}")
    return qty * f


def _rid(name: str) -> str:
    return "h_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]


def save(con, h: Household, c: Catalog, body: dict, by: str, rid: str | None = None) -> dict:
    """One of the household's own recipes from {name, meal, serves, active, total, ingredients: [{text|ingredient,
    qty, unit}], instructions, tags, season_months, want, kid_min_age, notes, credit, url}."""
    meals = [m for m in (body.get("meals") or [body.get("meal", "dinner")]) if m]
    if not meals or any(m not in MEALS for m in meals):
        raise RecipeError("meals: breakfast, lunch or dinner")
    body = {**body, "meal": meals[0]}
    if any(not 1 <= int(m) <= 12 for m in body.get("season_months") or []):
        raise RecipeError("season months are 1–12")
    serves = float(body.get("serves") or 4)
    ing, unknown = {}, []
    for ln in body.get("ingredients") or []:
        iid = ln.get("ingredient") if ln.get("ingredient") in c.ingredients else (
            c.match(ln.get("text") or "") if ln.get("text") else None)
        if not iid:
            unknown.append(ln.get("text") or ln.get("ingredient") or "?")
            continue
        ing[iid] = round(ing.get(iid, 0) + convert(float(ln["qty"]), ln.get("unit"), c.ingredients[iid].unit) / serves, 4)
    if unknown:
        raise RecipeError("add these as your own ingredients first", unknown)
    if not ing:
        raise RecipeError("a recipe needs ingredients")
    rid = rid or _rid(body["name"])
    if rid in c.recipes and c.recipes[rid].source != "household" and not rid.startswith("h_"):
        raise RecipeError("that's a built-in recipe; choose another name")
    kid = int(body.get("kid_min_age") or 0)
    tags = sorted(set(body.get("tags") or []) | ({"kid_can_make"} if kid else set()))
    url = (body.get("url") or "").strip()
    if url and urlparse(url).scheme not in ("http", "https"):
        raise RecipeError("the source link must be a web address")
    data = {"id": rid, "name": body["name"][:80], "meal": body.get("meal", "dinner"),
            "active": int(body.get("active") or 20), "total": int(body.get("total") or 30), "ing": ing,
            "veg": float(body.get("veg", 1)), "protein": float(body.get("protein", 20)), "tags": tags,
            "source": "household", "kid_min_age": kid,
            "instructions": [str(s)[:300] for s in (body.get("instructions") or [])[:30]],
            "season_months": [int(m) for m in body.get("season_months") or []],
            "want": {k: int(v) for k, v in (body.get("want") or {}).items() if k in ("times", "per_weeks")},
            "notes": str(body.get("notes") or "")[:500], "created_by": by,
            "credit": str(body.get("credit") or "")[:80], "url": url[:500], "meals": list(dict.fromkeys(meals)),
            "kcal": max(0, min(int(body.get("kcal") or 0), 5000))}
    allergens = c.allergens_of(Recipe(**{k: v for k, v in data.items() if k in Recipe.__dataclass_fields__}))
    con.execute("INSERT OR REPLACE INTO custom_recipes VALUES (?,?,?,?,?)", (rid, json.dumps(data), 1, by, store.now()))
    con.commit()
    store.audit(con, by, "recipe", {"id": rid})
    house = h.everyone_allergies()
    return {"saved": rid, "allergens": allergens,
            "warning": (f"Contains {', '.join(sorted(set(allergens) & house))}: someone in the house is allergic, so "
                        "DinnerPeace won't plan it.") if set(allergens) & house else None}


# ---------------------------------------------------------------- export / import
def export(con, c: Catalog, household_name: str = "") -> dict:
    """The household's own recipes as a portable file (ingredients in words, amounts for 4)."""
    rows = [json.loads(r["data"]) for r in con.execute("SELECT data FROM custom_recipes WHERE active = 1 ORDER BY id")]
    custom = {r["id"]: json.loads(r["data"]) for r in con.execute("SELECT id, data FROM custom_ingredients")}
    used = set()
    recipes = []
    for d in rows:
        lines = []
        for iid, q in d["ing"].items():
            ing = c.ingredients.get(iid)
            if not ing:
                continue
            if iid in custom:
                used.add(iid)
            lines.append({"text": ing.name, "qty": round(q * 4, 3), "unit": ing.unit})
        recipes.append({k: d.get(k) for k in ("name", "meal", "meals", "kcal", "active", "total", "instructions", "tags",
                                              "season_months", "want", "kid_min_age", "notes", "credit", "url", "veg",
                                              "protein")}
                       | {"serves": 4, "ingredients": lines})
    ings = [{k: custom[i].get(k) for k in ("name", "unit", "cat", "allergens", "storage", "freezable", "shelf")}
            for i in sorted(used)]
    return {"format": FORMAT, "version": 1, "household": household_name, "recipes": recipes, "ingredients": ings}


def import_book(con, h: Household, c: Catalog, book: dict, by: str, credit: str = "") -> dict:
    """Recipes from an exported file or a shared book. Ingredients the book defines that this household doesn't have
    are added as its own; recipes with a name already in the book are skipped (not overwritten)."""
    from . import catalog as catmod
    if not isinstance(book, dict) or book.get("format") != FORMAT:
        raise RecipeError("that isn't a DinnerPeace recipe file")
    added_ing = []
    for d in (book.get("ingredients") or [])[:200]:
        name = str(d.get("name") or "").strip().lower()
        if not name or c.match(name):
            continue
        iid = "h_" + re.sub(r"[^a-z0-9]+", "_", name).strip("_")[:40]
        data = {"id": iid, "name": name, "unit": d.get("unit") or "each", "cat": d.get("cat") or "pantry", "aisle": 5,
                "allergens": sorted(set(d.get("allergens") or []) | set(c.text_allergens(name))),
                "shelf": int(d.get("shelf") or 7), "storage": d.get("storage") or "", "freezable": d.get("freezable"),
                "source": "household", "prices": {}}
        con.execute("INSERT OR REPLACE INTO custom_ingredients VALUES (?,?,?,?)", (iid, json.dumps(data), by, store.now()))
        added_ing.append(name)
    con.commit()
    c = catmod.for_household(h)
    have = {r.name.lower() for r in c.recipes.values()}
    saved, skipped, failed = [], [], []
    for r in (book.get("recipes") or [])[:500]:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in have:
            skipped.append(name)
            continue
        try:
            body = dict(r, credit=r.get("credit") or credit)
            out = save(con, h, c, body, by, rid=_rid(name) if _rid(name) not in c.recipes else _rid(name) + "_2")
            saved.append(out["saved"])
            have.add(name.lower())
        except RecipeError as e:
            failed.append({"name": name, "why": str(e), "unknown": e.unknown})
    return {"added": len(saved), "skipped_same_name": skipped, "failed": failed, "new_ingredients": added_ing}


# ---------------------------------------------------------------- from the web
class FetchError(ValueError):
    pass


def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def fetch(url: str, max_bytes: int = 3_000_000) -> tuple[str, str]:
    """GET a public web page (see the module notes for the limits). Returns (final url, text)."""
    import httpx
    for _ in range(4):
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname or u.port not in (None, 80, 443):
            raise FetchError("only ordinary web addresses (http or https)")
        if not _public(u.hostname):
            raise FetchError("that address isn't on the public web")
        with httpx.stream("GET", url, timeout=10, follow_redirects=False,
                          headers={"User-Agent": "LilHelper/1.0 (recipe import; one page at a person's request)",
                                   "Accept": "text/html,application/xhtml+xml"}) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code >= 400:
                raise FetchError(f"the page answered {r.status_code}")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise FetchError("that page is too large")
            return url, body.decode(r.encoding or "utf-8", errors="replace")
    raise FetchError("too many redirects")


def _jsonld(page: str) -> list:
    out = []
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            out.append(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            continue
    return out


def find_recipe(page: str) -> dict | None:
    def walk(x):
        if isinstance(x, list):
            for y in x:
                r = walk(y)
                if r:
                    return r
        elif isinstance(x, dict):
            t = x.get("@type")
            if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
                return x
            for k in ("@graph", "mainEntity", "itemListElement"):
                if k in x:
                    r = walk(x[k])
                    if r:
                        return r
        return None
    for block in _jsonld(page):
        r = walk(block)
        if r:
            return r
    return None


def _minutes(iso: str | None) -> int | None:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", (iso or "").strip())
    if not m or not any(m.groups()):
        return None
    d, hh, mm = (int(g or 0) for g in m.groups())
    return d * 1440 + hh * 60 + mm


UNITS = {"cup": "cup", "cups": "cup", "c": "cup", "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp",
         "tbs": "tbsp", "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp", "pound": "lb", "pounds": "lb", "lb": "lb",
         "lbs": "lb", "ounce": "oz", "ounces": "oz", "oz": "oz", "gram": "g", "grams": "g", "g": "g", "kg": "kg",
         "ml": "ml", "liter": "l", "litre": "l", "can": "can", "cans": "can", "clove": "clove", "cloves": "clove",
         "slice": "slice", "slices": "slice", "head": "head", "heads": "head", "bunch": "bunch", "bunches": "bunch"}
VULGAR = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅛": "1/8"}
SKIP = re.compile(r"^(kosher |sea |fine )?(salt|pepper|black pepper|water|ice|salt and pepper|cooking spray)\b", re.I)


def parse_line(line: str) -> dict:
    """'1 1/2 pounds boneless chicken thighs, cut into pieces' → {qty: 1.5, unit: lb, text: 'boneless chicken thighs'}"""
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", line))
    for k, v in VULGAR.items():
        t = t.replace(k, " " + v)
    t = re.sub(r"\([^)]*\)", "", t).strip()
    qty = None
    m = re.match(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)(?:\s*(?:-|to)\s*(\d+(?:\.\d+)?))?\s*", t)
    if m:
        qty = float(sum(Fraction(p) for p in m.group(1).split()))
        t = t[m.end():]
    words = t.split()
    unit = None
    if words and words[0].lower().rstrip(".") in UNITS:
        unit = UNITS[words[0].lower().rstrip(".")]
        t = " ".join(words[1:])
    t = re.sub(r"^of\s+", "", t.strip())
    text = re.split(r",|;| for | to taste", t)[0].strip()
    return {"qty": qty or 1.0, "unit": unit, "text": text, "line": line.strip()[:120], "has_qty": qty is not None}


def _season(words: str) -> list[int]:
    for pat, months in ((r"\bsummer\b", [6, 7, 8]), (r"\b(fall|autumn)\b", [9, 10, 11]), (r"\bwinter\b", [12, 1, 2]),
                        (r"\bspring\b", [3, 4, 5]), (r"thanksgiving", [11]), (r"christmas|holiday", [12])):
        if re.search(pat, words):
            return months
    return []


def draft_from_page(c: Catalog, page: str, url: str) -> dict:
    """A recipe draft (not saved) from a page's structured data, with sensible defaults a person then checks."""
    r = find_recipe(page)
    if not r:
        raise FetchError("no recipe found on that page (it doesn't publish recipe details). Try another page, or add it "
                         "by hand.")
    name = htmllib.unescape(str(r.get("name") or "Recipe")).strip()[:80]
    lines, unknown, check = [], [], []
    for raw in r.get("recipeIngredient") or r.get("ingredients") or []:
        p = parse_line(str(raw))
        if not p["text"] or SKIP.match(p["text"]):
            continue
        iid = c.match(p["text"])
        if not iid:
            cands = c.match_all(p["text"])
            iid = max(cands, key=lambda i: sum(1 for x in c.recipes.values() if i in x.ing)) if cands else None
        if not iid:
            unknown.append(p["text"])
            lines.append({"text": p["text"], "qty": p["qty"], "unit": p["unit"] or "", "line": p["line"], "known": False})
            continue
        unit = p["unit"]
        try:
            convert(p["qty"], unit, c.ingredients[iid].unit)
        except RecipeError:
            check.append(p["line"])
            unit = c.ingredients[iid].unit
        lines.append({"ingredient": iid, "text": c.ingredients[iid].name, "qty": round(p["qty"], 3), "unit": unit or "",
                      "line": p["line"], "known": True})
    y = r.get("recipeYield")
    y = y[0] if isinstance(y, list) and y else y
    m = re.search(r"\d+", str(y or ""))
    serves = int(m.group()) if m else 4
    prep, cook, total = (_minutes(r.get(k)) for k in ("prepTime", "cookTime", "totalTime"))
    total = total or ((prep or 0) + (cook or 0)) or 45
    active = prep or min(total, 25)
    cat = " ".join(str(x) for x in ([r.get("recipeCategory")] if isinstance(r.get("recipeCategory"), str)
                                    else r.get("recipeCategory") or [])).lower()
    kw = r.get("keywords")
    words = (name + " " + cat + " " + (", ".join(kw) if isinstance(kw, list) else str(kw or ""))).lower()
    meal = "breakfast" if re.search(r"breakfast|brunch", words) else "lunch" if re.search(r"\blunch|sandwich", words) \
        else "dinner"
    tags = [t for pat, t in ((r"one[- ]pot|one[- ]pan|skillet", "one_pot"), (r"sheet[- ]pan", "sheet_pan"),
                             (r"slow[- ]cooker|crock", "slow_cooker"), (r"vegetarian|vegan", "vegetarian"),
                             (r"freezer|make[- ]ahead", "freezes_well"), (r"kid", "kid_friendly")) if re.search(pat, words)]
    pub = r.get("publisher") or r.get("author") or {}
    pub = pub[0] if isinstance(pub, list) and pub else pub
    site = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', page, re.I)
    credit = (site.group(1) if site else None) or (pub.get("name") if isinstance(pub, dict) else None) or \
        urlparse(url).hostname.removeprefix("www.")
    return {"name": name, "meal": meal, "serves": serves, "active": max(1, min(active, 300)),
            "total": max(1, min(total, 1440)), "ingredients": lines, "instructions": [],
            "tags": tags, "season_months": _season(words), "want": {}, "kid_min_age": 0,
            "credit": htmllib.unescape(credit)[:80], "url": url, "unknown": unknown, "check_amounts": check,
            "note": "The method is on the source page; add your own notes if you like."}


def search(query: str, sites: list[str]) -> dict:
    """Recipe pages for a query, from the sites the household likes (or anywhere). Uses a search API when the server
    has a key (BRAVE_API_KEY); otherwise returns a search link to open in the browser."""
    q = query.strip()[:120]
    scope = " OR ".join(f"site:{s}" for s in sites[:5])
    full = f"{q} recipe {('(' + scope + ')') if scope else ''}".strip()
    key = os.getenv("BRAVE_API_KEY")
    if not key:
        return {"results": [], "search_url": f"https://www.google.com/search?q={quote_plus(full)}",
                "note": "Open the search, pick a recipe, copy its link, and paste it below."}
    import httpx
    try:
        r = httpx.get("https://api.search.brave.com/res/v1/web/search", params={"q": full, "count": 10}, timeout=10,
                      headers={"Accept": "application/json", "X-Subscription-Token": key})
        r.raise_for_status()
        items = (r.json().get("web") or {}).get("results") or []
    except httpx.HTTPError as e:
        return {"results": [], "search_url": f"https://www.google.com/search?q={quote_plus(full)}",
                "note": f"Search didn't answer ({type(e).__name__}); open the search instead."}
    return {"results": [{"title": htmllib.unescape(re.sub(r"<[^>]+>", "", i.get("title", ""))), "url": i.get("url"),
                         "site": urlparse(i.get("url", "")).hostname,
                         "snippet": htmllib.unescape(re.sub(r"<[^>]+>", "", i.get("description", "")))[:200]}
                        for i in items if i.get("url")], "search_url": None}
