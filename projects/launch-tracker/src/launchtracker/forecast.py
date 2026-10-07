"""Our own projection of annual launches: a log-linear trend with an interval, back-tested on recent years.

Deliberately simple and labelled as ours. Third-party projections (data/reference/market.yaml) are shown next to it,
labelled with who made them; the two are never blended.
"""
from __future__ import annotations

import math

import numpy as np

from .config import Settings


def _fit(years: list[int], counts: list[int]):
    x = np.array(years, dtype=float)
    y = np.log(np.maximum(np.array(counts, dtype=float), 1.0))
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    sd = float(np.std(resid, ddof=2)) if len(x) > 2 else 0.0
    return slope, intercept, sd


def annual_series(con, settings: Settings, industry: str | None = None) -> list[tuple[int, int]]:
    """Complete years only (the current year is partial and would drag the trend down)."""
    last_complete = settings.now().year - 1
    q = "select year(net), count(*) from launches where outcome <> 'pending' and year(net) <= ?"
    p: list = [last_complete]
    if industry:
        q += " and industry = ?"; p.append(industry)
    return [(int(y), int(n)) for y, n in con.execute(q + " group by 1 order by 1", p).fetchall()]


def project(con, settings: Settings, industry: str | None = None) -> dict:
    a = settings["analytics"]
    series = annual_series(con, settings, industry)
    if len(series) < 4:
        return {"series": series, "projection": [], "backtest": None, "note": "not enough history"}
    fit_years = series[-a["forecast_fit_years"]:]
    slope, icpt, sd = _fit([y for y, _ in fit_years], [n for _, n in fit_years])
    last = series[-1][0]
    z = 1.2816                                            # 80% interval
    proj = []
    for y in range(last + 1, last + 1 + a["forecast_years"]):
        mid = slope * y + icpt
        proj.append({"yr": y, "mid": round(math.exp(mid)), "low": round(math.exp(mid - z * sd)),
                     "high": round(math.exp(mid + z * sd))})
    # back-test: fit without the last k years, predict them, report the error
    k = a["backtest_years"]
    train = series[-(a["forecast_fit_years"] + k):-k]
    bt = None
    if len(train) >= 4:
        s2, i2, _ = _fit([y for y, _ in train], [n for _, n in train])
        rows = [{"yr": y, "actual": n, "predicted": round(math.exp(s2 * y + i2))} for y, n in series[-k:]]
        mape = sum(abs(r["predicted"] - r["actual"]) / r["actual"] for r in rows) / len(rows)
        bt = {"rows": rows, "mape_pct": round(100 * mape, 1)}
    return {"series": series, "projection": proj, "growth_pct_per_year": round(100 * (math.exp(slope) - 1), 1),
            "backtest": bt, "fit_years": [fit_years[0][0], fit_years[-1][0]],
            "label": "Our trend fit (log-linear, 80% interval) — not a forecast by anyone in the industry"}
