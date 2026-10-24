"""The owner's side of plans: list prices (monthly and yearly), each subscription, and what happens at renewal.

Prices have a history: a new price takes effect on its date and old ones stay on record. Every subscription keeps
the price it pays now and a renewal policy:
  grandfather    keeps its price at every renewal, whatever the list price becomes
  current_price  renews at the list price of its plan and billing period on the renewal date (an upcharge, or a cut)
  custom         renews at a price set for that one subscriber
Subscribers whose price goes up at their next renewal get an email 30 days before (once per renewal).

Where the money is actually taken: App Store and Google Play subscriptions (source `revenuecat`) are charged at the
prices in App Store Connect / Play Console, which also decide whether existing subscribers keep their price (Apple's
"preserve prices for existing subscribers"); the console shows what to set there. Subscriptions marked `direct`
(future web billing) and `comp` (free, given by the owner) follow these rules exactly.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets

from . import plans

POLICIES = ("grandfather", "current_price", "custom")
INTERVALS = ("monthly", "yearly")
SOURCES = ("admin", "comp", "direct", "revenuecat", "trial")
NOTICE_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (plan TEXT, monthly REAL, yearly REAL, effective TEXT, set_by TEXT, note TEXT,
    created TEXT, PRIMARY KEY (plan, effective));
CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY, kind TEXT, subject TEXT, plan TEXT, interval TEXT,
    price REAL, policy TEXT DEFAULT 'current_price', custom_price REAL, started TEXT, renews TEXT,
    status TEXT DEFAULT 'active', source TEXT, notice_for TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS billing_log (ts TEXT, sub TEXT, event TEXT, detail TEXT, by TEXT);
"""


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(d: dt.datetime) -> str:
    return d.isoformat(timespec="seconds")


def setup(con) -> None:
    con.executescript(SCHEMA)


def owners() -> set[str]:
    return {e.strip().lower() for e in os.getenv("HELPER_OWNER_EMAILS", "").split(",") if e.strip()}


def is_owner(email: str) -> bool:
    return (email or "").lower() in owners()


def log(con, sub: str, event: str, detail: dict, by: str = "system") -> None:
    con.execute("INSERT INTO billing_log VALUES (?,?,?,?,?)", (iso(now()), sub, event, json.dumps(detail), by))


# ---------------------------------------------------------------- list prices
PAID = ("family", "chef_solo", "chef_studio")


def price(con, plan: str, at: dt.datetime | None = None) -> dict:
    """The list price in force at `at`: {monthly, yearly, effective, savings_pct}."""
    setup(con)
    at = at or now()
    r = con.execute("SELECT * FROM prices WHERE plan = ? AND effective <= ? ORDER BY effective DESC LIMIT 1",
                    (plan, iso(at))).fetchone()
    t = plans.TIERS[plan]
    m, y = (float(r["monthly"]), float(r["yearly"])) if r else (float(t["monthly"]), float(t["yearly"]))
    return {"plan": plan, "monthly": m, "yearly": y, "effective": r["effective"] if r else None,
            "savings_pct": round(100 * (1 - y / (12 * m))) if m else 0}


def price_book(con) -> list[dict]:
    setup(con)
    out = []
    for p in PAID:
        cur = price(con, p)
        nxt = con.execute("SELECT * FROM prices WHERE plan = ? AND effective > ? ORDER BY effective LIMIT 1",
                          (p, iso(now()))).fetchone()
        hist = [dict(r) for r in con.execute("SELECT * FROM prices WHERE plan = ? ORDER BY effective DESC", (p,))]
        out.append({**cur, "label": plans.TIERS[p]["label"], "scheduled": dict(nxt) if nxt else None, "history": hist,
                    "subscribers": con.execute("SELECT COUNT(*) AS n FROM subscriptions WHERE plan = ? AND status = 'active'",
                                               (p,)).fetchone()["n"]})
    return out


def set_price(con, plan: str, monthly: float, yearly: float | None = None, annual_discount_pct: float | None = None,
              effective: dt.datetime | None = None, by: str = "owner", note: str = "") -> dict:
    """A new list price from `effective` (now by default). Give yearly, or a discount on 12 months."""
    setup(con)
    if plan not in PAID:
        raise ValueError(f"paid plans are {', '.join(PAID)}")
    if not 0 < monthly <= 10000:
        raise ValueError("the monthly price must be positive")
    if yearly is None:
        if annual_discount_pct is None or not 0 <= annual_discount_pct < 100:
            raise ValueError("give a yearly price or a yearly discount from 0 to 99%")
        yearly = round(monthly * 12 * (1 - annual_discount_pct / 100), 2)
    if not 0 < yearly <= monthly * 12:
        raise ValueError("the yearly price must be positive and no more than 12 months at the monthly price")
    eff = iso(effective or now())
    con.execute("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)",
                (plan, round(monthly, 2), round(yearly, 2), eff, by, note[:200], iso(now())))
    log(con, "", "price", {"plan": plan, "monthly": monthly, "yearly": yearly, "effective": eff}, by)
    con.commit()
    return price(con, plan, dt.datetime.fromisoformat(eff))


# ---------------------------------------------------------------- subscriptions
def _add(start: dt.datetime, interval: str) -> dt.datetime:
    if interval == "yearly":
        try:
            return start.replace(year=start.year + 1)
        except ValueError:
            return start.replace(year=start.year + 1, day=28)
    m = start.month % 12 + 1
    y = start.year + (start.month == 12)
    for d in (start.day, 30, 29, 28):
        try:
            return start.replace(year=y, month=m, day=d)
        except ValueError:
            continue
    raise ValueError("bad date")


def subscribe(con, kind: str, subject: str, plan: str, interval: str = "monthly", source: str = "admin",
              policy: str = "current_price", start: dt.datetime | None = None, renews: dt.datetime | None = None,
              price_now: float | None = None, by: str = "owner") -> dict:
    """Start (or replace) the active subscription for a household (kind 'household') or a chef (kind 'chef'), and
    turn the plan on."""
    setup(con)
    if interval not in INTERVALS or policy not in POLICIES or source not in SOURCES:
        raise ValueError("bad interval, policy or source")
    if (kind == "chef") != (plan in plans.CHEF_PLANS) or plan not in PAID:
        raise ValueError("chef plans go on a chef; Family goes on a household")
    start = start or now()
    renews = renews or _add(start, interval)
    p = price_now if price_now is not None else (0.0 if source == "comp" else price(con, plan, start)[interval])
    con.execute("UPDATE subscriptions SET status = 'replaced', updated = ? WHERE kind = ? AND subject = ? AND status = 'active'",
                (iso(now()), kind, subject))
    sid = secrets.token_hex(6)
    con.execute("INSERT INTO subscriptions (id, kind, subject, plan, interval, price, policy, started, renews, status, "
                "source, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, kind, subject, plan, interval, round(p, 2), policy, iso(start), iso(renews), "active", source,
                 iso(now())))
    _apply_plan(con, kind, subject, plan, iso(renews + dt.timedelta(days=3)))     # three days' grace past renewal
    log(con, sid, "start", {"plan": plan, "interval": interval, "price": p, "source": source}, by)
    con.commit()
    return get(con, sid)


def _apply_plan(con, kind: str, subject: str, plan: str, until: str | None) -> None:
    if kind == "chef":
        plans.set_chef_plan(con, subject, plan, until)
    else:
        plans.set_household_plan(con, subject, plan, until)


def get(con, sid: str) -> dict:
    r = con.execute("SELECT * FROM subscriptions WHERE id = ?", (sid,)).fetchone()
    if not r:
        raise ValueError("no such subscription")
    return dict(r)


def next_price(con, sub: dict) -> float:
    """What this subscription renews at, under its policy, with the list price on its renewal date."""
    if sub["source"] == "comp":
        return 0.0
    if sub["policy"] == "grandfather":
        return float(sub["price"])
    if sub["policy"] == "custom" and sub.get("custom_price") is not None:
        return float(sub["custom_price"])
    return price(con, sub["plan"], dt.datetime.fromisoformat(sub["renews"]))[sub["interval"]]


def edit(con, sid: str, by: str = "owner", **changes) -> dict:
    sub = get(con, sid)
    if changes.get("policy") and changes["policy"] not in POLICIES:
        raise ValueError(f"policy is one of {', '.join(POLICIES)}")
    if changes.get("policy") == "custom" and changes.get("custom_price") is None and sub.get("custom_price") is None:
        raise ValueError("a custom renewal needs a price")
    if changes.get("custom_price") is not None and not 0 <= float(changes["custom_price"]) <= 10000:
        raise ValueError("that price doesn't look right")
    if changes.get("interval") and changes["interval"] not in INTERVALS:
        raise ValueError("monthly or yearly")
    if changes.get("plan") and changes["plan"] != sub["plan"]:
        if (sub["kind"] == "chef") != (changes["plan"] in plans.CHEF_PLANS) or changes["plan"] not in PAID:
            raise ValueError("that plan doesn't fit this subscriber")
    allowed = {k: v for k, v in changes.items() if k in ("policy", "custom_price", "interval", "plan", "status")
               and v is not None}
    if not allowed:
        return sub
    sets = ", ".join(f"{k} = ?" for k in allowed)
    con.execute(f"UPDATE subscriptions SET {sets}, notice_for = NULL, updated = ? WHERE id = ?",
                (*allowed.values(), iso(now()), sid))
    if "plan" in allowed or allowed.get("status") == "cancelled":
        s2 = get(con, sid)
        if allowed.get("status") == "cancelled":
            log(con, sid, "cancel", {"ends": s2["renews"]}, by)       # keeps the plan until the paid period ends
        else:
            _apply_plan(con, s2["kind"], s2["subject"], s2["plan"], iso(dt.datetime.fromisoformat(s2["renews"]) + dt.timedelta(days=3)))
    log(con, sid, "edit", allowed, by)
    con.commit()
    return get(con, sid)


def bulk_policy(con, plan: str, policy: str, by: str = "owner") -> int:
    """Grandfather everyone on a plan (or move them all to the list price at renewal)."""
    if policy not in ("grandfather", "current_price"):
        raise ValueError("bulk changes are grandfather or current_price")
    n = con.execute("UPDATE subscriptions SET policy = ?, notice_for = NULL, updated = ? WHERE plan = ? AND status = 'active'",
                    (policy, iso(now()), plan)).rowcount
    log(con, "", "bulk_policy", {"plan": plan, "policy": policy, "count": n}, by)
    con.commit()
    return n


def listing(con, plan: str | None = None, status: str = "active") -> list[dict]:
    setup(con)
    q, args = "SELECT * FROM subscriptions WHERE status = ?", [status]
    if plan:
        q, args = q + " AND plan = ?", args + [plan]
    out = []
    for r in con.execute(q + " ORDER BY renews", args):
        s = dict(r)
        s["next_price"] = next_price(con, s)
        s["change"] = round(s["next_price"] - float(s["price"]), 2)
        s["who"] = _who(con, s)
        out.append(s)
    return out


def _who(con, s: dict) -> dict:
    if s["kind"] == "chef":
        u = con.execute("SELECT email, name FROM users WHERE id = ?", (s["subject"],)).fetchone()
        return {"name": u["name"] if u else "?", "email": u["email"] if u else ""}
    h = con.execute("SELECT name FROM households WHERE id = ?", (s["subject"],)).fetchone()
    a = con.execute("SELECT u.email FROM members m JOIN users u ON u.id = m.user_id WHERE m.household_id = ? "
                    "AND m.role = 'admin' LIMIT 1", (s["subject"],)).fetchone()
    return {"name": h["name"] if h else "?", "email": a["email"] if a else ""}


def renewals(con, days: int = 30) -> list[dict]:
    """Active subscriptions renewing in the next `days`, with their renewal price."""
    end = iso(now() + dt.timedelta(days=days))
    return [s for s in listing(con) if s["renews"] <= end]


def renew_due(con, at: dt.datetime | None = None, by: str = "system") -> list[dict]:
    """Roll every subscription whose renewal date has passed: new price under its policy, next date, plan extended.
    Cancelled ones end instead. App Store subscriptions renew through the webhook, so they're skipped here."""
    setup(con)
    at = at or now()
    done = []
    for r in con.execute("SELECT * FROM subscriptions WHERE status IN ('active', 'cancelled') AND renews <= ? "
                         "AND source != 'revenuecat'", (iso(at),)).fetchall():
        s = dict(r)
        if s["status"] == "cancelled":
            con.execute("UPDATE subscriptions SET status = 'ended', updated = ? WHERE id = ?", (iso(at), s["id"]))
            _apply_plan(con, s["kind"], s["subject"], "none" if s["kind"] == "chef" else "free", None)
            log(con, s["id"], "end", {}, by)
            done.append({"id": s["id"], "ended": True})
            continue
        newp = next_price(con, s)
        nxt = _add(dt.datetime.fromisoformat(s["renews"]), s["interval"])
        con.execute("UPDATE subscriptions SET price = ?, renews = ?, notice_for = NULL, updated = ? WHERE id = ?",
                    (round(newp, 2), iso(nxt), iso(at), s["id"]))
        _apply_plan(con, s["kind"], s["subject"], s["plan"], iso(nxt + dt.timedelta(days=3)))
        log(con, s["id"], "renew", {"from": s["price"], "to": newp, "next": iso(nxt), "policy": s["policy"]}, by)
        done.append({"id": s["id"], "from": s["price"], "to": newp, "renews": iso(nxt)})
    con.commit()
    return done


def notices_due(con, at: dt.datetime | None = None) -> list[dict]:
    """Subscriptions whose price goes up at a renewal within NOTICE_DAYS and haven't been told yet."""
    setup(con)
    at = at or now()
    out = []
    for s in listing(con):
        if s["source"] == "revenuecat" or s["notice_for"] == s["renews"]:
            continue
        if s["renews"] <= iso(at + dt.timedelta(days=NOTICE_DAYS)) and s["next_price"] > float(s["price"]) + 0.004:
            out.append(s)
    return out


def mark_noticed(con, sid: str, renews: str) -> None:
    con.execute("UPDATE subscriptions SET notice_for = ? WHERE id = ?", (renews, sid))
    log(con, sid, "notice", {"renews": renews}, "system")
    con.commit()


def history(con, limit: int = 100) -> list[dict]:
    setup(con)
    return [dict(r) for r in con.execute("SELECT * FROM billing_log ORDER BY ts DESC LIMIT ?", (limit,))]
