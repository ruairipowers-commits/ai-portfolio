from __future__ import annotations

import numpy as np
import pandas as pd


def perf(equity: pd.Series | np.ndarray, bars_per_year: float, init: float | None = None) -> dict:
    e = np.asarray(equity, dtype=float)
    if len(e) < 3:
        return {}
    r = np.diff(e) / e[:-1]
    mu, sd = r.mean(), r.std(ddof=1)
    downside = r[r < 0].std(ddof=1) if (r < 0).sum() > 1 else np.nan
    years = len(r) / bars_per_year
    tot = e[-1] / (init or e[0]) - 1
    dd = e / np.maximum.accumulate(e) - 1
    ann = (1 + tot) ** (1 / years) - 1 if years > 0 and tot > -1 else np.nan
    return {
        "Total return": tot,
        "Annualised return": ann,
        "Annualised vol": sd * np.sqrt(bars_per_year),
        "Sharpe": mu / sd * np.sqrt(bars_per_year) if sd > 0 else 0.0,
        "Sortino": mu / downside * np.sqrt(bars_per_year) if downside and downside > 0 else np.nan,
        "Max drawdown": dd.min(),
        "Calmar": ann / abs(dd.min()) if dd.min() < 0 and np.isfinite(ann) else np.nan,
    }


def trade_stats(fills: pd.DataFrame, bars: pd.DataFrame, init_cash: float) -> dict:
    if fills is None or fills.empty:
        return {"Fills": 0}
    days = max(bars.ts.dt.date.nunique(), 1)
    notional = (fills.qty * fills.price).sum()
    costs = fills.commission.sum() + fills.spread_cost.sum() + fills.impact_cost.sum()
    exposure = (bars.position != 0).mean()
    return {
        "Fills": len(fills),
        "Shares traded": fills.qty.sum(),
        "Daily turnover (x equity)": notional / init_cash / days,
        "Avg cost per fill (bps)": costs / notional * 1e4 if notional else 0,
        "Avg implementation shortfall (bps)": np.average(fills.shortfall_bps, weights=fills.qty),
        "Avg fill delay (ms)": fills.delay_ms.mean(),
        "Time in market": exposure,
    }


def round_trips(fills: pd.DataFrame) -> pd.DataFrame:
    """Group fills into position episodes (flat → flat, or sign flips) with their P&L."""
    if fills is None or fills.empty:
        return pd.DataFrame()
    out, pos, cash, start, comm = [], 0.0, 0.0, None, 0.0
    for f in fills.itertuples():
        q = f.signed_qty
        if pos == 0:
            start, cash, comm = f.ts, 0.0, 0.0
        new = pos + q
        if pos != 0 and (new == 0 or np.sign(new) != np.sign(pos)):
            close_q = -pos
            cash -= close_q * f.price
            comm += f.commission * abs(close_q) / abs(q)
            out.append({"entry": start, "exit": f.ts, "side": "long" if pos > 0 else "short",
                        "pnl": cash - comm, "holding": f.ts - start})
            rem = q - close_q
            pos = rem
            start, cash, comm = f.ts, -rem * f.price, f.commission * abs(rem) / abs(q) if rem else 0.0
            continue
        cash -= q * f.price
        comm += f.commission
        pos = new
    return pd.DataFrame(out)


def cost_waterfall(res) -> pd.DataFrame:
    """Gross (frictionless) P&L → net P&L, split into the frictions the engine modelled."""
    b, f = res.bars, res.fills
    gross = b.gross_equity.iloc[-1] - res.cfg.init_cash
    net = b.equity.iloc[-1] - res.cfg.init_cash
    if f is None or f.empty:
        return pd.DataFrame({"component": ["Gross P&L", "Net P&L"], "value": [gross, net]})
    spread, impact, comm, delay = f.spread_cost.sum(), f.impact_cost.sum(), f.commission.sum(), f.delay_cost.sum()
    other = (gross - spread - impact - comm - delay) - net   # e.g. unfilled working orders at the end
    comps = [("Gross P&L", gross), ("Spread", -spread), ("Impact + slippage", -impact), ("Commission", -comm),
             ("Latency / delay", -delay), ("Residual", -other), ("Net P&L", net)]
    return pd.DataFrame(comps, columns=["component", "value"])
