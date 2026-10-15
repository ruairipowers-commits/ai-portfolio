"""People and households on one server: sign-up, roles, invites, devices, deletion.

A central database (accounts.sqlite under HELPER_DATA) holds only what's needed to sign people in and route them to
their household: email, display name, which households they belong to and as whom. Everything about meals, money and
children lives in the household's own folder and database.

Roles (per household):
  admin   sets the household up and changes its settings, adds and edits people, invites and removes members
  adult   plans, approves, shops, records spending, adds recipes and specials
  kid     sees the week and their jobs, says how much was eaten and rates meals (optional: kids don't need accounts)

Sign-up (HELPER_SIGNUP): `invite` (default) — a new household needs a sign-up code (HELPER_SIGNUP_CODES), anyone can
join an existing household they're invited to; `open` — anyone can create a household (the App Store release);
`closed` — invitations only.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import shutil
import sqlite3

import yaml

from .config import ROOT, data_root, household_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, created TEXT,
    feed_salt TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS households (id TEXT PRIMARY KEY, name TEXT, created TEXT, created_by TEXT,
    plan TEXT DEFAULT 'beta', plan_until TEXT, status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS members (household_id TEXT, user_id TEXT, person_id TEXT, role TEXT, joined TEXT,
    PRIMARY KEY (household_id, user_id));
CREATE TABLE IF NOT EXISTS invites (code TEXT PRIMARY KEY, household_id TEXT, email TEXT, person_id TEXT, role TEXT,
    created_by TEXT, created TEXT, expires TEXT, used_by TEXT, used_at TEXT);
CREATE TABLE IF NOT EXISTS devices (token TEXT PRIMARY KEY, user_id TEXT, household_id TEXT, platform TEXT,
    created TEXT, last_seen TEXT);
"""
ROLES = ("admin", "adult", "kid")
INVITE_DAYS = 14


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    p = data_root() / "accounts.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(SCHEMA)
    return con


def signup_mode() -> str:
    m = os.getenv("HELPER_SIGNUP", "invite")
    return m if m in ("invite", "open", "closed") else "invite"


def signup_code_ok(code: str | None) -> bool:
    mode = signup_mode()
    if mode == "open":
        return True
    if mode == "closed":
        return False
    codes = [c.strip() for c in os.getenv("HELPER_SIGNUP_CODES", "").split(",") if c.strip()]
    return bool(code) and any(secrets.compare_digest(code, c) for c in codes)


def norm_email(e: str) -> str:
    e = (e or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) or len(e) > 200:
        raise ValueError("that email doesn't look right")
    return e


def _id(n: int = 12) -> str:
    return secrets.token_hex(n // 2 + 1)[:n]


# ---------------------------------------------------------------- users
def user_by_email(con, email: str) -> dict | None:
    r = con.execute("SELECT * FROM users WHERE email = ?", (norm_email(email),)).fetchone()
    return dict(r) if r else None


def user(con, uid: str) -> dict | None:
    r = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(r) if r else None


def get_or_create_user(con, email: str, name: str = "") -> dict:
    u = user_by_email(con, email)
    if u:
        return u
    uid = _id()
    con.execute("INSERT INTO users (id, email, name, created, feed_salt) VALUES (?,?,?,?,?)",
                (uid, norm_email(email), (name or email.split("@")[0])[:60], now(), _id(16)))
    con.commit()
    return user(con, uid)


def touch(con, uid: str) -> None:
    con.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now(), uid))
    con.commit()


def rotate_feed(con, uid: str) -> str:
    salt = _id(16)
    con.execute("UPDATE users SET feed_salt = ? WHERE id = ?", (salt, uid))
    con.commit()
    return salt


# ---------------------------------------------------------------- households
def memberships(con, uid: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT m.household_id, m.person_id, m.role, h.name, h.plan FROM members m JOIN households h "
        "ON h.id = m.household_id WHERE m.user_id = ? AND h.status = 'active' ORDER BY m.joined", (uid,))]


def membership(con, uid: str, hid: str) -> dict | None:
    r = con.execute("SELECT * FROM members WHERE user_id = ? AND household_id = ?", (uid, hid)).fetchone()
    return dict(r) if r else None


def members(con, hid: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT m.user_id, m.person_id, m.role, m.joined, u.email, u.name, u.last_seen FROM members m "
        "JOIN users u ON u.id = m.user_id WHERE m.household_id = ?", (hid,))]


def starter_settings(name: str, region: str, admin_person: dict, timezone: str = "America/New_York") -> dict:
    """A new household's settings: the wizard fills in the rest."""
    ex = yaml.safe_load((ROOT / "config" / "household.example.yaml").read_text())
    return {
        "household": {"name": name[:60], "region": region, "timezone": timezone, "week_starts": "monday", "budget_per_week": 200,
                      "time_value_per_hour": 20, "planning_minutes_before": 60},
        "people": {admin_person["id"]: {k: v for k, v in admin_person.items() if k != "id"}},
        "pets": {},
        "meals": {"dinner": {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "eaters": "all"},
                  "special_nights": {}},
        "dinner_times": {"default": "18:00"},
        "prep_minutes": {d: 30 for d in ("mon", "tue", "wed", "thu", "fri")} | {"sat": 45, "sun": 60},
        "health": ex.get("health", {}),
        "brands": {},
        "stores": ["whole_foods", "trader_joes", "stop_and_shop"],
        "home_store": "whole_foods",
        "memberships": [],
        "cards": [],
        "suggestions": {"per_week": 2},
        "chores": ex.get("chores", {}),
        "storage": {"fridge_l": 500, "freezer_l": 200, "fill_target": 0.8},
        "eating_out": {"takeout": {"budget": 50, "service": "uber_eats"},
                       "eat_out": {"budget": 80, "service": "restaurant"}},
        "outputs": {"email": {"day": "sun", "time": "08:00", "to": [admin_person.get("email")] if admin_person.get(
            "email") else []}},
        "require_admin": True,
    }


def create_household(con, uid: str, name: str, region: str, person: dict, timezone: str = "America/New_York") -> str:
    from .config import parse_household
    hid = _id(12)
    pid = person["id"]
    settings = starter_settings(name, region, {**person, "admin": True, "age_band": "adult"}, timezone)
    parse_household(settings)                                   # validate before anything is written
    d = household_dir(hid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "household.yaml").write_text(yaml.safe_dump(settings, sort_keys=False, allow_unicode=True, width=120))
    con.execute("INSERT INTO households (id, name, created, created_by) VALUES (?,?,?,?)", (hid, name[:60], now(), uid))
    con.execute("INSERT INTO members VALUES (?,?,?,?,?)", (hid, uid, pid, "admin", now()))
    con.commit()
    return hid


def import_household(con, uid: str, path, admin_person: str) -> str:
    """Bring an existing household.yaml (the v1 setup) into an account."""
    from .config import parse_household
    raw = yaml.safe_load(open(path).read())
    if admin_person not in raw.get("people", {}):
        raise ValueError(f"{admin_person} isn't in that file")
    raw["people"][admin_person]["admin"] = True
    raw["require_admin"] = True
    parse_household(raw)
    hid = _id(12)
    d = household_dir(hid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "household.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=120))
    con.execute("INSERT INTO households (id, name, created, created_by) VALUES (?,?,?,?)",
                (hid, raw["household"].get("name", "Household")[:60], now(), uid))
    con.execute("INSERT INTO members VALUES (?,?,?,?,?)", (hid, uid, admin_person, "admin", now()))
    con.commit()
    return hid


def set_role(con, hid: str, uid: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError("bad role")
    if role != "admin" and admin_count(con, hid, excluding=uid) == 0:
        raise ValueError("the household needs at least one admin")
    con.execute("UPDATE members SET role = ? WHERE household_id = ? AND user_id = ?", (role, hid, uid))
    con.commit()


def admin_count(con, hid: str, excluding: str | None = None) -> int:
    return con.execute("SELECT COUNT(*) AS n FROM members WHERE household_id = ? AND role = 'admin' AND user_id != ?",
                       (hid, excluding or "")).fetchone()["n"]


def remove_member(con, hid: str, uid: str) -> None:
    m = membership(con, uid, hid)
    if not m:
        return
    if m["role"] == "admin" and admin_count(con, hid, excluding=uid) == 0 and len(members(con, hid)) > 1:
        raise ValueError("make someone else an admin first")
    con.execute("DELETE FROM members WHERE household_id = ? AND user_id = ?", (hid, uid))
    con.execute("DELETE FROM devices WHERE household_id = ? AND user_id = ?", (hid, uid))
    con.commit()
    if not members(con, hid):
        delete_household(con, hid)


def delete_household(con, hid: str) -> None:
    """Everything about a household goes: its folder (settings, database, outputs) and its rows here."""
    shutil.rmtree(household_dir(hid), ignore_errors=True)
    for t in ("members", "invites", "devices"):
        con.execute(f"DELETE FROM {t} WHERE household_id = ?", (hid,))
    con.execute("DELETE FROM households WHERE id = ?", (hid,))
    con.commit()


def delete_user(con, uid: str) -> list[str]:
    """In-app account deletion (an App Store requirement): leave every household; a household left with nobody
    signed in is deleted. Returns the ids of households deleted."""
    gone = []
    for m in memberships(con, uid):
        others = [x for x in members(con, m["household_id"]) if x["user_id"] != uid]
        if not others:
            delete_household(con, m["household_id"])
            gone.append(m["household_id"])
        else:
            if m["role"] == "admin" and not any(x["role"] == "admin" for x in others):
                adult = next((x for x in others if x["role"] == "adult"), None)
                if adult:
                    con.execute("UPDATE members SET role = 'admin' WHERE household_id = ? AND user_id = ?",
                                (m["household_id"], adult["user_id"]))
            con.execute("DELETE FROM members WHERE household_id = ? AND user_id = ?", (m["household_id"], uid))
    con.execute("DELETE FROM devices WHERE user_id = ?", (uid,))
    con.execute("DELETE FROM invites WHERE used_by = ?", (uid,))
    con.execute("DELETE FROM users WHERE id = ?", (uid,))
    con.commit()
    return gone


# ---------------------------------------------------------------- invites
def invite(con, hid: str, email: str, person_id: str, role: str, by: str) -> str:
    if role not in ROLES:
        raise ValueError("bad role")
    code = secrets.token_urlsafe(16)
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=INVITE_DAYS)).isoformat(timespec="seconds")
    con.execute("INSERT INTO invites (code, household_id, email, person_id, role, created_by, created, expires) "
                "VALUES (?,?,?,?,?,?,?,?)", (code, hid, norm_email(email), person_id, role, by, now(), expires))
    con.commit()
    return code


def pending_invites(con, hid: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT email, person_id, role, created, expires FROM invites WHERE household_id = ? AND used_by IS NULL "
        "AND expires > ?", (hid, now()))]


def accept_invite(con, code: str, uid: str, email: str) -> dict:
    r = con.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
    if not r or r["used_by"] or r["expires"] < now():
        raise ValueError("that invitation has expired or was already used")
    if r["email"] != norm_email(email):
        raise ValueError("that invitation is for a different email address")
    if not membership(con, uid, r["household_id"]):
        con.execute("INSERT INTO members VALUES (?,?,?,?,?)", (r["household_id"], uid, r["person_id"], r["role"], now()))
    con.execute("UPDATE invites SET used_by = ?, used_at = ? WHERE code = ?", (uid, now(), code))
    con.commit()
    return dict(r)


# ---------------------------------------------------------------- devices (push)
def add_device(con, uid: str, hid: str, token: str, platform: str) -> None:
    if not re.fullmatch(r"ExponentPushToken\[[A-Za-z0-9_\-]{10,}\]|ExpoPushToken\[[A-Za-z0-9_\-]{10,}\]", token or ""):
        raise ValueError("not an Expo push token")
    con.execute("INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,?)", (token, uid, hid, platform[:10], now(), now()))
    con.commit()


def devices(con, hid: str, uids: list[str] | None = None) -> list[dict]:
    rows = [dict(r) for r in con.execute("SELECT * FROM devices WHERE household_id = ?", (hid,))]
    return [r for r in rows if uids is None or r["user_id"] in uids]


def remove_device(con, token: str) -> None:
    con.execute("DELETE FROM devices WHERE token = ?", (token,))
    con.commit()


def households(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM households WHERE status = 'active'")]
