"""Build the OFFLINE FIXTURE in data/landing/ (deterministic, seeded).

- options_iv.parquet     same columns as gauss314/options-IV-SP500; GENERATED values for the symbols in
                         config/settings.yaml hub.slice_symbols over 120 trading days. `dlp fetch` replaces it with a
                         real slice from the Hub.
- constituents.parquet   from data/reference/constituents_fixture.csv (real names, sectors and CIKs for 45 S&P 500
                         companies; date_added mostly blank). `dlp fetch` replaces it with all 503 rows.
- usage.csv              SYNTHETIC query log: which team queried which dataset, per day, for 90 days.
The catalog itself (vendors, datasets, customers, contracts) is seeded from data/seed/catalog.yaml.
"""
from __future__ import annotations

import csv
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def trading_days(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def options(symbols: list[str], days: list[date], rng: random.Random) -> pd.DataFrame:
    rows = []
    vix = 16.0
    vix_path = {}
    for d in days:
        vix = max(10.0, min(45.0, vix + rng.gauss(0, 0.9) + (18 - vix) * 0.05))
        vix_path[d] = round(vix, 2)
    for s in symbols:
        base = rng.uniform(18, 45)
        hv = base * rng.uniform(0.8, 1.05)
        for d in days:
            atm = max(8.0, base + (vix_path[d] - 16) * rng.uniform(0.6, 1.2) + rng.gauss(0, 1.2))
            hv = max(6.0, 0.94 * hv + 0.06 * atm * rng.uniform(0.75, 1.0) + rng.gauss(0, 0.6))
            calls = int(rng.lognormvariate(math.log(40000), 0.6))
            puts = int(calls * rng.uniform(0.5, 1.3))
            skew = rng.uniform(1.5, 4.0)
            rows.append({
                "symbol": s, "date": d.isoformat(), "strikes_spread": round(rng.uniform(0.5, 5.0), 2),
                "calls_contracts_traded": calls, "puts_contracts_traded": puts,
                "calls_open_interest": int(calls * rng.uniform(4, 9)), "puts_open_interest": int(puts * rng.uniform(4, 9)),
                "DITM_IV": round(atm + 3 * skew, 2), "ITM_IV": round(atm + 2 * skew, 2), "sITM_IV": round(atm + skew, 2),
                "ATM_IV": round(atm, 2), "sOTM_IV": round(atm - 0.5 * skew, 2), "OTM_IV": round(atm - 0.2 * skew, 2),
                "DOTM_IV": round(atm + 0.8 * skew, 2), "hv_20": round(hv, 2), "hv_60": round(hv * rng.uniform(0.95, 1.05), 2),
                "hv_120": round(hv * rng.uniform(0.92, 1.08), 2), "hv_200": round(hv * rng.uniform(0.9, 1.1), 2),
                "VIX": vix_path[d],
            })
    return pd.DataFrame(rows)


def usage(catalog: dict, days: list[date], rng: random.Random) -> list[dict]:
    # (team, dataset) → mean queries per day. Card panel is barely used (a retirement candidate).
    pattern = {("t-vol", "ds-nl-volsurface"): 14, ("t-vol", "ds-options-iv"): 9, ("t-macro", "ds-card-panel"): 0.15,
               ("t-macro", "ds-options-iv"): 1.0, ("t-qr", "ds-port-congestion"): 6, ("t-qr", "ds-options-iv"): 11,
               ("t-qr", "ds-edgar-10k"): 2, ("t-vol", "ds-constituents"): 3, ("t-risk", "ds-rates-curve"): 4}
    users = {u["team"]: u["id"] for c in catalog["customers"] for u in c["users"]}
    team_cust = {t["id"]: c["id"] for c in catalog["customers"] for t in c["teams"]}
    out = []
    for d in days:
        for (team, ds), lam in pattern.items():
            if ds == "ds-rates-curve" and d > date(2026, 6, 30):
                continue  # Alder's contract expired; access stopped
            n = sum(1 for _ in range(30) if rng.random() < lam / 30)
            if n:
                out.append({"day": d.isoformat(), "customer": team_cust[team], "team": team, "user": users[team],
                            "dataset": ds, "queries": n})
    return out


def main() -> int:
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    catalog = yaml.safe_load((ROOT / "data" / "seed" / "catalog.yaml").read_text())
    landing = ROOT / settings["paths"]["landing"]
    landing.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    opt_days = trading_days(date(2026, 10, 2), 120)
    df = options(settings["hub"]["slice_symbols"], opt_days, rng)
    df.to_parquet(landing / "options_iv.parquet", index=False)
    cons = pd.read_csv(ROOT / "data" / "reference" / "constituents_fixture.csv", dtype=str)
    cons.to_parquet(landing / "constituents.parquet", index=False)
    use_days = [date(2026, 10, 5) - timedelta(days=i) for i in range(90, 0, -1)]
    rows = usage(catalog, use_days, rng)
    with open(landing / "usage.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (landing / "SOURCE").write_text("fixture\n")
    print(f"fixture: {len(df)} option rows, {len(cons)} constituents, {len(rows)} usage rows → {landing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
