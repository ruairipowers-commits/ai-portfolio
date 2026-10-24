"""Dinner Peace Pro: the engine behind the personal-chef app. Arithmetic and rules only; no model is asked anything.

A chef is a member (role `chef`) of each client household, so everything about the family — people, allergies,
likes, brands, the week's plan, the pantry — stays in that household's folder, and the family sees what the chef
logs (containers, reheat cards) in their own app. What belongs to the chef's business lives in the chef's own
database (warehouse/chefs/<user id>/chef.sqlite): the client list (priority, visit days, billing model, access notes),
the chef's cards (names only), shopping trips, the expense ledger, invoices and coverage packs.

  cockpit        "What do I do next?": today's kitchens in time order, the next step in each, the strictest hazard
  containers     numbered containers in the client's fridge or freezer, with use-by countdowns
  reheat cards   a 4x6 label or a letter page (PDF), or an email to the family; a card naming an allergen someone
                 in the household has is refused until the chef confirms it
  voice notes    "At the Millers. Chucked the leftover lasagna, made 4 portions of short ribs, freeze two, fridge two.
                 Reheat at 350 for 25 minutes covered. They're out of olive oil." → a preview of changes to confirm
  trip           (Studio) one shopping trip across client homes for the next visits: lines for the same item merged
                 across homes that the chef pays for, priced at the cheapest store, bulk packs split by each home's
                 quantity (to the cent); homes that pay with their own card get their own checkout
  ledger         what the chef spent for each client, the card used and the rewards it earned; invoices from it
  coverage       (Studio) a password-protected, expiring page for a backup chef
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import secrets
import sqlite3
from pathlib import Path

from . import catalog as catalog_mod, money, store
from .config import DAYS, Household, data_root, load_household, parse_household, stores as load_stores, tenant
from .prices import PriceBook, week_start

BILLING = ("chef_card_reimburse", "client_card_on_file")
LOCATIONS = ("fridge", "freezer")
METHODS = ("oven", "stovetop", "microwave", "air_fryer")
SHELF_DAYS = {"fridge": 4, "freezer": 60}                 # cooked food, USDA guidance: 3–4 days chilled
COVER_LEVELS = ("view_recipes_and_routines", "full_operational")
CARD_LIKE = re.compile(r"(?:\d[ -]?){12,19}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (household_id TEXT PRIMARY KEY, priority INTEGER DEFAULT 100,
    billing TEXT DEFAULT 'chef_card_reimburse', client_card TEXT, budget REAL, visits TEXT, address TEXT,
    gate_code TEXT, access_notes TEXT, emergency TEXT, notes TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS trips (id TEXT PRIMARY KEY, date TEXT, created TEXT, status TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY, household_id TEXT, date TEXT, store TEXT, amount REAL,
    card TEXT, paid_by TEXT, rewards REAL, status TEXT DEFAULT 'pending', trip_id TEXT, invoice_id TEXT, note TEXT,
    ts TEXT);
CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, household_id TEXT, created TEXT, period_from TEXT,
    period_to TEXT, total REAL, status TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS coverage (id TEXT PRIMARY KEY, sub_name TEXT, sub_email TEXT, start TEXT, "end" TEXT,
    households TEXT, level TEXT, salt TEXT, pw_hash TEXT, created TEXT, revoked INTEGER DEFAULT 0, opened INTEGER DEFAULT 0);
"""


class ProError(ValueError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- the chef's own database
def chef_db(uid: str) -> sqlite3.Connection:
    if not re.fullmatch(r"[a-z0-9]{6,32}", uid or ""):
        raise ProError("bad chef id")
    p = data_root() / "chefs" / uid / "chef.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def get_setting(con, key: str, default=None):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def put_setting(con, key: str, value) -> None:
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
    con.commit()


def no_card_numbers(*texts) -> None:
    for t in texts:
        if t and CARD_LIKE.search(str(t)):
            raise ProError("that looks like a card number; use a name you'd recognise (e.g. 'Amex Gold')")


def _visits(raw) -> list[dict]:
    out = []
    for v in raw or []:
        day = v.get("day")
        if day not in DAYS:
            raise ProError(f"visit day must be one of {', '.join(DAYS)}")
        for k in ("arrive", "leave"):
            if v.get(k) and not re.fullmatch(r"[0-2]\d:[0-5]\d", v[k]):
                raise ProError(f"{k} must look like 13:30")
        covers = [d for d in (v.get("covers") or [day]) if d in DAYS]
        out.append({"day": day, "arrive": v.get("arrive") or "10:00", "leave": v.get("leave") or "13:00",
                    "covers": covers or [day]})
    return out


def client(con, hid: str) -> dict:
    r = con.execute("SELECT * FROM clients WHERE household_id = ?", (hid,)).fetchone()
    d = dict(r) if r else {"household_id": hid, "priority": 100, "billing": "chef_card_reimburse", "client_card": None,
                           "budget": None, "visits": "[]", "address": "", "gate_code": "", "access_notes": "",
                           "emergency": "", "notes": ""}
    d["visits"] = json.loads(d.get("visits") or "[]")
    return d


def save_client(con, hid: str, **fields) -> dict:
    cur = client(con, hid)
    cur.update({k: v for k, v in fields.items() if v is not None})
    if cur["billing"] not in BILLING:
        raise ProError(f"billing must be one of {', '.join(BILLING)}")
    no_card_numbers(cur.get("client_card"), cur.get("notes"), cur.get("access_notes"))
    cur["visits"] = _visits(cur["visits"])
    con.execute("INSERT OR REPLACE INTO clients VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (hid, int(cur["priority"]), cur["billing"], cur.get("client_card"), cur.get("budget"),
                 json.dumps(cur["visits"]), cur.get("address") or "", cur.get("gate_code") or "",
                 cur.get("access_notes") or "", cur.get("emergency") or "", cur.get("notes") or "", now()))
    con.commit()
    return client(con, hid)


def chef_household(con) -> Household:
    """The chef's cards and memberships as a household-shaped object, so money.best_card and PriceBook work on them."""
    cards = get_setting(con, "cards", []) or []
    memberships = get_setting(con, "memberships", ["costco"]) or []
    stores = get_setting(con, "stores", ["costco", "whole_foods", "trader_joes", "stop_and_shop"])
    from .accounts import starter_settings
    raw = starter_settings("chef", "northeast-us", {"id": "chef", "name": "Chef", "admin": True, "age_band": "adult"})
    raw.update({"cards": cards, "memberships": memberships, "stores": stores,
                "home_store": stores[0] if stores else "whole_foods"})
    return parse_household(raw)


def branding(con, plan: str) -> dict:
    b = get_setting(con, "branding", {}) or {}
    if plan != "chef_studio":
        return {"business": "", "footer": "Prepared with Dinner Peace Pro", "custom": False}
    return {"business": (b.get("business") or "")[:60], "footer": (b.get("footer") or "Prepared with Dinner Peace Pro")[:120],
            "custom": True}


# ---------------------------------------------------------------- a client household's dossier
def dossier(h: Household) -> dict:
    """What a chef needs before walking into the kitchen. Allergies first: they're rules, not preferences."""
    c = catalog_mod.for_household(h)
    people = []
    for p in h.people.values():
        people.append({"id": p.id, "name": p.name, "kid": p.is_kid, "age": p.current_age, "allergies": p.allergies,
                       "diet": p.diet, "likes": [c.recipes[x].name if x in c.recipes else x for x in p.likes],
                       "dislikes": [c.ingredients[x].name if x in c.ingredients else
                                    (c.recipes[x].name if x in c.recipes else x) for x in p.dislikes]})
    brands = {}
    for iid, rule in (h.raw.get("brands") or {}).items():
        if (rule or {}).get("prefer"):
            brands[c.ingredients[iid].name if iid in c.ingredients else iid] = rule["prefer"]
    for iid, pref in (h.raw.get("ingredient_prefs") or {}).items():
        if pref.get("brand"):
            brands[c.ingredients[iid].name if iid in c.ingredients else iid] = pref["brand"] + (
                f" ({pref['store'].replace('_', ' ')})" if pref.get("store") else "")
    hazards = []
    for p in people:
        for a in p["allergies"]:
            hazards.append({"person": p["name"], "allergen": a, "kid": p["kid"],
                            "text": f"{p['name']}{' (child)' if p['kid'] else ''}: {a.replace('_', ' ')} allergy"})
    hazards.sort(key=lambda x: (not x["kid"], x["allergen"]))
    return {"name": h.info.get("name"), "people": people, "hazards": hazards, "brands": brands,
            "address": h.raw.get("address") or {},
            "allergens": sorted(h.everyone_allergies()), "pets": [{"name": pt.name} for pt in h.pets.values()],
            "budget_per_week": h.info.get("budget_per_week")}


# ---------------------------------------------------------------- containers (in the client's database)
def open_containers(con) -> list[dict]:
    rows = [dict(r) for r in con.execute("SELECT * FROM containers WHERE status = 'in' ORDER BY number")]
    today = dt.date.today()
    for r in rows:
        r["days_left"] = (dt.date.fromisoformat(r["use_by"]) - today).days
        r["warn"] = "past use-by" if r["days_left"] < 0 else ("use today" if r["days_left"] == 0 else
                                                               ("use soon" if r["days_left"] == 1 else ""))
    return rows


def next_number(con) -> int:
    used = {r["number"] for r in con.execute("SELECT number FROM containers WHERE status = 'in'")}
    n = 1
    while n in used:
        n += 1
    return n


def log_container(con, dish: str, portions: float, location: str, by: str, number: int | None = None,
                  shelf_days: int | None = None, prepared: dt.date | None = None, card: str | None = None) -> dict:
    dish = (dish or "").strip()[:80]
    if not dish:
        raise ProError("say what's in the container")
    if location not in LOCATIONS:
        raise ProError("fridge or freezer")
    if not 0 < float(portions) <= 50:
        raise ProError("portions between 0 and 50")
    n = int(number) if number else next_number(con)
    if con.execute("SELECT 1 FROM containers WHERE status = 'in' AND number = ?", (n,)).fetchone():
        raise ProError(f"container #{n} is already in use; mark it eaten first or use #{next_number(con)}")
    prepared = prepared or dt.date.today()
    days = int(shelf_days or SHELF_DAYS[location])
    use_by = prepared + dt.timedelta(days=days)
    cur = con.execute("INSERT INTO containers (number, dish, portions, location, prepared, use_by, status, card, by, ts) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (n, dish, float(portions), location, prepared.isoformat(), use_by.isoformat(), "in", card, by,
                       now()))
    con.commit()
    store.audit(con, by, "container_in", {"number": n, "location": location})
    return {"id": cur.lastrowid, "number": n, "dish": dish, "portions": float(portions), "location": location,
            "prepared": prepared.isoformat(), "use_by": use_by.isoformat()}


def close_container(con, cid: int, status: str, by: str) -> None:
    if status not in ("eaten", "tossed"):
        raise ProError("eaten or tossed")
    n = con.execute("UPDATE containers SET status = ?, closed = ? WHERE id = ? AND status = 'in'",
                    (status, now(), cid)).rowcount
    con.commit()
    if not n:
        raise ProError("no such container in the fridge")
    store.audit(con, by, f"container_{status}", {"id": cid})


def find_container(con, words: str) -> dict | None:
    """The open container whose dish best matches a few spoken words (most recent first)."""
    ws = [w for w in re.findall(r"[a-z]+", words.lower()) if len(w) > 2 and w not in ("the", "leftover", "leftovers",
                                                                                        "from", "old")]
    best, score = None, 0
    for r in sorted(open_containers(con), key=lambda r: r["prepared"], reverse=True):
        hit = sum(w in r["dish"].lower() for w in ws)
        if hit > score:
            best, score = r, hit
    return best


# ---------------------------------------------------------------- reheat cards
def allergen_hits(h: Household, text: str) -> list[str]:
    """Allergens someone in this household has that the card's words point to (the hidden-allergen list too)."""
    c = catalog_mod.for_household(h)
    found = set(c.text_allergens(text))
    for iid in c.ingredients:
        name = c.ingredients[iid].name.lower()
        if re.search(rf"\b{re.escape(name)}\b", text.lower()):
            found |= set(c.ingredients[iid].allergens)
    return sorted(found & h.everyone_allergies())


def make_card(h: Household, con, meal: str, method: str, minutes: int, by: str, temp_f: int | None = None,
              covered: bool = False, notes: str = "", containers: list[int] | None = None, confirm: bool = False,
              prepared: dt.date | None = None) -> dict:
    meal = (meal or "").strip()[:80]
    if not meal:
        raise ProError("name the dish")
    if method not in METHODS:
        raise ProError(f"method must be one of {', '.join(METHODS)}")
    if not 0 < int(minutes) <= 240:
        raise ProError("minutes between 1 and 240")
    if method in ("oven", "air_fryer") and not (temp_f and 150 <= int(temp_f) <= 550):
        raise ProError("an oven temperature in °F (150–550)")
    no_card_numbers(notes)
    hits = allergen_hits(h, f"{meal} {notes}")
    if hits and not confirm:
        names = ", ".join(a.replace("_", " ") for a in hits)
        raise ProError(f"this card points to {names}, and someone in {h.info.get('name')} is allergic. Check the dish; "
                       f"confirm only if it's for someone who can eat it (the label will say 'Contains: {names}')")
    cid = secrets.token_hex(5)
    prepared = prepared or dt.date.today()
    con.execute("INSERT INTO reheat_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, prepared.isoformat(), meal, method, int(temp_f) if temp_f else None, int(minutes), int(covered),
                 notes[:400], json.dumps(containers or []), json.dumps(hits), by, now()))
    for n in containers or []:
        con.execute("UPDATE containers SET card = ? WHERE number = ? AND status = 'in'", (cid, int(n)))
    con.commit()
    store.audit(con, by, "reheat_card", {"id": cid, "allergen_confirmed": bool(hits)})
    return card(con, cid)


def card(con, cid: str) -> dict:
    r = con.execute("SELECT * FROM reheat_cards WHERE id = ?", (cid,)).fetchone()
    if not r:
        raise ProError("no such reheat card")
    d = dict(r)
    d["containers"], d["contains"], d["covered"] = json.loads(d["containers"]), json.loads(d["contains"]), bool(d["covered"])
    d["steps"] = card_steps(d)
    cs = [dict(x) for x in con.execute("SELECT number, location, use_by FROM containers WHERE card = ?", (cid,))]
    d["use_by"] = min((x["use_by"] for x in cs), default=None)
    return d


def card_steps(d: dict) -> list[str]:
    cover = "covered with foil" if d["covered"] else "uncovered"
    if d["method"] == "oven":
        steps = [f"Heat the oven to {d['temp_f']}°F.", f"Move to an oven-safe dish, {cover}.",
                 f"Bake {d['minutes']} minutes, until hot all the way through (165°F in the middle)."]
    elif d["method"] == "air_fryer":
        steps = [f"Heat the air fryer to {d['temp_f']}°F.", f"Cook {d['minutes']} minutes, shaking halfway."]
    elif d["method"] == "stovetop":
        steps = ["Tip into a pan with a splash of water or stock.",
                 f"Warm over medium heat {d['minutes']} minutes, {'lid on' if d['covered'] else 'stirring'}, until steaming."]
    else:
        steps = [f"Take the lid off the glass container{' and cover loosely' if d['covered'] else ''}.",
                 f"Microwave {d['minutes']} minutes on high, stirring halfway, until steaming."]
    steps.append("From frozen: thaw overnight in the fridge first.")
    return steps


def recent_cards(con, days: int = 14) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    return [card(con, r["id"]) for r in con.execute("SELECT id FROM reheat_cards WHERE prepared >= ? ORDER BY ts DESC",
                                                    (since,))]


def card_html(h: Household, cards: list[dict], brand: dict, size: str) -> str:
    """4x6 labels (one card a page) or a letter page with every card."""
    import html as H
    page = "4in 6in" if size == "4x6" else "letter"
    css = (f"@page {{ size: {page}; margin: {'0.25in' if size == '4x6' else '0.6in'}; }}"
           "body{font-family:Nunito,'Helvetica Neue',Arial,sans-serif;color:#2B231D;margin:0}"
           ".card{border:2px solid #9FB8A6;border-radius:18px;padding:14px 16px;margin-bottom:14px;page-break-inside:avoid;"
           "background:#FFFDF9}" + (".card{page-break-after:always;height:5.2in}" if size == "4x6" else "") +
           ".brand{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#8E683E;font-weight:800}"
           "h1{font-size:22px;margin:4px 0 2px}.meta{font-size:11px;color:#7A6F66}.big{font-size:30px;font-weight:900;"
           "color:#476B55;margin:8px 0}ol{padding-left:18px;font-size:13px;line-height:1.45}"
           ".warn{background:#FCE8E6;color:#9B2C24;border-radius:10px;padding:6px 10px;font-weight:800;font-size:12px}"
           ".foot{font-size:9px;color:#7A6F66;margin-top:8px}.pill{display:inline-block;background:#EBF2ED;"
           "color:#2F4A39;border-radius:999px;padding:2px 9px;font-size:11px;font-weight:800;margin-right:4px}")
    parts = []
    for d in cards:
        headline = (f"{d['temp_f']}°F · {d['minutes']} min" if d["method"] in ("oven", "air_fryer")
                    else f"{d['method'].replace('_', ' ').title()} · {d['minutes']} min")
        boxes = "".join(f"<span class='pill'>#{n}</span>" for n in d["containers"])
        warn = (f"<div class='warn'>Contains: {H.escape(', '.join(a.replace('_', ' ') for a in d['contains']))}</div>"
                if d["contains"] else "")
        parts.append(
            f"<div class='card'><div class='brand'>{H.escape(brand['business'] or 'Dinner Peace Pro')} · "
            f"{H.escape(h.info.get('name', ''))}</div><h1>{H.escape(d['meal'])}</h1>"
            f"<div class='meta'>Made {H.escape(d['prepared'])}"
            + (f" · use by {H.escape(d['use_by'])}" if d.get("use_by") else "") + f"</div>{boxes}"
            f"<div class='big'>{H.escape(headline)}</div>{warn}<ol>"
            + "".join(f"<li>{H.escape(s)}</li>" for s in d["steps"]) + "</ol>"
            + (f"<div class='meta'>{H.escape(d['notes'])}</div>" if d.get("notes") else "")
            + f"<div class='foot'>{H.escape(brand['footer'])}</div></div>")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(parts)}</body></html>"


def card_pdf(h: Household, cards: list[dict], brand: dict, size: str = "4x6") -> bytes:
    from weasyprint import HTML
    return HTML(string=card_html(h, cards, brand, size)).write_pdf()


# ---------------------------------------------------------------- the chef's shopping list for a household
def add_to_list(con, c, text: str, by: str, qty: float | None = None) -> dict:
    iid = c.match(text)
    name = c.ingredients[iid].name if iid else text.strip()[:60]
    unit = c.ingredients[iid].unit if iid else "each"
    cur = con.execute("INSERT INTO chef_list (ingredient, name, qty, unit, note, by, ts) VALUES (?,?,?,?,?,?,?)",
                      (iid, name, qty or 1, unit, "", by, now()))
    con.commit()
    return {"id": cur.lastrowid, "ingredient": iid, "name": name, "qty": qty or 1, "unit": unit}


def open_list(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM chef_list WHERE done = 0 ORDER BY id")]


# ---------------------------------------------------------------- voice notes → a preview of changes
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "twelve": 12, "a": 1, "an": 1, "half": 0.5}
NUMW = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve|a|an|half)"


def _n(w: str) -> float:
    return float(w) if re.fullmatch(r"\d+(?:\.\d+)?", w) else float(WORDNUM[w])


def parse_note(text: str, client_names: dict[str, str]) -> dict:
    """Rules, not a model: what a chef says in a kitchen → a list of proposed changes. Nothing is saved here."""
    t = " " + re.sub(r"\s+", " ", text.lower().replace("’", "'")) + " "
    out: dict = {"household": None, "actions": [], "unparsed": []}
    # which kitchen: "at the Millers", "for the Hendersons", "Miller family"
    for hid, name in client_names.items():
        fam = re.sub(r"\b(the|family|household|house|home)\b", "", name.lower()).strip()
        stem = re.sub(r"s$", "", fam.split()[-1]) if fam else ""
        if stem and re.search(rf"\b{re.escape(stem)}(s|'s|es)?\b", t):
            out["household"] = hid
            break
    verbs = (r"made|cooked|prepped|did|freeze|fridge|refrigerate|reheat|microwave|chucked|tossed|threw|binned|dumped|"
             r"got rid|they|we|need|add|then")
    for sentence in re.split(rf"[.;!?]| and then |,\s*(?=(?:and )?(?:{verbs})\b)| and (?=(?:{verbs})\b)", t):
        s = sentence.strip()
        if not s:
            continue
        hit = False
        m = re.search(r"\b(chucked|tossed|threw out|threw away|binned|dumped|got rid of)\b (?:the )?(.+?)(?: from \w+day)?$", s)
        if m:
            out["actions"].append({"kind": "toss", "what": m.group(2).strip()})
            hit = True
        m = re.search(r"\b(?:they|we) (?:ate|finished) (?:the )?(.+?)(?: from \w+day)?$", s)
        if m:
            out["actions"].append({"kind": "eaten", "what": m.group(1).strip()})
            hit = True
        m = re.search(rf"\b(?:made|cooked|prepped|did) {NUMW} (?:portions?|servings?|containers?) of (.+?)$", s)
        if m:
            out["actions"].append({"kind": "made", "dish": m.group(2).strip().rstrip(","), "portions": _n(m.group(1))})
            hit = True
        for m in re.finditer(rf"\b(freeze|fridge|refrigerate) {NUMW}\b|\b{NUMW} (?:in the )?(freezer|fridge)\b", s):
            if m.group(1):
                loc, n = ("freezer" if m.group(1) == "freeze" else "fridge"), _n(m.group(2))
            else:
                loc, n = m.group(4), _n(m.group(3))
            out["actions"].append({"kind": "split", "location": loc, "portions": n})
            hit = True
        m = re.search(r"\breheat\b.*?(?:at |to )?(\d{3})\b.*?(\d{1,3}) ?(?:min|minutes)", s)
        if m:
            out["actions"].append({"kind": "reheat", "method": "oven", "temp_f": int(m.group(1)),
                                   "minutes": int(m.group(2)), "covered": "covered" in s and "uncovered" not in s})
            hit = True
        else:
            m = re.search(r"\b(microwave|stovetop|stove|air fry(?:er)?)\b.*?(\d{1,3}) ?(?:min|minutes)", s)
            if m and ("reheat" in s or "warm" in s or m.group(1) == "microwave"):
                meth = {"stove": "stovetop", "air fry": "air_fryer", "air fryer": "air_fryer"}.get(m.group(1), m.group(1))
                temp = re.search(r"\b(\d{3})\b", s)
                out["actions"].append({"kind": "reheat", "method": meth, "minutes": int(m.group(2)),
                                       "temp_f": int(temp.group(1)) if temp else None,
                                       "covered": "covered" in s or "lid on" in s})
                hit = True
        m = re.search(r"\b(?:(?:they're|they are|we're|we are) (?:out of|low on|almost out of)|need more|add) (.+?)"
                      r"(?: to the (?:shopping )?list)?$", s)
        if m:
            for item in re.split(r",| and ", m.group(1)):
                if item.strip():
                    out["actions"].append({"kind": "shop", "item": item.strip()})
            hit = True
        if not hit and not re.fullmatch(r"(?:at|for) (?:the )?[a-z' ]+", s):
            out["unparsed"].append(s)
    # "made 4 portions … freeze two, fridge two" → containers; no split → one fridge container
    made = [a for a in out["actions"] if a["kind"] == "made"]
    splits = [a for a in out["actions"] if a["kind"] == "split"]
    for a in made:
        a["containers"] = ([{"location": sp["location"], "portions": sp["portions"]} for sp in splits]
                           or [{"location": "fridge", "portions": a["portions"]}])
        if splits and abs(sum(sp["portions"] for sp in splits) - a["portions"]) > 1e-9:
            a["warning"] = f"the split adds up to {sum(sp['portions'] for sp in splits):g}, not {a['portions']:g}"
    for a in [a for a in out["actions"] if a["kind"] == "reheat"]:
        a["meal"] = made[-1]["dish"] if made else None
    out["actions"] = [a for a in out["actions"] if a["kind"] != "split"]
    return out


def apply_note(h: Household, con, parsed: dict, by: str, confirm_allergen: bool = False) -> dict:
    """Carry out a confirmed preview in one household (the caller has set the tenant)."""
    c = catalog_mod.for_household(h)
    if not confirm_allergen:                     # check before changing anything, so a refusal leaves no half-change
        for a in parsed["actions"]:
            if a["kind"] in ("made", "reheat") and allergen_hits(h, a.get("dish") or a.get("meal") or ""):
                hits = ", ".join(x.replace("_", " ") for x in allergen_hits(h, a.get("dish") or a.get("meal")))
                raise ProError(f"{a.get('dish') or a.get('meal')} points to {hits}, and someone in "
                               f"{h.info.get('name')} is allergic. Check the dish, then confirm if it's right")
    done = {"tossed": [], "eaten": [], "containers": [], "cards": [], "shopping": [], "skipped": []}
    new_numbers: list[int] = []
    for a in parsed["actions"]:
        if a["kind"] in ("toss", "eaten"):
            box = find_container(con, a["what"])
            if box:
                close_container(con, box["id"], "tossed" if a["kind"] == "toss" else "eaten", by)
                done["tossed" if a["kind"] == "toss" else "eaten"].append(f"#{box['number']} {box['dish']}")
            else:
                done["skipped"].append(f"no open container matches “{a['what']}”")
        elif a["kind"] == "made":
            for part in a["containers"]:
                box = log_container(con, a["dish"].capitalize(), part["portions"], part["location"], by)
                new_numbers.append(box["number"])
                done["containers"].append(box)
        elif a["kind"] == "shop":
            done["shopping"].append(add_to_list(con, c, a["item"], by))
    for a in parsed["actions"]:
        if a["kind"] == "reheat":
            if not a.get("meal"):
                done["skipped"].append("a reheat instruction with no dish to attach it to")
                continue
            done["cards"].append(make_card(h, con, a["meal"].capitalize(), a["method"], a["minutes"], by,
                                           a.get("temp_f"), a.get("covered", False), "", new_numbers,
                                           confirm=confirm_allergen))
    return done


# ---------------------------------------------------------------- the cockpit
def _today_visit(cl: dict, day: str) -> dict | None:
    return next((v for v in cl["visits"] if v["day"] == day), None)


def kitchen_today(hid: str, cl: dict, today: dt.date) -> dict | None:
    """One client's visit today (if any): dishes to cook, what's packed, the next step, hazards."""
    day = DAYS[today.weekday()]
    v = _today_visit(cl, day)
    with tenant(hid):
        h = load_household()
        dz = dossier(h)
        con = store.connect()
        rec = store.get_week(con, week_start(today).isoformat())
        boxes = open_containers(con)
        shopping = open_list(con)
        con.close()
    if not v:
        return None
    dishes = []
    for e in (rec or {}).get("plan", {}).get("entries", []):
        if e["day"] in v["covers"] and e.get("kind", "cook") == "cook":
            dishes.append({"day": e["day"], "meal": e["meal"], "name": e["name"], "recipe": e["recipe"],
                           "servings": e["servings"]})
    made_today = [b for b in boxes if b["prepared"] == today.isoformat()]
    for d in dishes:
        d["ready"] = any(_same_dish(d["name"], b["dish"]) for b in made_today)
    left = [d for d in dishes if not d["ready"]]
    if not rec:
        nxt = "No plan for this week yet: draft it in their Week tab"
    elif left:
        d = left[0]
        nxt = f"Cook {d['name']} ({d['servings']:g} servings) and pack container #{_next_free(boxes)}"
    elif dishes:
        nxt = "Everything's packed: print the reheat labels and log leftovers"
    else:
        nxt = "No cooked meals planned for the days you cover"
    return {"household_id": hid, "name": dz["name"], "arrive": v["arrive"], "leave": v["leave"], "covers": v["covers"],
            "priority": cl["priority"], "dishes": dishes, "ready": sum(d["ready"] for d in dishes),
            "next": nxt, "hazard": dz["hazards"][0]["text"] if dz["hazards"] else None,
            "hazards": [x["text"] for x in dz["hazards"]], "containers_in": len(boxes),
            "expiring": [f"#{b['number']} {b['dish']}" for b in boxes if b["days_left"] <= 1],
            "shopping": [s["name"] for s in shopping], "plan_status": (rec or {}).get("status")}


def _same_dish(a: str, b: str) -> bool:
    wa = {w for w in re.findall(r"[a-z]+", a.lower()) if len(w) > 3}
    wb = {w for w in re.findall(r"[a-z]+", b.lower()) if len(w) > 3}
    return bool(wa and wb and len(wa & wb) >= max(1, min(len(wa), len(wb)) // 2))


def _next_free(boxes: list[dict]) -> int:
    used = {b["number"] for b in boxes}
    n = 1
    while n in used:
        n += 1
    return n


def cockpit(uid: str, hids: list[str], names: dict[str, str], today: dt.date, clock: str = "00:00") -> dict:
    con = chef_db(uid)
    clients = {hid: client(con, hid) for hid in hids}
    trip = con.execute("SELECT * FROM trips WHERE date = ? AND status != 'done' ORDER BY created DESC LIMIT 1",
                       (today.isoformat(),)).fetchone()
    con.close()
    kitchens = [k for k in (kitchen_today(hid, clients[hid], today) for hid in hids) if k]
    kitchens.sort(key=lambda k: (k["arrive"], k["priority"]))
    current = next((k for k in kitchens if k["leave"] > clock), None)
    for k in kitchens:
        k["done"] = k["leave"] <= clock
    upcoming = []
    for n in range(1, 7):
        d = today + dt.timedelta(days=n)
        for hid in hids:
            v = _today_visit(clients[hid], DAYS[d.weekday()])
            if v:
                upcoming.append({"date": d.isoformat(), "day": DAYS[d.weekday()], "household_id": hid,
                                 "name": names.get(hid, ""), "arrive": v["arrive"]})
    stop = None
    if trip:
        data = json.loads(trip["data"])
        stop = next(({"store": s["store_name"], "items": sum(len(ch["lines"]) for ch in s["checkouts"]),
                      "pay": [{"with": ch["card_name"] if ch["paid_by"] == "chef" else f"{ch['household_name']}'s card",
                               "note": ch.get("card_note", ""), "total": ch["total"]} for ch in s["checkouts"]]}
                     for s in data["stops"]), None)
    return {"date": today.isoformat(), "homes_today": len(kitchens), "kitchens": kitchens, "now": current,
            "next_stop": stop, "trip_id": trip["id"] if trip else None, "upcoming": upcoming[:8],
            "clients": [{"household_id": hid, "name": names.get(hid, ""), "priority": clients[hid]["priority"],
                         "billing": clients[hid]["billing"], "visits": clients[hid]["visits"]}
                        for hid in sorted(hids, key=lambda x: clients[x]["priority"])]}


# ---------------------------------------------------------------- one shopping trip across client homes (Studio)
def home_needs(hid: str, cl: dict, start: dt.date, days: int = 3) -> dict:
    """What one home's visits in [start, start+days) need: plan ingredients × servings, minus their pantry, plus the
    chef's list for them. Quantities in each ingredient's unit."""
    want: dict[str, float] = {}
    why: dict[str, set] = {}
    with tenant(hid):
        h = load_household()
        c = catalog_mod.for_household(h)
        con = store.connect()
        pantry = store.pantry(con)
        visit_days = []
        for n in range(days):
            d = start + dt.timedelta(days=n)
            v = _today_visit(cl, DAYS[d.weekday()])
            if v:
                visit_days.append((d, v))
        for d, v in visit_days:
            rec = store.get_week(con, week_start(d).isoformat())
            for e in (rec or {}).get("plan", {}).get("entries", []):
                if e["day"] in v["covers"] and e.get("kind", "cook") == "cook" and e["recipe"] in c.recipes:
                    for iid, q in c.recipes[e["recipe"]].ing.items():
                        want[iid] = want.get(iid, 0) + q * e["servings"]
                        why.setdefault(iid, set()).add(e["name"])
        for item in open_list(con):
            if item["ingredient"]:
                want[item["ingredient"]] = want.get(item["ingredient"], 0) + float(item["qty"] or 1)
                why.setdefault(item["ingredient"], set()).add("their list")
        con.close()
        brands = {iid: (r or {}).get("prefer") for iid, r in (h.raw.get("brands") or {}).items() if (r or {}).get("prefer")}
        brands |= {iid: p["brand"] for iid, p in (h.raw.get("ingredient_prefs") or {}).items() if p.get("brand")}
        banned = {iid: (r or {}).get("banned") for iid, r in (h.raw.get("brands") or {}).items() if (r or {}).get("banned")}
        name = h.info.get("name", "")
        visits = [d.isoformat() for d, _ in visit_days]
    need = {}
    for iid, q in want.items():
        short = q - pantry.get(iid, 0.0)
        if short > 1e-6 and not banned.get(iid):
            need[iid] = {"qty": round(short, 3), "brand": brands.get(iid), "for": sorted(why.get(iid, []))}
    return {"household_id": hid, "name": name, "visits": visits, "need": need}


def split_cents(total: float, weights: list[float]) -> list[float]:
    """Shares of `total` by weight, in cents, that add up exactly (largest remainder)."""
    cents = int(round(total * 100))
    s = sum(weights)
    if s <= 0:
        return [0.0] * len(weights)
    raw = [cents * w / s for w in weights]
    base = [math.floor(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)[: cents - sum(base)]:
        base[i] += 1
    return [b / 100 for b in base]


def build_trip(uid: str, homes: list[dict], billing: dict[str, str], date: dt.date) -> dict:
    """Merge, price, split and route. `homes` from home_needs; `billing` hid → billing model."""
    con = chef_db(uid)
    ch = chef_household(con)
    con.close()
    c = catalog_mod.get(ch.info.get("region", "northeast-us"))
    pb = PriceBook(ch, date)
    store_cfg = load_stores()["stores"]
    # group lines: chef-paid homes share a line per (ingredient, brand); client-card homes buy their own
    groups: dict[tuple, list[tuple[str, float]]] = {}
    brand_names: dict[str, str] = {}
    for hm in homes:
        own = billing.get(hm["household_id"]) == "client_card_on_file"
        for iid, n in hm["need"].items():
            key = (iid, (n["brand"] or "").lower(), hm["household_id"] if own else "")
            brand_names[key[1]] = n["brand"] or ""
            groups.setdefault(key, []).append((hm["household_id"], n["qty"]))
    flags, unavailable = [], []
    names = {hm["household_id"]: hm["name"] for hm in homes}
    # every store's best pack for every line
    options: dict[tuple, dict[str, tuple]] = {}
    for key, parts in sorted(groups.items()):
        iid, brand, _ = key
        qty = sum(q for _, q in parts)
        offers = pb.offers(iid, mode="in_store")
        if brand:
            matching = [o for o in offers if o.brand.lower() == brand]
            if not matching and offers:
                flags.append(f"{c.ingredients[iid].name if iid in c.ingredients else iid}: buy {brand_names.get(brand, brand)} "
                             f"(the price list doesn't have it, so it's priced as the cheapest brand)")
            offers = matching or offers
        if not offers:
            unavailable.append(c.ingredients[iid].name if iid in c.ingredients else iid)
            continue
        per: dict[str, tuple] = {}
        for o in offers:
            packs = max(1, math.ceil(qty / o.pack - 1e-9))
            cost = round(packs * o.price, 2)
            if o.store not in per or cost < per[o.store][0]:
                per[o.store] = (cost, o, packs)
        options[key] = per
    # the route: the set of stores (up to max_stops) with the lowest cost + the chef's time in each store
    cdb = chef_db(uid)
    max_stops = int(get_setting(cdb, "max_stops", 2) or 2)
    hourly = float(get_setting(cdb, "time_value", 40) or 40)
    cdb.close()
    minutes = {s: int(((store_cfg[s].get("modes") or {}).get("in_store") or {}).get("minutes", 30)) for s in pb.stores}
    best_set, best_cost = None, math.inf
    from itertools import combinations
    for k in range(1, min(max_stops, len(pb.stores)) + 1):
        for subset in combinations(pb.stores, k):
            total, ok = 0.0, True
            for per in options.values():
                here = [per[s][0] for s in subset if s in per]
                if not here:
                    ok = False
                    break
                total += min(here)
            if not ok:
                continue
            total += sum(minutes[s] for s in subset) / 60 * hourly
            if total < best_cost - 1e-9:
                best_set, best_cost = subset, total
    if best_set is None:                                   # nothing covers every line in max_stops: allow all
        best_set = tuple(pb.stores)
        flags.append(f"no {max_stops} stores carry everything, so the trip uses more stops")
    stops: dict[str, dict] = {}
    for key, per in options.items():
        iid, brand, own_hid = key
        parts = groups[key]
        qty = sum(q for _, q in parts)
        avail = {s: v for s, v in per.items() if s in best_set} or per
        st_id = min(avail, key=lambda s: (avail[s][0], -avail[s][1].pack))
        cost, best, packs = avail[st_id]
        shares = split_cents(cost, [q for _, q in parts])
        ing = c.ingredients.get(iid)
        line = {"ingredient": iid, "name": ing.name if ing else iid, "brand": best.brand, "packs": packs,
                "pack": best.pack, "unit": ing.unit if ing else "", "price_each": best.price, "cost": cost,
                "special": best.special, "aisle": ing.aisle if ing else 99, "storage": ing.storage if ing else "pantry",
                "bulk": len(parts) > 1 and best.pack > max(q for _, q in parts) + 1e-9,
                "shares": [{"household_id": hid, "name": names[hid], "qty": round(q, 2), "cost": sh,
                            "pct": round(100 * q / qty) if qty else 0} for (hid, q), sh in zip(parts, shares)]}
        st = stops.setdefault(st_id, {"store": st_id, "store_name": store_cfg[st_id]["name"], "checkouts": {}})
        ck = own_hid or "chef"
        co = st["checkouts"].setdefault(ck, {"paid_by": "client" if own_hid else "chef", "household_id": own_hid or None,
                                             "household_name": names.get(own_hid, ""), "lines": []})
        co["lines"].append(line)
    out_stops = []
    used: dict[tuple[str, str], float] = {}
    for st in stops.values():
        cos = []
        for co in st["checkouts"].values():
            co["lines"].sort(key=lambda ln: ln["aisle"])
            co["total"] = round(sum(ln["cost"] for ln in co["lines"]), 2)
            if co["paid_by"] == "chef":
                pick = money.best_card(ch, st["store"], "in_store", co["total"], used=used)
                co.update({"card": pick.card, "card_name": pick.name, "card_note": pick.note, "rewards": pick.earned})
                money.add_use(used, pick, co["total"])
            else:
                co.update({"card": None, "card_name": "client's card", "card_note": "separate checkout", "rewards": 0.0})
            per = {}
            for ln in co["lines"]:
                for sh in ln["shares"]:
                    per[sh["household_id"]] = round(per.get(sh["household_id"], 0) + sh["cost"], 2)
            co["per_home"] = [{"household_id": k, "name": names[k], "amount": v} for k, v in per.items()]
            cos.append(co)
        # cold things last: the stop with the most chilled or frozen lines goes at the end of the route
        cold = sum(ln["storage"] in ("fridge", "freezer") for co in cos for ln in co["lines"])
        out_stops.append({"store": st["store"], "store_name": st["store_name"], "checkouts": cos, "cold": cold,
                          "total": round(sum(co["total"] for co in cos), 2)})
    out_stops.sort(key=lambda s: (s["cold"], s["store_name"]))
    per_home: dict[str, float] = {}
    for s in out_stops:
        for co in s["checkouts"]:
            for p in co["per_home"]:
                per_home[p["household_id"]] = round(per_home.get(p["household_id"], 0) + p["amount"], 2)
    return {"date": date.isoformat(), "stops": out_stops, "homes": [{"household_id": k, "name": names[k], "amount": v,
                                                                      "billing": billing.get(k)} for k, v in per_home.items()],
            "total": round(sum(s["total"] for s in out_stops), 2),
            "rewards": round(sum(co.get("rewards", 0) for s in out_stops for co in s["checkouts"]), 2),
            "bulk_lines": sum(ln["bulk"] for s in out_stops for co in s["checkouts"] for ln in co["lines"]),
            "minutes": sum(minutes.get(s["store"], 30) for s in out_stops),
            "flags": flags, "unavailable": unavailable}


def save_trip(uid: str, trip: dict) -> str:
    con = chef_db(uid)
    tid = secrets.token_hex(5)
    con.execute("INSERT INTO trips VALUES (?,?,?,?,?)", (tid, trip["date"], now(), "planned", json.dumps(trip)))
    con.commit()
    con.close()
    return tid


def get_trip(con, tid: str) -> dict:
    r = con.execute("SELECT * FROM trips WHERE id = ?", (tid,)).fetchone()
    if not r:
        raise ProError("no such trip")
    return {"id": r["id"], "status": r["status"], **json.loads(r["data"])}


def record_checkout(con, tid: str, store_id: str, paid_by: str, household_id: str | None, actual: float | None) -> list[dict]:
    """A checkout paid: ledger rows per home, split by the planned shares (scaled to what the receipt said)."""
    trip = get_trip(con, tid)
    st = next((s for s in trip["stops"] if s["store"] == store_id), None)
    co = next((c for c in (st or {}).get("checkouts", []) if c["paid_by"] == paid_by
               and (c.get("household_id") or None) == (household_id or None)), None)
    if not co:
        raise ProError("no such checkout on this trip")
    if co.get("recorded"):
        raise ProError("that checkout is already recorded")
    total = float(actual) if actual is not None else co["total"]
    if not 0 <= total <= 10000:
        raise ProError("that total doesn't look right")
    homes = co["per_home"]
    amounts = split_cents(total, [p["amount"] for p in homes])
    rewards = round(co.get("rewards", 0) * (total / co["total"]) if co["total"] else 0, 2)
    rew = split_cents(rewards, [p["amount"] for p in homes])
    rows = []
    for p, amt, rw in zip(homes, amounts, rew):
        con.execute("INSERT INTO ledger (household_id, date, store, amount, card, paid_by, rewards, status, trip_id, "
                    "note, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (p["household_id"], trip["date"], st["store_name"], amt, co.get("card_name"), paid_by, rw,
                     "pending" if paid_by == "chef" else "cleared", tid, f"trip {tid}", now()))
        rows.append({"household_id": p["household_id"], "amount": amt, "rewards": rw})
    co["recorded"], co["actual"] = True, total
    done = all(c.get("recorded") for s in trip["stops"] for c in s["checkouts"])
    data = {k: v for k, v in trip.items() if k not in ("id", "status")}
    con.execute("UPDATE trips SET data = ?, status = ? WHERE id = ?", (json.dumps(data), "done" if done else "shopping", tid))
    con.commit()
    return rows


def add_receipt(con, hid: str, store_name: str, amount: float, card_name: str | None, date: dt.date, note: str = "",
                paid_by: str = "chef") -> int:
    no_card_numbers(card_name, note)
    if not 0 < float(amount) <= 10000:
        raise ProError("that amount doesn't look right")
    cur = con.execute("INSERT INTO ledger (household_id, date, store, amount, card, paid_by, rewards, status, note, ts) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (hid, date.isoformat(), store_name[:40], round(float(amount), 2), (card_name or "")[:40], paid_by,
                       0.0, "pending" if paid_by == "chef" else "cleared", note[:200], now()))
    con.commit()
    return cur.lastrowid


def ledger(con, hid: str | None = None, status: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM ledger WHERE 1=1", []
    if hid:
        q, args = q + " AND household_id = ?", args + [hid]
    if status:
        q, args = q + " AND status = ?", args + [status]
    return [dict(r) for r in con.execute(q + " ORDER BY date DESC, id DESC", args)]


def week_spend(con, hid: str, today: dt.date) -> float:
    ws = week_start(today).isoformat()
    we = (week_start(today) + dt.timedelta(days=7)).isoformat()
    r = con.execute("SELECT COALESCE(SUM(amount),0) AS s FROM ledger WHERE household_id = ? AND date >= ? AND date < ?",
                    (hid, ws, we)).fetchone()
    return round(r["s"], 2)


def make_invoice(con, hid: str, name: str) -> dict:
    rows = ledger(con, hid, "pending")
    rows = [r for r in rows if r["paid_by"] == "chef"]
    if not rows:
        raise ProError("nothing to invoice: no pending expenses for this client")
    iid = "INV-" + dt.date.today().strftime("%Y%m%d") + "-" + secrets.token_hex(2).upper()
    total = round(sum(r["amount"] for r in rows), 2)
    lines = [{"date": r["date"], "store": r["store"], "amount": r["amount"], "note": r["note"]} for r in sorted(rows, key=lambda r: r["date"])]
    con.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)",
                (iid, hid, now(), lines[0]["date"], lines[-1]["date"], total, "sent", json.dumps({"name": name, "lines": lines})))
    con.executemany("UPDATE ledger SET status = 'invoiced', invoice_id = ? WHERE id = ?", [(iid, r["id"]) for r in rows])
    con.commit()
    return invoice(con, iid)


def invoice(con, iid: str) -> dict:
    r = con.execute("SELECT * FROM invoices WHERE id = ?", (iid,)).fetchone()
    if not r:
        raise ProError("no such invoice")
    d = dict(r)
    d.update(json.loads(d.pop("data")))
    return d


def mark_paid(con, iid: str) -> None:
    con.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (iid,))
    con.execute("UPDATE ledger SET status = 'cleared' WHERE invoice_id = ?", (iid,))
    con.commit()


def invoice_html(inv: dict, brand: dict) -> str:
    import html as H
    rows = "".join(f"<tr><td>{H.escape(l['date'])}</td><td>{H.escape(l['store'])}</td>"
                   f"<td style='text-align:right'>${l['amount']:.2f}</td></tr>" for l in inv["lines"])
    return ("<div style=\"font-family:Nunito,Arial,sans-serif;color:#2B231D;max-width:560px\">"
            f"<p style='color:#8E683E;font-weight:800;letter-spacing:.06em;text-transform:uppercase;font-size:12px'>"
            f"{H.escape(brand['business'] or 'Dinner Peace Pro')}</p>"
            f"<h2 style='margin:4px 0'>Grocery expenses · {H.escape(inv['name'])}</h2>"
            f"<p style='color:#7A6F66'>Invoice {H.escape(inv['id'])} · {H.escape(inv['period_from'])} to "
            f"{H.escape(inv['period_to'])}</p><table style='width:100%;border-collapse:collapse'>"
            f"<tr><th align=left>Date</th><th align=left>Store</th><th align=right>Amount</th></tr>{rows}"
            f"<tr><td colspan=2 style='font-weight:800;padding-top:8px'>Total</td>"
            f"<td style='text-align:right;font-weight:800;padding-top:8px'>${inv['total']:.2f}</td></tr></table>"
            f"<p style='color:#7A6F66;font-size:12px'>{H.escape(brand['footer'])}</p></div>")


# ---------------------------------------------------------------- coverage packs (Studio)
def _hash(pw: str, salt: str) -> str:
    return hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()


def make_coverage(con, sub_name: str, sub_email: str, start: dt.date, end: dt.date, hids: list[str], level: str,
                  password: str) -> dict:
    if level not in COVER_LEVELS:
        raise ProError(f"level must be one of {', '.join(COVER_LEVELS)}")
    if end < start or (end - start).days > 31:
        raise ProError("a coverage pack runs from 1 to 31 days")
    if end < dt.date.today():
        raise ProError("that end date has passed")
    if len(password or "") < 8:
        raise ProError("use a password of at least 8 characters, and send it to them separately (by text)")
    if not hids:
        raise ProError("pick at least one client household")
    cid, salt = secrets.token_urlsafe(18), secrets.token_hex(16)
    con.execute("INSERT INTO coverage (id, sub_name, sub_email, start, \"end\", households, level, salt, pw_hash, created) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, sub_name[:60], sub_email[:200], start.isoformat(), end.isoformat(), json.dumps(hids), level,
                 salt, _hash(password, salt), now()))
    con.commit()
    return coverage_row(con, cid)


def coverage_row(con, cid: str) -> dict:
    r = con.execute("SELECT * FROM coverage WHERE id = ?", (cid,)).fetchone()
    if not r:
        raise ProError("no such coverage pack")
    d = {k: r[k] for k in r.keys() if k not in ("salt", "pw_hash")}
    d["households"] = json.loads(d["households"])
    return d


def coverage_open(con, cid: str, password: str, today: dt.date) -> dict:
    """The gate a backup chef passes: right password, inside the dates, not revoked."""
    r = con.execute("SELECT * FROM coverage WHERE id = ?", (cid,)).fetchone()
    if not r or r["revoked"]:
        raise ProError("this coverage pack isn't available")
    if not secrets.compare_digest(_hash(password or "", r["salt"]), r["pw_hash"]):
        raise ProError("wrong password")
    if today < dt.date.fromisoformat(r["start"]):
        raise ProError(f"this pack opens on {r['start']}")
    if today > dt.date.fromisoformat(r["end"]):
        raise ProError("this coverage pack has expired")
    con.execute("UPDATE coverage SET opened = opened + 1 WHERE id = ?", (cid,))
    con.commit()
    return coverage_row(con, cid)


def coverage_content(uid: str, row: dict, names: dict[str, str]) -> list[dict]:
    """Per household: access (full_operational only), the allergen matrix, preferences, the plan for the covered
    days with steps, open containers."""
    con = chef_db(uid)
    start, end = dt.date.fromisoformat(row["start"]), dt.date.fromisoformat(row["end"])
    out = []
    for hid in row["households"]:
        if hid not in names:
            continue                                            # the chef no longer works for them
        cl = client(con, hid)
        with tenant(hid):
            h = load_household()
            dz = dossier(h)
            c = catalog_mod.for_household(h)
            hc = store.connect()
            boxes = open_containers(hc)
            days = []
            d = start
            while d <= end:
                v = _today_visit(cl, DAYS[d.weekday()])
                if v:
                    rec = store.get_week(hc, week_start(d).isoformat())
                    meals = []
                    for e in (rec or {}).get("plan", {}).get("entries", []):
                        if e["day"] in v["covers"] and e.get("kind", "cook") == "cook":
                            r = c.recipes.get(e["recipe"])
                            meals.append({"name": e["name"], "servings": e["servings"],
                                          "steps": (r.instructions if r else [])[:12]})
                    days.append({"date": d.isoformat(), "arrive": v["arrive"], "leave": v["leave"], "meals": meals})
                d += dt.timedelta(days=1)
            hc.close()
        full = row["level"] == "full_operational"
        out.append({"name": dz["name"], "hazards": dz["hazards"], "people": dz["people"], "brands": dz["brands"],
                    "address": cl["address"] if full else None, "gate_code": cl["gate_code"] if full else None,
                    "access_notes": cl["access_notes"] if full else None, "emergency": cl["emergency"],
                    "kitchen_notes": cl["notes"], "days": days, "containers": boxes})
    con.close()
    return out


def coverage_html(row: dict, homes: list[dict], chef_name: str) -> str:
    import html as H
    e = H.escape
    css = ("body{font-family:Nunito,Arial,sans-serif;background:#FAF7F2;color:#2B231D;margin:0;padding:16px}"
           ".wrap{max-width:760px;margin:0 auto}.card{background:#FFFDF9;border:1px solid #E8E0D5;border-radius:24px;"
           "padding:18px;margin:14px 0;box-shadow:0 8px 24px rgba(43,35,29,.06)}h1{font-size:24px}h2{margin:0 0 6px}"
           ".warn{background:#FCE8E6;color:#9B2C24;border-radius:12px;padding:8px 12px;font-weight:800;margin:6px 0}"
           ".muted{color:#7A6F66;font-size:14px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid "
           "#E8E0D5;padding:6px;text-align:left;font-size:14px}.pill{background:#F6EFE6;color:#8E683E;border-radius:999px;"
           "padding:2px 10px;font-weight:800;font-size:12px}")
    parts = [f"<h1>Coverage pack</h1><p class='muted'>From {e(chef_name)} for {e(row['sub_name'])} · "
             f"{e(row['start'])} to {e(row['end'])} · <span class='pill'>{e(row['level'].replace('_', ' '))}</span></p>"]
    for hm in homes:
        hz = "".join(f"<div class='warn'>⚠ {e(x['text'])}</div>" for x in hm["hazards"]) or "<p class='muted'>No allergies listed.</p>"
        ppl = "".join(f"<tr><td>{e(p['name'])}</td><td>{e(', '.join(p['likes'][:4]))}</td>"
                      f"<td>{e(', '.join(p['dislikes'][:4]))}</td></tr>" for p in hm["people"])
        days = "".join(f"<h3>{e(d['date'])} · {e(d['arrive'])}–{e(d['leave'])}</h3>" + "".join(
            f"<p><b>{e(m['name'])}</b> ({m['servings']:g} servings)</p><ol>" + "".join(f"<li>{e(s)}</li>" for s in m["steps"])
            + "</ol>" for m in d["meals"]) for d in hm["days"]) or "<p class='muted'>No visits on these dates.</p>"
        access = ""
        if hm["address"] is not None:
            access = (f"<p><b>Address:</b> {e(hm['address'] or '—')}<br><b>Gate / door code:</b> {e(hm['gate_code'] or '—')}"
                      f"<br><b>Access:</b> {e(hm['access_notes'] or '—')}</p>")
        boxes = "".join(f"<tr><td>#{b['number']}</td><td>{e(b['dish'])}</td><td>{e(b['location'])}</td>"
                        f"<td>{e(b['use_by'])}</td></tr>" for b in hm["containers"])
        brands = ", ".join(f"{e(k)}: {e(v)}" for k, v in hm["brands"].items()) or "none listed"
        parts.append(f"<div class='card'><h2>{e(hm['name'])}</h2>{hz}{access}<p><b>Emergency:</b> {e(hm['emergency'] or '—')}</p>"
                     f"<p><b>Kitchen notes:</b> {e(hm['kitchen_notes'] or '—')}</p><p><b>Brands:</b> {brands}</p>"
                     f"<table><tr><th>Who</th><th>Likes</th><th>Dislikes</th></tr>{ppl}</table>{days}"
                     + (f"<h3>In the fridge</h3><table><tr><th>#</th><th>Dish</th><th>Where</th><th>Use by</th></tr>{boxes}</table>"
                        if boxes else "") + "</div>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta name='robots' content='noindex'><title>Coverage pack</title><style>{css}</style></head>"
            f"<body><div class='wrap'>{''.join(parts)}</div></body></html>")
