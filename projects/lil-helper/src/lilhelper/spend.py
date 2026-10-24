"""What the household actually spent on food, against its budget — and where the numbers come from.

Three ways in, all on the household's own server:
  manual       type an amount ("$42 at Trader Joe's")
  statement    a card statement CSV (Amex, Citi and most banks' exports): only food rows matching config/merchants.yaml
               are kept, as store + amount + date. Descriptions, other purchases, card-member names and account
               numbers are never stored (DATA-03). Re-importing the same file adds nothing (each row's hash is kept).
  receipt      a photo or pasted receipt email, read by a model (ai.read_receipt) and confirmed by a person; matched
               item prices then update the price book, so next week's plan costs reflect what you really pay

Rewards: each row records what its card earned (counting this year's caps) and any monthly credit used (e.g. Uber
Cash on an Uber Eats order).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from functools import lru_cache

import yaml

from . import money, store
from .config import ROOT, Household
from .prices import week_start

CATEGORIES = ("groceries", "takeout", "eat_out")


@lru_cache(maxsize=1)
def _rules() -> dict:
    return yaml.safe_load((ROOT / "config" / "merchants.yaml").read_text())


def match_merchant(description: str, category_column: str = "") -> dict | None:
    r = _rules()
    d = (description or "").upper()
    if any(re.search(p, d, re.I) for p in r.get("skip", [])):
        return None
    for rule in r.get("rules", []):
        if re.search(rule["pattern"], d, re.I):
            return rule
    for cat, pats in (r.get("category_column") or {}).items():
        if category_column and any(re.search(p, category_column, re.I) for p in pats):
            return {"store": "restaurant", "category": cat, "label": "Restaurant"}
    return None


def _ref(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def ytd_used(con, year: int, month: int | None = None) -> dict[tuple[str, str], float]:
    """This calendar year's spend per (card, reward category), for annual caps; with `month`, also that month's
    spend per card under (card, money.MONTH), for spending limits."""
    out: dict[tuple[str, str], float] = {}
    for r in con.execute("SELECT card, store, amount, date FROM spend WHERE date >= ? AND date < ? AND card IS NOT NULL",
                         (f"{year}-01-01", f"{year + 1}-01-01")):
        key = (r["card"], money.category(r["store"] or ""))
        out[key] = out.get(key, 0.0) + float(r["amount"])
        if month and str(r["date"])[5:7] == f"{month:02d}":
            out[(r["card"], money.MONTH)] = out.get((r["card"], money.MONTH), 0.0) + float(r["amount"])
    return out


def credit_used(con, service: str, when: dt.date) -> float:
    start = when.replace(day=1)
    end = (start + dt.timedelta(days=32)).replace(day=1)
    row = con.execute("SELECT COALESCE(SUM(credit), 0) AS c FROM spend WHERE store = ? AND date >= ? AND date < ?",
                      (service, start.isoformat(), end.isoformat())).fetchone()
    return float(row["c"])


def _rewards(con, h: Household, store_id: str, amount: float, card: str | None, date: dt.date) -> tuple[float, float]:
    """(rewards earned on this card for this spend, monthly credit applied)."""
    credit = 0.0
    cards = money.cards(h)
    left, _ = money.credits_for(h, store_id, date, credit_used(con, store_id, date))
    if left and card in cards and any(store_id in cr.get("applies_to", []) for cr in cards[card].credits):
        credit = round(min(left, amount), 2)
    if not card or card not in cards:
        return 0.0, credit
    c = cards[card]
    cat = money.category(store_id)
    r, cap = money.rate(c, cat)
    used = ytd_used(con, date.year).get((card, cat), 0.0)
    bonus = min(amount, max(0.0, cap - used)) if cap is not None else amount
    earned = bonus * r + (amount - bonus) * money.default_rate(c)
    pct, _, _ = money.store_reward(h, store_id)
    return round(earned + amount * pct, 2), credit


def add(con, h: Household, *, date: dt.date, amount: float, store_id: str | None, merchant: str, category: str,
        card: str | None, source: str, by: str, ref: str | None = None, note: str = "") -> bool:
    """Record one purchase. Returns False if it was already recorded (same ref)."""
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    if amount <= 0 or amount > 5000:
        raise ValueError("amount must be between $0 and $5,000")
    if card and card not in money.cards(h):
        raise ValueError("that card isn't in the household settings")
    rewards, credit = _rewards(con, h, store_id or "", amount, card, date)
    try:
        con.execute("INSERT INTO spend (date, week_of, merchant, store, category, amount, card, rewards, credit, source,"
                    " ref, note, by, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (date.isoformat(), week_start(date).isoformat(), merchant[:60], store_id, category, round(amount, 2),
                     card, rewards, credit, source, ref or _ref(source, date, merchant, amount, store.now()), note[:120],
                     by, store.now()))
    except Exception as e:                                   # sqlite3.IntegrityError on a duplicate ref
        if "UNIQUE" in str(e):
            return False
        raise
    con.commit()
    return True


# ---------------------------------------------------------------- statements
DATE_COLS = ("date", "transaction date", "trans. date", "posted date", "post date")
DESC_COLS = ("description", "merchant", "payee", "name", "appears on your statement as")
AMOUNT_COLS = ("amount",)
CAT_COLS = ("category",)


def _col(headers: list[str], names: tuple[str, ...]) -> str | None:
    low = {h.strip().lower(): h for h in headers}
    return next((low[n] for n in names if n in low), None)


def _parse_date(s: str) -> dt.date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _money(s: str) -> float | None:
    s = (s or "").replace("$", "").replace(",", "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def import_statement(con, h: Household, text: str, card: str | None, by: str) -> dict:
    """A card statement CSV → food purchases. Only date, a store label and the amount are kept per matched row."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = reader.fieldnames or []
    dcol, ncol = _col(headers, DATE_COLS), _col(headers, DESC_COLS)
    acol, ccol = _col(headers, AMOUNT_COLS), _col(headers, CAT_COLS)
    debit = _col(headers, ("debit",))
    if not dcol or not ncol or not (acol or debit):
        raise ValueError("couldn't find date, description and amount columns in this file")
    rows = list(reader)
    # Charges are positive on Amex and Citi exports, negative on some banks': follow the majority.
    amounts = [_money(r.get(acol, "")) for r in rows] if acol else []
    flip = bool(acol) and sum(1 for a in amounts if a and a < 0) > sum(1 for a in amounts if a and a > 0)
    out = {"imported": 0, "duplicates": 0, "skipped_not_food": 0, "skipped_refunds": 0, "rows": len(rows)}
    for r in rows:
        desc = r.get(ncol, "")
        rule = match_merchant(desc, r.get(ccol, "") if ccol else "")
        if not rule:
            out["skipped_not_food"] += 1
            continue
        amt = _money(r.get(debit, "")) if debit else _money(r.get(acol, ""))
        if amt is not None and flip:
            amt = -amt
        date = _parse_date(r.get(dcol, ""))
        if not amt or amt <= 0 or not date:
            out["skipped_refunds"] += 1
            continue
        ref = _ref("statement", card, date, desc.strip().upper(), amt)
        if add(con, h, date=date, amount=amt, store_id=rule["store"], merchant=rule["label"],
               category=rule["category"], card=card, source="statement", by=by, ref=ref):
            out["imported"] += 1
        else:
            out["duplicates"] += 1
    store.audit(con, by, "import_statement", dict(out))
    return out


# ---------------------------------------------------------------- receipts
def confirm_receipt(con, h: Household, res, card: str | None, by: str, use_prices: bool = True) -> dict:
    """A person confirmed a receipt read by ai.read_receipt: record the spend, and the matched prices."""
    if res.total is None:
        raise ValueError("no total on this receipt")
    date = dt.date.fromisoformat(res.date) if res.date else dt.date.today()
    ref = _ref("receipt", res.merchant, date, res.total)
    added = add(con, h, date=date, amount=res.total, store_id=res.store, merchant=res.merchant or "Receipt",
                category=res.category, card=card, source="receipt", by=by, ref=ref)
    prices = 0
    if added and use_prices and res.store:
        for it in res.items:
            if it["status"] == "price_update":
                con.execute("INSERT INTO prices_seen VALUES (?,?,?,?,?,?,?,?)",
                            (res.store, it["ingredient"], it["price"], it.get("pack"), date.isoformat(), "receipt", by,
                             store.now()))
                prices += 1
        con.commit()
    store.audit(con, by, "confirm_receipt", {"store": res.store, "total": res.total, "prices": prices,
                                             "duplicate": not added})
    return {"recorded": added, "prices_updated": prices}


def observed_prices(con, since_days: int = 60, today: dt.date | None = None) -> dict[tuple[str, str], float]:
    """Latest confirmed pack price per (store, ingredient) from receipts — the price book prefers these."""
    since = ((today or dt.date.today()) - dt.timedelta(days=since_days)).isoformat()
    out = {}
    for r in con.execute("SELECT store, ingredient, price FROM prices_seen WHERE date >= ? ORDER BY date", (since,)):
        out[(r["store"], r["ingredient"])] = float(r["price"])
    return out


# ---------------------------------------------------------------- budget vs actual
def summary(con, h: Household, week_of: dt.date) -> dict:
    """This week and month: budget, planned (from the week's plan) and spent, by category."""
    wk = week_start(week_of)
    rec = store.get_week(con, wk.isoformat()) or {}
    choice = rec.get("shopping_choice") or "balanced"
    planned_groc = ((rec.get("split") or {}).get(choice) or {}).get("total", 0.0)
    planned_out = {"takeout": 0.0, "eat_out": 0.0}
    for e in rec.get("eating_out") or []:
        planned_out[e["kind"]] += float(e.get("budget", 0)) - float(e.get("credit", 0))
    spent = {c: 0.0 for c in CATEGORIES}
    rewards = credits = 0.0
    rows = [dict(r) for r in con.execute("SELECT id, date, merchant, store, category, amount, card, rewards, credit, "
                                         "source FROM spend WHERE week_of = ? ORDER BY date", (wk.isoformat(),))]
    for r in rows:
        spent[r["category"]] += r["amount"]
        rewards += r["rewards"] or 0
        credits += r["credit"] or 0
    budget_groc = float(h.info.get("budget_per_week", 0) or 0)
    nights = (rec.get("plan") or {}).get("special_nights") or h.special_nights()
    budget_out = sum(float(h.eating_out().get(k, {}).get("budget", 0)) for k in nights.values()
                     if k in ("takeout", "eat_out"))
    month_start = wk.replace(day=1)
    m_rows = con.execute("SELECT category, SUM(amount) AS a FROM spend WHERE date >= ? AND date < ? GROUP BY category",
                         (month_start.isoformat(), (month_start + dt.timedelta(days=32)).replace(day=1).isoformat()))
    month = {r["category"]: round(r["a"], 2) for r in m_rows}
    total_budget = round(budget_groc + budget_out, 2)
    total_spent = round(sum(spent.values()) - credits, 2)
    return {"week_of": wk.isoformat(),
            "budget": {"groceries": budget_groc, "eating_out": round(budget_out, 2), "total": total_budget},
            "planned": {"groceries": round(planned_groc, 2), **{k: round(v, 2) for k, v in planned_out.items()},
                        "total": round(planned_groc + sum(planned_out.values()), 2)},
            "spent": {**{k: round(v, 2) for k, v in spent.items()}, "credits_used": round(credits, 2),
                      "total": total_spent},
            "remaining": round(total_budget - total_spent, 2),
            "rewards_earned": round(rewards, 2),
            "month": {"spent": month, "total": round(sum(month.values()), 2)},
            "rows": rows}
