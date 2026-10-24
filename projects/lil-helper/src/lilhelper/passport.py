"""Location privacy, the portable Household Food Passport, and client engagements (the marketplace's private side).

Three records:
  HouseholdLocation      the street address, door or gate code and access notes (in the household's own settings),
                         and a fuzzy public point (in the accounts database) made once by generate_fuzzy_coordinates
  HouseholdFoodPassport  what any chef needs to cook safely for the family, built from its settings: allergies first,
                         diets, likes, dislikes, brands, kitchen notes. Portable: the family can grant it to a chef
                         they're talking to, revoke it, export it, and take it to a new chef when they switch
  ClientEngagement       one chef and one household: inquiry → trial_scheduled → active (→ paused) → ended

PassportAccessService decides who sees what, on the server, on every read:
  anyone signed in   the public card: town, fuzzy distance, size, allergen types (marketplace listing)
  a granted chef     + the food passport (first names, ages, likes/dislikes, brands); never the address
  an engaged chef    + street address, gate code and access notes — only while the engagement is trial_scheduled
                     or active, whatever any grant says
  the household      everything about itself
Every read of a private part is written to an access log the household can see.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import os
import secrets
from dataclasses import asdict, dataclass, field  # noqa: F401  (asdict is used by the API too)

from . import accounts, geo
from .config import load_household, tenant

ADDRESS_STATUSES = frozenset({"trial_scheduled", "active"})
STATUSES = ("inquiry", "trial_scheduled", "active", "paused", "ended", "declined")
TRANSITIONS = {
    "inquiry": {"trial_scheduled", "active", "declined", "ended"},
    "trial_scheduled": {"active", "inquiry", "declined", "ended"},
    "active": {"paused", "ended"},
    "paused": {"active", "ended"},
    "ended": set(), "declined": set(),
}
SCOPES = ("passport",)            # what a household can grant; the address is never grantable on its own
GRID_DEG = 0.01                   # ~1.1 km north–south: the snap grid
RING_M = (300.0, 900.0)           # then a fixed offset 300–900 m away, the same every time for this household
EARTH_M = 6_371_000.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS household_locations (hid TEXT PRIMARY KEY, fuzzy_lat REAL, fuzzy_lng REAL, city TEXT,
    state TEXT, zip3 TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS engagements (id TEXT PRIMARY KEY, chef_uid TEXT, hid TEXT, status TEXT, trial_at TEXT,
    started TEXT, ended TEXT, rate_per_visit REAL, request_id TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS passport_grants (hid TEXT, chef_uid TEXT, scope TEXT, granted_by TEXT, granted TEXT,
    revoked TEXT, PRIMARY KEY (hid, chef_uid, scope));
CREATE TABLE IF NOT EXISTS passport_access (ts TEXT, hid TEXT, viewer TEXT, parts TEXT);
"""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def setup(con) -> None:
    con.executescript(SCHEMA)


# ---------------------------------------------------------------- data models
@dataclass
class HouseholdLocation:
    household_id: str
    street: str = ""
    unit: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    lat: float | None = None
    lng: float | None = None
    gate_code: str = ""
    access_notes: str = ""
    fuzzy_lat: float | None = None
    fuzzy_lng: float | None = None

    def public(self) -> dict:
        """The only parts that may leave the server for someone without an engagement."""
        return {"city": self.city, "state": self.state, "fuzzy_lat": self.fuzzy_lat, "fuzzy_lng": self.fuzzy_lng}

    def private(self) -> dict:
        return {"street": self.street, "unit": self.unit, "city": self.city, "state": self.state, "zip": self.zip,
                "lat": self.lat, "lng": self.lng, "gate_code": self.gate_code, "access_notes": self.access_notes}


@dataclass
class PassportPerson:
    first_name: str
    child: bool
    age: int | None
    allergies: list[str] = field(default_factory=list)
    diet: list[str] = field(default_factory=list)
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)


@dataclass
class HouseholdFoodPassport:
    household_id: str
    household_name: str
    version: str
    allergens: list[str]
    people: list[PassportPerson]
    brands: dict[str, str]
    kitchen_notes: str = ""
    pets: list[str] = field(default_factory=list)
    generated: str = field(default_factory=now)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClientEngagement:
    id: str
    chef_uid: str
    household_id: str
    status: str
    trial_at: str | None = None
    started: str | None = None
    ended: str | None = None
    rate_per_visit: float | None = None
    request_id: str | None = None
    created: str = ""
    updated: str = ""

    @property
    def shows_address(self) -> bool:
        return self.status in ADDRESS_STATUSES


# ---------------------------------------------------------------- fuzzy coordinates
def _secret() -> bytes:
    return (os.getenv("HELPER_SECRET") or "dev-only-not-secret").encode()


def generate_fuzzy_coordinates(lat: float, lng: float, seed: str = "") -> tuple[float, float]:
    """A public stand-in for a home: snap to a ~1 km grid, then move 300–900 m in a direction and distance fixed by
    `seed` (the household id, keyed with the server secret), rounded to 3 decimals (~100 m).

    The same household always gets the same point, so asking again and averaging the answers gets nobody closer;
    the grid snap means moving house a street away changes nothing public; and the offset means the grid corner
    itself isn't the answer either. The true point is never returned to anyone outside the engagement.
    """
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("coordinates out of range")
    glat = (math.floor(lat / GRID_DEG) + 0.5) * GRID_DEG
    glng = (math.floor(lng / GRID_DEG) + 0.5) * GRID_DEG
    h = hmac.new(_secret(), f"fuzz|{seed}|{glat:.4f}|{glng:.4f}".encode(), hashlib.sha256).digest()
    u1 = int.from_bytes(h[:8], "big") / 2 ** 64
    u2 = int.from_bytes(h[8:16], "big") / 2 ** 64
    bearing = 2 * math.pi * u1
    dist = RING_M[0] + (RING_M[1] - RING_M[0]) * u2
    dlat = math.degrees(dist * math.cos(bearing) / EARTH_M)
    dlng = math.degrees(dist * math.sin(bearing) / (EARTH_M * max(0.01, math.cos(math.radians(glat)))))
    return round(max(-90.0, min(90.0, glat + dlat)), 3), round((glng + dlng + 180) % 360 - 180, 3)


def fuzzy_miles(a: tuple[float, float] | None, b: tuple[float, float] | None) -> int | None:
    """Distance shown to people: whole miles between fuzzy points, never under 1."""
    if not a or not b:
        return None
    return max(1, round(geo.miles(a, b)))


# ---------------------------------------------------------------- reading a household's records
def location(hid: str) -> HouseholdLocation:
    with tenant(hid):
        raw = load_household().raw
    a, acc = raw.get("address") or {}, raw.get("access") or {}
    con = accounts.connect()
    setup(con)
    r = con.execute("SELECT * FROM household_locations WHERE hid = ?", (hid,)).fetchone()
    con.close()
    return HouseholdLocation(hid, a.get("line1", ""), a.get("line2", ""), a.get("city", ""), a.get("state", ""),
                             a.get("zip", ""), a.get("lat"), a.get("lon"), str(acc.get("gate_code") or ""),
                             str(acc.get("notes") or ""), r["fuzzy_lat"] if r else None, r["fuzzy_lng"] if r else None)


def refresh_location(con, hid: str, address: dict) -> dict:
    """After the household saves its address: store only the fuzzy point, town and ZIP prefix centrally."""
    setup(con)
    f = (generate_fuzzy_coordinates(float(address["lat"]), float(address["lon"]), hid)
         if address.get("lat") is not None and address.get("lon") is not None else (None, None))
    con.execute("INSERT OR REPLACE INTO household_locations VALUES (?,?,?,?,?,?,?)",
                (hid, f[0], f[1], address.get("city", ""), (address.get("state") or "").upper(),
                 str(address.get("zip") or "")[:3], now()))
    con.commit()
    return {"fuzzy_lat": f[0], "fuzzy_lng": f[1]}


def public_point(con, hid: str) -> tuple[float, float] | None:
    setup(con)
    r = con.execute("SELECT fuzzy_lat, fuzzy_lng FROM household_locations WHERE hid = ?", (hid,)).fetchone()
    return (r["fuzzy_lat"], r["fuzzy_lng"]) if r and r["fuzzy_lat"] is not None else None


def food_passport(hid: str) -> HouseholdFoodPassport:
    from . import catalog
    with tenant(hid):
        h = load_household()
        c = catalog.for_household(h)
    name = lambda x: c.ingredients[x].name if x in c.ingredients else (c.recipes[x].name if x in c.recipes else x)
    people = [PassportPerson(p.name.split()[0], p.is_kid, p.current_age, list(p.allergies), list(p.diet),
                             [name(x) for x in p.likes], [name(x) for x in p.dislikes]) for p in h.people.values()]
    brands = {name(k): (v or {}).get("prefer") for k, v in (h.raw.get("brands") or {}).items() if (v or {}).get("prefer")}
    brands |= {name(k): v["brand"] for k, v in (h.raw.get("ingredient_prefs") or {}).items() if v.get("brand")}
    body = json.dumps([asdict(p) for p in people], sort_keys=True) + json.dumps(brands, sort_keys=True)
    return HouseholdFoodPassport(hid, h.info.get("name", ""), hashlib.sha256(body.encode()).hexdigest()[:12],
                                 sorted(h.everyone_allergies()), people, brands,
                                 str((h.raw.get("access") or {}).get("kitchen_notes") or ""),
                                 [pt.name for pt in h.pets.values()])


# ---------------------------------------------------------------- engagements
def _eng(row) -> ClientEngagement:
    return ClientEngagement(row["id"], row["chef_uid"], row["hid"], row["status"], row["trial_at"], row["started"],
                            row["ended"], row["rate_per_visit"], row["request_id"], row["created"], row["updated"])


def engagement(con, chef_uid: str, hid: str) -> ClientEngagement | None:
    """The current (not ended or declined) engagement between a chef and a household, if any."""
    setup(con)
    r = con.execute("SELECT * FROM engagements WHERE chef_uid = ? AND hid = ? AND status NOT IN ('ended', 'declined') "
                    "ORDER BY created DESC LIMIT 1", (chef_uid, hid)).fetchone()
    return _eng(r) if r else None


def get_engagement(con, eid: str) -> ClientEngagement:
    setup(con)
    r = con.execute("SELECT * FROM engagements WHERE id = ?", (eid,)).fetchone()
    if not r:
        raise ValueError("no such engagement")
    return _eng(r)


def engagements_for(con, *, chef_uid: str | None = None, hid: str | None = None) -> list[ClientEngagement]:
    setup(con)
    q, a = ("SELECT * FROM engagements WHERE chef_uid = ?", (chef_uid,)) if chef_uid else \
        ("SELECT * FROM engagements WHERE hid = ?", (hid,))
    return [_eng(r) for r in con.execute(q + " ORDER BY created DESC", a)]


def open_engagement(con, chef_uid: str, hid: str, status: str = "inquiry", request_id: str | None = None,
                    rate: float | None = None) -> ClientEngagement:
    setup(con)
    cur = engagement(con, chef_uid, hid)
    if cur:
        return cur
    if status not in ("inquiry", "active"):
        raise ValueError("an engagement starts as an inquiry (or active, for a chef the family invited directly)")
    eid = secrets.token_hex(6)
    con.execute("INSERT INTO engagements VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (eid, chef_uid, hid, status, None, now() if status == "active" else None, None, rate, request_id,
                 now(), now()))
    con.commit()
    return get_engagement(con, eid)


def move(con, eid: str, to: str, *, trial_at: str | None = None, rate: float | None = None) -> ClientEngagement:
    e = get_engagement(con, eid)
    if to not in STATUSES:
        raise ValueError(f"status is one of {', '.join(STATUSES)}")
    if to != e.status and to not in TRANSITIONS[e.status]:
        raise ValueError(f"an engagement can't go from {e.status} to {to}")
    if to == "trial_scheduled":
        if not trial_at:
            raise ValueError("a trial needs a date and time")
        try:
            dt.datetime.fromisoformat(trial_at)
        except ValueError:
            raise ValueError("the trial time looks like 2026-11-03T16:00")
    if rate is not None and not 0 <= rate <= 5000:
        raise ValueError("a rate per visit between $0 and $5,000")
    con.execute("UPDATE engagements SET status = ?, trial_at = COALESCE(?, trial_at), rate_per_visit = COALESCE(?, rate_per_visit), "
                "started = CASE WHEN ? = 'active' AND started IS NULL THEN ? ELSE started END, "
                "ended = CASE WHEN ? IN ('ended', 'declined') THEN ? ELSE ended END, updated = ? WHERE id = ?",
                (to, trial_at, rate, to, now(), to, now(), now(), eid))
    con.commit()
    return get_engagement(con, eid)


def end_all(con, chef_uid: str, hid: str) -> None:
    setup(con)
    con.execute("UPDATE engagements SET status = 'ended', ended = ?, updated = ? WHERE chef_uid = ? AND hid = ? "
                "AND status NOT IN ('ended', 'declined')", (now(), now(), chef_uid, hid))
    con.commit()


# ---------------------------------------------------------------- grants
def grant(con, hid: str, chef_uid: str, by: str, scope: str = "passport") -> None:
    if scope not in SCOPES:
        raise ValueError("only the food passport can be granted; the address follows the engagement")
    setup(con)
    con.execute("INSERT OR REPLACE INTO passport_grants VALUES (?,?,?,?,?,NULL)", (hid, chef_uid, scope, by, now()))
    con.commit()


def revoke(con, hid: str, chef_uid: str, scope: str = "passport") -> None:
    setup(con)
    con.execute("UPDATE passport_grants SET revoked = ? WHERE hid = ? AND chef_uid = ? AND scope = ?",
                (now(), hid, chef_uid, scope))
    con.commit()


def grants(con, hid: str) -> list[dict]:
    setup(con)
    return [dict(r) for r in con.execute("SELECT * FROM passport_grants WHERE hid = ? ORDER BY granted DESC", (hid,))]


def access_log(con, hid: str, limit: int = 50) -> list[dict]:
    setup(con)
    return [dict(r) for r in con.execute("SELECT * FROM passport_access WHERE hid = ? ORDER BY ts DESC LIMIT ?",
                                         (hid, limit))]


# ---------------------------------------------------------------- the access service
class AccessDenied(PermissionError):
    pass


class PassportAccessService:
    """One place that decides what a viewer may see of a household. Call `view`; never read the records directly
    for someone outside the household."""

    def __init__(self, con):
        self.con = con
        setup(con)

    def relation(self, viewer_uid: str, hid: str) -> dict:
        m = accounts.membership(self.con, viewer_uid, hid)
        member = bool(m and m["role"] != "chef")
        eng = engagement(self.con, viewer_uid, hid)
        if m and m["role"] == "chef" and eng is None and not self.con.execute(
                "SELECT 1 FROM engagements WHERE chef_uid = ? AND hid = ?", (viewer_uid, hid)).fetchone():
            eng = open_engagement(self.con, viewer_uid, hid, "active")      # a chef hired before engagements existed
        g = self.con.execute("SELECT 1 FROM passport_grants WHERE hid = ? AND chef_uid = ? AND scope = 'passport' "
                             "AND revoked IS NULL", (hid, viewer_uid)).fetchone()
        return {"member": member, "engagement": eng, "granted": bool(g)}

    def can_see_address(self, viewer_uid: str, hid: str) -> bool:
        r = self.relation(viewer_uid, hid)
        return r["member"] or bool(r["engagement"] and r["engagement"].shows_address)

    def can_see_passport(self, viewer_uid: str, hid: str) -> bool:
        r = self.relation(viewer_uid, hid)
        return r["member"] or r["granted"] or bool(r["engagement"] and r["engagement"].shows_address)

    def view(self, viewer_uid: str, hid: str) -> dict:
        """The payload for this viewer: always the public card; the passport and the address only as allowed."""
        rel = self.relation(viewer_uid, hid)
        loc = location(hid)
        out: dict = {"household_id": hid, "public": loc.public(), "passport": None, "location": None,
                     "engagement": asdict(rel["engagement"]) if rel["engagement"] else None,
                     "access": {"passport": False, "address": False}}
        parts = []
        if self.can_see_passport(viewer_uid, hid):
            out["passport"] = food_passport(hid).to_dict()
            out["access"]["passport"] = True
            parts.append("passport")
        if self.can_see_address(viewer_uid, hid):
            out["location"] = loc.private()
            out["access"]["address"] = True
            parts.append("address")
        if parts and not rel["member"]:
            self.con.execute("INSERT INTO passport_access VALUES (?,?,?,?)", (now(), hid, viewer_uid, ",".join(parts)))
            self.con.commit()
        return out

    def private_location(self, viewer_uid: str, hid: str) -> dict:
        """The street, gate code and access notes, or AccessDenied."""
        if not self.can_see_address(viewer_uid, hid):
            raise AccessDenied("the address is shared only with a chef whose trial is scheduled or who is working "
                               "for the household")
        if not self.relation(viewer_uid, hid)["member"]:
            self.con.execute("INSERT INTO passport_access VALUES (?,?,?,?)", (now(), hid, viewer_uid, "address"))
            self.con.commit()
        return location(hid).private()
