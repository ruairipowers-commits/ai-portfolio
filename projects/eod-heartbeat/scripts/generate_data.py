"""Generate 10 business days of synthetic end-of-day feeds for a fictional fund, with injected breaks.

Larkspur Capital (fictional) runs three books over 12 fictional securities. For each business date the
generator writes the files the EOD pipeline expects, plus when each one arrived:

  data/landing/<date>/{prices,fx,trades,pb_positions,corp_actions,adjustments,reported_pnl}.csv
  data/landing/<date>/arrivals.csv
  data/landing/reference/{securities,opening_positions,opening_prices,feeds}.csv

Injected breaks (what the SQL should find, and what the runbooks explain):
  2026-09-15  vendor price file late (18:42 vs 17:30 SLA)
  2026-09-17  NRDC 2:1 split applied by the prime broker, not internally -> position + P&L break
  2026-09-18  FX file never arrives -> missing critical feed, P&L can't be computed for MACRO
  2026-09-21  duplicated trade in the OMS extract -> position break on CDRX
  2026-09-22  BLKW price unchanged four days running (vendor stopped updating after 09-17) -> stale price
  2026-09-23  EUR rate published as 11.62 instead of 1.162 -> FX outlier + MACRO P&L break
  2026-09-24  prime-broker file late (19:48 vs 19:00) and a trade booked after the PB cutoff -> timing break
Fixes arrive as internal adjustments the next day (09-18 split, 09-22 duplicate), as ops would book them.
"""
from __future__ import annotations

import csv
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.getenv("EOD_LANDING_DIR") or ROOT / "data" / "landing")
rng = random.Random(7)

DATES = [date(2026, 9, d) for d in (14, 15, 16, 17, 18, 21, 22, 23, 24, 25)]
PRIOR = date(2026, 9, 11)
SECURITIES = [  # ticker, name, ccy, book, start price, opening qty
    ("ALPN", "Alpine Networks", "USD", "EQ-LS", 62.40, 40_000),
    ("BRKS", "Brookside Retail", "USD", "EQ-LS", 31.10, -25_000),
    ("CDRX", "Cedar Rx", "USD", "EQ-LS", 18.75, 60_000),
    ("DLMR", "Dalmore Energy", "USD", "EQ-LS", 47.20, 30_000),
    ("ELMW", "Elmwood Bancorp", "USD", "EQ-LS", 55.90, -18_000),
    ("NRDC", "Nordic Coldchain", "USD", "EQ-EVENT", 84.00, 20_000),
    ("BLKW", "Blackwater Mining", "USD", "EQ-EVENT", 12.30, 60_000),
    ("FRNT", "Frontier Pharma", "USD", "EQ-EVENT", 23.60, 45_000),
    ("HALM", "Halmstad Industri", "EUR", "MACRO", 41.80, 35_000),
    ("ORVL", "Orvelle SA", "EUR", "MACRO", 96.50, -12_000),
    ("THMS", "Thames Utilities", "GBP", "MACRO", 9.85, 200_000),
    ("KYOS", "Kyoso Robotics", "JPY", "MACRO", 3150.0, 8_000),
]
FX0 = {"USD": 1.0, "EUR": 1.162, "GBP": 1.318, "JPY": 0.00671}
FEEDS = [  # feed, SLA (ET), critical for NAV sign-off
    ("fx", "17:15", True), ("prices", "17:30", True), ("trades", "18:00", True),
    ("corp_actions", "18:30", False), ("pb_positions", "19:00", True), ("reported_pnl", "19:30", False),
]


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    tick = {s[0]: s for s in SECURITIES}
    # ---------------- true market data
    px = {t: [s[4]] for t, s in tick.items()}           # index 0 = PRIOR
    fx = {c: [v] for c, v in FX0.items()}
    for i, d in enumerate(DATES, start=1):
        for t in tick:
            if t == "BLKW" and d >= date(2026, 9, 18):
                move = rng.choice([-1, 1]) * rng.uniform(0.004, 0.008)   # illiquid, small moves
            else:
                move = rng.gauss(0.0004, 0.012)
            if d == date(2026, 9, 17) and t == "BLKW":
                move = 0.015                                # last real print before the vendor stalls
            if d == date(2026, 9, 23) and t in ("HALM", "ORVL"):
                move = {"HALM": 0.025, "ORVL": -0.015}[t]   # a real move on the day the EUR rate is wrong
            px[t].append(round(px[t][-1] * (1 + move), 2 if t != "KYOS" else 0))
        for c in fx:
            fx[c].append(1.0 if c == "USD" else round(fx[c][-1] * (1 + rng.gauss(0, 0.003)), 5 if c == "JPY" else 4))
    split_i = DATES.index(date(2026, 9, 17)) + 1
    for i in range(split_i, len(px["NRDC"])):             # NRDC trades post-split from 09-17
        px["NRDC"][i] = round(px["NRDC"][i] / 2, 2)

    # ---------------- trades (OMS) and true positions
    true_pos = {t: s[5] for t, s in tick.items()}
    internal_extra = {}
    trade_n = 1000
    pb_rows_by_date, trades_by_date = {}, {}
    pnl_by_date = {}
    for i, d in enumerate(DATES, start=1):
        trades = []
        for _ in range(rng.randint(3, 6)):
            t = rng.choice([s[0] for s in SECURITIES if s[0] not in ("NRDC", "BLKW")])
            qty = rng.choice([1, -1]) * rng.choice([1000, 2000, 2500, 5000])
            trade_n += 1
            trades.append([d.isoformat(), f"T{trade_n}", tick[t][3], t, qty, round(px[t][i] * (1 + rng.uniform(-0.003, 0.003)), 2),
                           "15:" + f"{rng.randint(0, 59):02d}"])
        if d == date(2026, 9, 21):                         # duplicated row in the OMS extract
            trade_n += 1
            dup = [d.isoformat(), f"T{trade_n}", "EQ-LS", "CDRX", 5000, round(px["CDRX"][i], 2), "14:12"]
            trades += [dup, list(dup)]
        if d == date(2026, 9, 24):                         # booked after the prime broker's 16:30 cutoff
            trade_n += 1
            trades.append([d.isoformat(), f"T{trade_n}", "EQ-LS", "ELMW", -3000, round(px["ELMW"][i], 2), "16:58"])
        trades_by_date[d] = trades
        # P&L the risk system reports (correct data, split-aware): prior qty x price change x today's FX
        pnl = {}
        for t, s in tick.items():
            prev_qty = true_pos[t] * (2 if (t == "NRDC" and i == split_i) else 1)
            prev_px = px[t][i - 1] / (2 if (t == "NRDC" and i == split_i) else 1)
            pnl[s[3]] = pnl.get(s[3], 0.0) + prev_qty * (px[t][i] - prev_px) * fx[s[2]][i]
        pnl_by_date[d] = pnl
        if i == split_i:
            true_pos["NRDC"] *= 2
        seen = set()
        for tr in trades:
            if tr[1] in seen:
                continue
            seen.add(tr[1])
            true_pos[tr[3]] += tr[4]
        pb_pos = dict(true_pos)
        if d == date(2026, 9, 24):
            pb_pos["ELMW"] += 3000                         # the late trade isn't in the PB file yet
        pb_rows_by_date[d] = [[d.isoformat(), tick[t][3], t, q] for t, q in pb_pos.items()]

    # ---------------- reference data
    ref = OUT / "reference"
    _write(ref / "securities.csv", ["ticker", "name", "ccy", "book"], [[s[0], s[1], s[2], s[3]] for s in SECURITIES])
    _write(ref / "opening_positions.csv", ["as_of", "book", "ticker", "qty"],
           [[PRIOR.isoformat(), s[3], s[0], s[5]] for s in SECURITIES])
    _write(ref / "opening_prices.csv", ["as_of", "ticker", "close"], [[PRIOR.isoformat(), t, px[t][0]] for t in tick])
    _write(ref / "opening_fx.csv", ["as_of", "ccy", "usd_rate"], [[PRIOR.isoformat(), c, fx[c][0]] for c in fx])
    _write(ref / "feeds.csv", ["feed", "sla_time", "critical"], [[f, s, str(c).lower()] for f, s, c in FEEDS])

    # ---------------- daily files as delivered (with injected faults)
    for i, d in enumerate(DATES, start=1):
        day = OUT / d.isoformat()
        vendor_px = {t: px[t][i] for t in tick}
        if date(2026, 9, 18) <= d <= date(2026, 9, 22):
            vendor_px["BLKW"] = px["BLKW"][DATES.index(date(2026, 9, 17)) + 1]   # vendor stopped updating after 09-17
        _write(day / "prices.csv", ["business_date", "ticker", "ccy", "close"],
               [[d.isoformat(), t, tick[t][2], vendor_px[t]] for t in tick])
        if d != date(2026, 9, 18):
            rates = {c: fx[c][i] for c in fx}
            if d == date(2026, 9, 23):
                rates["EUR"] = round(rates["EUR"] * 10, 4)  # decimal slipped in the vendor file
            _write(day / "fx.csv", ["business_date", "ccy", "usd_rate"], [[d.isoformat(), c, r] for c, r in rates.items()])
        _write(day / "trades.csv", ["business_date", "trade_id", "book", "ticker", "qty", "price", "booked_time"],
               trades_by_date[d])
        _write(day / "pb_positions.csv", ["business_date", "book", "ticker", "qty"], pb_rows_by_date[d])
        _write(day / "corp_actions.csv", ["business_date", "ticker", "action", "ratio"],
               [[d.isoformat(), "NRDC", "split", 2.0]] if d == date(2026, 9, 17) else [])
        adj = []
        if d == date(2026, 9, 18):
            adj.append([d.isoformat(), "EQ-EVENT", "NRDC", 20_000, "Book 2:1 split from 2026-09-17 (ops)"])
        if d == date(2026, 9, 22):
            adj.append([d.isoformat(), "EQ-LS", "CDRX", -5000, "Cancel duplicated OMS row from 2026-09-21 (ops)"])
        _write(day / "adjustments.csv", ["business_date", "book", "ticker", "qty", "reason"], adj)
        _write(day / "reported_pnl.csv", ["business_date", "book", "pnl_usd"],
               [[d.isoformat(), b, round(v, 2)] for b, v in pnl_by_date[d].items()])
        arrivals = []
        for feed, sla, _ in FEEDS:
            if feed == "fx" and d == date(2026, 9, 18):
                continue                                    # never arrives
            hh, mm = map(int, sla.split(":"))
            at = datetime(d.year, d.month, d.day, hh, mm) - timedelta(minutes=rng.randint(5, 40))
            if feed == "prices" and d == date(2026, 9, 15):
                at = datetime(d.year, d.month, d.day, 18, 42)
            if feed == "pb_positions" and d == date(2026, 9, 24):
                at = datetime(d.year, d.month, d.day, 19, 48)
            rows = sum(1 for _ in open(day / f"{feed}.csv")) - 1
            arrivals.append([d.isoformat(), feed, at.isoformat(timespec="minutes"), rows])
        _write(day / "arrivals.csv", ["business_date", "feed", "arrived_at", "rows"], arrivals)
    print(f"Wrote {len(DATES)} business days of feeds to {OUT}")


if __name__ == "__main__":
    main()
