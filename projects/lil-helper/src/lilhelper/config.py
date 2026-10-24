"""Settings, the household's settings, stores and money: plain YAML anyone can read.

One server can hold many households. Each household lives in its own folder (warehouse/households/<id>/) with its
settings (household.yaml) and its database; `tenant()` points everything at one household for the length of a request
or a job. Without a tenant (the CLI, tests, the demo) the project folder is used, with config/household.yaml if it
exists, else the fictional example household.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import copy
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(os.getenv("LILHELPER_ROOT") or Path(__file__).resolve().parents[2])
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MEALS = ["breakfast", "lunch", "dinner"]
NIGHT_KINDS = ("cook", "leftovers", "takeout", "eat_out", "freezer")
ALLERGENS = ("peanut", "tree_nut", "dairy", "egg", "gluten", "soy", "fish", "shellfish", "sesame")
DIETS = ("vegetarian", "pescatarian", "no_pork")
MODES = ("in_store", "pickup", "delivery")

_tenant: ContextVar[Path | None] = ContextVar("lilhelper-tenant", default=None)


_cache: dict[Path, tuple[float, dict]] = {}


def _read(path: Path, fresh: bool = True) -> dict:
    """YAML, cached until the file changes (settings files are read on every call path). `fresh=False` returns the
    shared cached object for read-only config (stores, money): callers must not change it."""
    try:
        mt = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return copy.deepcopy(hit[1]) if fresh else hit[1]
    data = yaml.safe_load(path.read_text()) or {}
    _cache[path] = (mt, data)
    return copy.deepcopy(data) if fresh else data


def data_root() -> Path:
    """Where the server keeps every household (and the accounts database)."""
    return Path(os.getenv("HELPER_DATA") or ROOT / "warehouse")


def household_dir(hid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{6,32}", hid or ""):
        raise ValueError("bad household id")
    return data_root() / "households" / hid


@contextlib.contextmanager
def tenant(hid: str | None):
    """Run the block against one household's folder (settings, database, outputs)."""
    if not hid:
        yield None
        return
    d = household_dir(hid)
    d.mkdir(parents=True, exist_ok=True)
    tok = _tenant.set(d)
    try:
        yield d
    finally:
        _tenant.reset(tok)


def set_tenant(hid: str | None):
    """For request handlers: point at a household until the returned token is reset."""
    return _tenant.set(household_dir(hid) if hid else None)


def reset_tenant(tok) -> None:
    _tenant.reset(tok)


def current_tenant() -> Path | None:
    return _tenant.get()


def work_root() -> Path:
    """Where runs write (warehouse, output, logs): the household's folder, else the demo visitor's sandbox, else the
    project."""
    t = _tenant.get()
    if t is not None:
        return t
    from . import demo
    return demo.current() or ROOT


CHILD_UNDER = 12                         # under this age is a child: lighter jobs, kid portions


@dataclass
class Person:
    id: str
    name: str
    age_band: str
    portion: float = 1.0
    age: int | None = None
    allergies: list[str] = field(default_factory=list)
    diet: list[str] = field(default_factory=list)
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    home: list[str] = field(default_factory=lambda: list(DAYS))   # days home for dinner (and jobs)
    can_cook: bool = False
    email: str | None = None            # adults: where invites and sign-in links go
    admin: bool = False                 # can change the household's settings and invite people
    birthday: str | None = None         # "2014-03-07", or "03-07" without the year
    can_approve: bool | None = None     # under-18s can approve the week (spend) only if the admin says so

    @property
    def current_age(self) -> int | None:
        """From the birthday when it has a year; otherwise the age entered."""
        if self.birthday and len(self.birthday) == 10:
            b = dt.date.fromisoformat(self.birthday)
            t = dt.date.today()
            return t.year - b.year - ((t.month, t.day) < (b.month, b.day))
        return self.age

    @property
    def is_kid(self) -> bool:
        """A child is under 12 (from the birthday or age); without either, what the profile says."""
        a = self.current_age
        return a < CHILD_UNDER if a is not None else self.age_band == "kid"

    @property
    def is_teen(self) -> bool:
        a = self.current_age
        return a is not None and CHILD_UNDER <= a < 18

    @property
    def years(self) -> int:
        a = self.current_age
        return a if a is not None else (18 if not self.is_kid else 8)

    @property
    def may_approve(self) -> bool:
        """Approving the week leads to spending: adults, and teens the admin allows."""
        if self.is_kid:
            return False
        return bool(self.can_approve) if self.is_teen else self.can_approve is not False

    @property
    def role(self) -> str:
        if self.admin and not self.is_kid and not self.is_teen:
            return "admin"
        return "adult" if self.may_approve else "kid"

    def label(self, share_names: bool) -> str:
        """What a model sees: never a child's name unless the household opts in (DATA-03)."""
        if share_names:
            return self.name
        a = self.current_age
        if self.is_kid:
            return f"kid ({a})" if a else "kid"
        return f"teen ({a})" if self.is_teen else "adult"


@dataclass
class Pet:
    id: str
    name: str
    species: str
    weight_kg: float
    food: dict
    treats_per_day: int
    kcal_per_day: float
    extras: bool
    vet_notes: str = ""


@dataclass
class Household:
    raw: dict
    people: dict[str, Person]
    pets: dict[str, Pet]
    # this week's changes made in the app: who's away (day → person ids), and nights changed to takeout etc.
    away: dict[str, set[str]] = field(default_factory=dict)
    night_overrides: dict[str, str] = field(default_factory=dict)
    week_of: "dt.date | None" = None        # the week being planned (occasions and birthdays need dates)

    @property
    def info(self) -> dict:
        return self.raw["household"]

    def date_of(self, day: str) -> "dt.date | None":
        return self.week_of + dt.timedelta(days=DAYS.index(day)) if self.week_of and day in DAYS else None

    def occasions(self, day: str) -> list[dict]:
        from . import occasions
        d = self.date_of(day)
        return occasions.on_day(self.raw, self.people, d) if d else []

    def off_duty(self, day: str) -> set[str]:
        """People with no jobs that day: it's their birthday."""
        return {pid for o in self.occasions(day) if o["kind"] == "birthday" for pid in o["people"]}

    @property
    def meals(self) -> dict:
        return self.raw["meals"]

    def eaters(self, meal: str, day: str | None = None) -> list[Person]:
        """Who eats this meal; on a given day, only people home (their `home` days) and not marked away."""
        e = self.meals.get(meal, {}).get("eaters", "all")
        base = list(self.people.values()) if e == "all" else [self.people[p] for p in e if p in self.people]
        if day is None:
            return base
        gone = self.away.get(day, set())
        return [p for p in base if (meal == "lunch" or day in p.home) and p.id not in gone]

    def everyone_allergies(self) -> set[str]:
        """Allergies anywhere in the house: a shared kitchen and leftovers mean these apply to every meal."""
        return {a for p in self.people.values() for a in p.allergies}

    def slots(self) -> list[tuple[str, str]]:
        """(day, meal) pairs to plan, in calendar order, excluding nights that aren't cooked and meals nobody's home for."""
        special = self.special_nights()
        buffet = {m for m, v in (self.raw.get("buffet") or {}).items() if v and v.get("on")}
        out = []
        for day in DAYS:
            for meal in MEALS:
                if meal in buffet:
                    continue                               # kept as a buffet: portions on hand, no recipe per day
                cfg = self.meals.get(meal)
                if cfg and day in cfg.get("days", []) and not (meal == "dinner" and day in special) \
                        and self.eaters(meal, day):
                    out.append((day, meal))
        return out

    def special_nights(self) -> dict[str, str]:
        """day → leftovers | takeout | eat_out | freezer: dinners that aren't cooked from the plan this week."""
        base = {d: k for d, k in (self.meals.get("special_nights", {}) or {}).items() if k}
        base.update(self.night_overrides)
        return {d: k for d, k in base.items() if k != "cook"}

    def eating_out(self) -> dict[str, dict]:
        """Budgets and how for nights that aren't cooked at home, e.g. takeout: {budget: 55, service: uber_eats}."""
        return dict(self.raw.get("eating_out", {}) or {})

    def cooked_dinner_days(self) -> list[str]:
        special = self.special_nights()
        days = (self.meals.get("dinner") or {}).get("days", [])
        return [d for d in DAYS if d in days and d not in special]

    def leftover_lunches(self) -> dict[str, str]:
        """lunch day → the day whose dinner feeds it (only when that dinner is cooked earlier in the same week)."""
        cfg = (self.raw.get("leftovers") or {}).get("lunch") or {}
        cooked = set(self.cooked_dinner_days())
        out = {}
        for d in cfg.get("days", []):
            i = DAYS.index(d)
            if i > 0 and DAYS[i - 1] in cooked:
                out[d] = DAYS[i - 1]
        return out

    def leftover_eaters(self) -> list[Person]:
        cfg = (self.raw.get("leftovers") or {}).get("lunch") or {}
        return [self.people[p] for p in cfg.get("eaters", []) if p in self.people]

    def extra_portions(self) -> float:
        return float((self.raw.get("leftovers") or {}).get("extra_portions", 0) or 0)

    def styles(self, key: str) -> dict:
        """Recipe tags to require or prefer, keyed by day (for dinner) or by meal: {require: [...], prefer: [...]}."""
        return (self.raw.get("styles") or {}).get(key) or {}

    def kid_chef(self) -> dict[str, str]:
        """day → the kid who cooks dinner that night (with an adult helping)."""
        return {d: p for d, p in (self.raw.get("kid_chef") or {}).items() if p in self.people}

    def dinner_time(self, day: str) -> str:
        t = self.raw.get("dinner_times") or {}
        return str(t.get(day) or t.get("default") or "18:00")

    def cost_range(self, meal: str) -> tuple[float | None, float | None]:
        """(min, max) dollars per serving for this meal: the meal's own range, else the household's."""
        r = (self.meals.get(meal) or {}).get("cost_per_serving") or self.raw.get("cost_per_serving") or {}
        lo, hi = r.get("min"), r.get("max")
        return (float(lo) if lo is not None else None, float(hi) if hi is not None else None)

    def storage(self) -> dict:
        """Litres of fridge and freezer space, and how full is comfortable."""
        s = dict(self.raw.get("storage") or {})
        s.setdefault("fridge_l", 500)
        s.setdefault("freezer_l", 200)
        s.setdefault("fill_target", 0.8)
        return s

    def freezer_meals(self) -> dict:
        return dict(self.raw.get("freezer_meals") or {})

    def sessions(self) -> list[dict]:
        """Planned shopping trips and orders: [{id, day, time, store, mode, who}]. Empty: DinnerPeace picks."""
        return [dict(s, id=s.get("id") or f"{s['store']}-{s['mode']}-{s['day']}")
                for s in (self.raw.get("shopping_sessions") or [])]

    def prep_limit(self, day: str) -> int:
        return int(self.raw.get("prep_minutes", {}).get(day, 60))

    def admins(self) -> list[Person]:
        return [p for p in self.people.values() if p.role == "admin"]


def household_path() -> Path:
    t = _tenant.get()
    if t is not None:
        return t / "household.yaml"
    p = ROOT / Settings.load()["household_file"]
    return p if p.exists() else ROOT / "config" / "household.example.yaml"


def parse_household(raw: dict) -> Household:
    s = Settings.load()
    validate_household(raw, s)
    people = {pid: Person(id=pid, **{k: v for k, v in d.items() if k in Person.__dataclass_fields__})
              for pid, d in raw["people"].items()}
    pets = {pid: Pet(id=pid, name=d["name"], species=d.get("species", "dog"), weight_kg=d.get("weight_kg", 0),
                     food=d["food"], treats_per_day=d.get("treats_per_day", 0), kcal_per_day=d.get("kcal_per_day", 0),
                     extras=d.get("extras", False), vet_notes=d.get("vet_notes", "") or "")
            for pid, d in (raw.get("pets") or {}).items()}
    return Household(raw, people, pets)


def load_household(path: Path | None = None) -> Household:
    return parse_household(_read(path or household_path()))


def save_household(raw: dict) -> Household:
    """Validate and write the current household's settings (atomically). Returns the parsed household."""
    h = parse_household(copy.deepcopy(raw))
    p = household_path()
    if _tenant.get() is None and p.name == "household.example.yaml":
        raise HouseholdError("no household selected; the example household is read-only")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=120))
    tmp.replace(p)
    return h


class HouseholdError(ValueError):
    pass


def validate_household(raw: dict, s: "Settings") -> None:
    """Refuse settings that hold card numbers, name people or days that don't exist, or make no sense."""
    pat = re.compile(s["privacy"]["card_number_pattern"])
    for c in raw.get("cards", []) or []:
        if pat.search(str(c)):
            raise HouseholdError("A card field looks like a card number. Use a name you'd recognise, never the number.")
        if isinstance(c, dict):
            _check_card(c, raw)
    bad = set(raw.get("delivery_services") or []) - set(delivery()["services"])
    if bad:
        raise HouseholdError(f"unknown delivery services {sorted(bad)}")
    _check_address(raw.get("address"))
    if sum(1 for c in raw.get("cards", []) or [] if isinstance(c, dict) and c.get("primary")) > 1:
        raise HouseholdError("only one card can be your primary card")
    if not isinstance(raw.get("household"), dict) or not isinstance(raw.get("people"), dict) or not raw["people"]:
        raise HouseholdError("settings need a household section and at least one person")
    for site in raw.get("recipe_sources") or []:
        if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", str(site)):
            raise HouseholdError(f"recipe sources are website names like marthastewart.com, not {site!r}")
    for i, o in enumerate(raw.get("occasions") or []):
        d = str(o.get("date", ""))
        try:
            ok = bool(re.fullmatch(r"(\d{4}-)?\d{2}-\d{2}", d)) and bool(
                dt.date.fromisoformat(d if len(d) == 10 else f"2000-{d}"))
        except ValueError:
            ok = False
        if not o.get("name") or not ok:
            raise HouseholdError(f"occasion {i + 1}: needs a name and a real date (YYYY-MM-DD or MM-DD)")
        if o.get("kind", "custom") not in ("anniversary", "holiday", "custom", "birthday", "party"):
            raise HouseholdError(f"occasion {o['name']}: kind is anniversary, party, holiday or custom")
        for who in o.get("people") or []:
            if who not in raw["people"]:
                raise HouseholdError(f"occasion {o['name']}: unknown person {who!r}")
    for iid, pref in (raw.get("ingredient_prefs") or {}).items():
        if not isinstance(pref, dict) or (pref.get("store") and pref["store"] not in (raw.get("stores") or [])):
            raise HouseholdError(f"{iid}: the store for this item must be one of your stores")
        if pref.get("price") is not None and not 0 < float(pref["price"]) <= 1000:
            raise HouseholdError(f"{iid}: price must be between 0 and 1000")
    from .occasions import HOLIDAYS
    for hid in raw.get("holidays_off") or []:
        if hid not in HOLIDAYS:
            raise HouseholdError(f"unknown holiday {hid!r}")
    tz = raw["household"].get("timezone")
    if tz is not None:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(str(tz))
        except Exception:
            raise HouseholdError(f"unknown time zone {tz!r} (use a name like America/New_York)")
    if not isinstance(raw.get("meals"), dict):
        raise HouseholdError("settings need a meals section")
    people = set(raw.get("people", {}))
    for pid, p in raw["people"].items():
        if not re.fullmatch(r"[a-z0-9_]{1,32}", str(pid)):
            raise HouseholdError(f"person id {pid!r}: lowercase letters, digits and _ only")
        if p.get("age_band") not in ("adult", "kid"):
            raise HouseholdError(f"{pid}: age_band must be adult or kid")
        bad = set(p.get("allergies") or []) - set(ALLERGENS)
        if bad:
            raise HouseholdError(f"{pid}: unknown allergies {sorted(bad)}; use {', '.join(ALLERGENS)}")
        bad = set(p.get("diet") or []) - set(DIETS)
        if bad:
            raise HouseholdError(f"{pid}: unknown diets {sorted(bad)}; use {', '.join(DIETS)}")
        if set(p.get("home") or []) - set(DAYS):
            raise HouseholdError(f"{pid}: home days must be mon..sun")
        if p.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", p["email"]):
            raise HouseholdError(f"{pid}: that email doesn't look right")
        bday = p.get("birthday")
        if bday is not None:
            if not re.fullmatch(r"(\d{4}-)?\d{2}-\d{2}", str(bday)):
                raise HouseholdError(f"{pid}: birthday as YYYY-MM-DD (or MM-DD)")
            try:
                dt.date.fromisoformat(str(bday) if len(str(bday)) == 10 else f"2000-{bday}")
            except ValueError:
                raise HouseholdError(f"{pid}: that birthday isn't a real date")
            if len(str(bday)) == 10 and dt.date.fromisoformat(str(bday)) > dt.date.today():
                raise HouseholdError(f"{pid}: a birthday can't be in the future")
        person = Person(id=pid, **{k: v for k, v in p.items() if k in Person.__dataclass_fields__})
        if p.get("admin") and (person.is_kid or person.is_teen):
            raise HouseholdError(f"{pid}: the household admin needs to be an adult")
        if pat.search(str(p.get("name", ""))):
            raise HouseholdError(f"{pid}: that name looks like a card number")
    if not any(p.get("admin") for p in raw["people"].values()) and raw.get("require_admin", False):
        raise HouseholdError("someone has to be the household admin")
    for meal, cfg in (raw.get("meals") or {}).items():
        if meal == "special_nights":
            for d, k in (cfg or {}).items():
                if d not in DAYS or (k and k not in NIGHT_KINDS):
                    raise HouseholdError(f"special night {d}: {k!r} isn't one of {', '.join(NIGHT_KINDS)}")
            continue
        if meal not in MEALS or not isinstance(cfg, dict):
            raise HouseholdError(f"meals: {meal!r} isn't breakfast, lunch or dinner")
        if set(cfg.get("days") or []) - set(DAYS):
            raise HouseholdError(f"{meal}: days must be mon..sun")
        if isinstance(cfg.get("eaters"), list):
            unknown = set(cfg["eaters"]) - people
            if unknown:
                raise HouseholdError(f"{meal}: unknown eaters {sorted(unknown)}")
    for key in ("cost_per_serving",):
        r = raw.get(key) or {}
        if r.get("min") is not None and r.get("max") is not None and float(r["min"]) > float(r["max"]):
            raise HouseholdError("cost per serving: min is above max")
    for t in (raw.get("dinner_times") or {}).values():
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(t)):
            raise HouseholdError(f"dinner time {t!r}: use 24-hour HH:MM")
    known_stores = set(stores()["stores"])
    for sess in raw.get("shopping_sessions") or []:
        if sess.get("store") not in known_stores:
            raise HouseholdError(f"shopping session: unknown store {sess.get('store')!r}")
        if sess.get("mode") not in MODES:
            raise HouseholdError(f"shopping session: mode must be one of {', '.join(MODES)}")
        if sess.get("mode") not in stores()["stores"][sess["store"]]["modes"]:
            raise HouseholdError(f"{stores()['stores'][sess['store']]['name']} doesn't offer {sess['mode']}")
        if sess.get("day") not in DAYS + ["sun_before", "sat_before"]:
            raise HouseholdError("shopping session: day must be mon..sun (or sun_before)")
        if sess.get("who") and sess["who"] not in people:
            raise HouseholdError(f"shopping session: unknown person {sess['who']!r}")
    for d, p in (raw.get("kid_chef") or {}).items():
        if d not in DAYS or p not in people:
            raise HouseholdError(f"kid chef: {d} / {p} not recognised")
    st = raw.get("storage") or {}
    for k in ("fridge_l", "freezer_l"):
        if k in st and not (0 <= float(st[k]) <= 5000):
            raise HouseholdError(f"storage {k}: 0–5000 litres")


def _check_address(a) -> None:
    if not a:
        return
    if not isinstance(a, dict):
        raise HouseholdError("the address is a set of fields: line1, city, state, zip")
    for k in ("line1", "line2", "city", "state", "zip"):
        if a.get(k) is not None and len(str(a[k])) > 120:
            raise HouseholdError(f"address {k} is too long")
    if a.get("zip") and not re.fullmatch(r"\d{5}(-\d{4})?", str(a["zip"])):
        raise HouseholdError("a US ZIP code is 5 digits (or ZIP+4)")
    if a.get("state") and not re.fullmatch(r"[A-Za-z]{2}", str(a["state"])):
        raise HouseholdError("use the two-letter state, like CT")
    for k, lo, hi in (("lat", -90, 90), ("lon", -180, 180)):
        if a.get(k) is not None and not lo <= float(a[k]) <= hi:
            raise HouseholdError(f"address {k} is out of range")


def _check_card(c: dict, raw: dict) -> None:
    name = c.get("name") or c.get("template") or c.get("id") or "a card"
    if not (c.get("id") or c.get("template")) or not re.fullmatch(r"[a-z0-9_]{1,40}", str(c.get("id") or c.get("template"))):
        raise HouseholdError(f"{name}: needs an id (lowercase letters, numbers, _)")
    if c.get("last4") and not re.fullmatch(r"\d{4}", str(c["last4"])):
        raise HouseholdError(f"{name}: last 4 digits only, never the full number")
    if c.get("expires"):
        m = re.fullmatch(r"(20\d\d)-(0[1-9]|1[0-2])", str(c["expires"]))
        if not m:
            raise HouseholdError(f"{name}: expiry is year and month, like 2028-07")
    for k in ("credit_limit", "monthly_limit"):
        if c.get(k) not in (None, "") and not 0 < float(c[k]) <= 1_000_000:
            raise HouseholdError(f"{name}: {k.replace('_', ' ')} must be a positive amount")
    for st in c.get("stores") or []:
        if st not in (raw.get("stores") or []) and st not in stores()["stores"]:
            raise HouseholdError(f"{name}: unknown store {st!r}")
    for cat, rule in (c.get("earn") or {}).items():
        if not isinstance(rule, dict) or not ("pct" in rule or "points" in rule):
            raise HouseholdError(f"{name}: each reward needs pct (0.03 = 3%) or points per dollar")
        v = float(rule.get("pct", rule.get("points", 0)))
        if not 0 <= v <= (0.2 if "pct" in rule else 20):
            raise HouseholdError(f"{name}: a {cat} reward of {v} doesn't look right")
        if rule.get("annual_cap") not in (None, "") and float(rule["annual_cap"]) <= 0:
            raise HouseholdError(f"{name}: an annual cap must be positive")
    for cr in c.get("credits") or []:
        if not cr.get("name") or not 0 <= float(cr.get("monthly", 0)) <= 500:
            raise HouseholdError(f"{name}: each credit needs a name and a monthly amount")


class Settings(dict):
    @classmethod
    def load(cls) -> "Settings":
        return cls(_read(ROOT / "config" / "settings.yaml"))


def delivery() -> dict:
    return _read(ROOT / "config" / "delivery.yaml", fresh=False)


def stores() -> dict:
    """Read-only (shared): don't change what this returns."""
    return _read(ROOT / "config" / "stores.yaml", fresh=False)


def money() -> dict:
    """Read-only (shared): don't change what this returns."""
    return _read(ROOT / "config" / "money.yaml", fresh=False)
