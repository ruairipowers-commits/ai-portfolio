"""Prices a ticket with the C++ engine and computes its risk: position Greeks, payoff, max loss / profit,
breakevens, a full-revaluation scenario grid, and a cross-check of the price by a second numerical method."""
from __future__ import annotations

import numpy as np

from . import _optlib as O
from .market import Market


def leg_rows(legs, mk: Market) -> list[dict]:
    rows = []
    for lg in legs:
        T, vol = mk.years(lg.expiry), mk.vol(lg.strike, lg.expiry)
        g = O.bs(mk.spot, lg.strike, T, mk.r, mk.q, vol, lg.option_type == "CALL")
        sign = 1 if lg.side == "BUY" else -1
        n = sign * lg.quantity * mk.multiplier
        rows.append({"side": lg.side, "qty": lg.quantity, "type": lg.option_type, "strike": lg.strike, "expiry": lg.expiry,
                     "years": round(T, 4), "vol": round(vol, 4), "price": round(g["price"], 4), "delta": round(g["delta"], 4),
                     "position_delta_shares": round(n * g["delta"], 2), "position_gamma": round(n * g["gamma"], 4),
                     "position_vega_usd": round(n * g["vega"], 2), "position_theta_usd": round(n * g["theta"], 2),
                     "premium_usd": round(n * g["price"], 2)})
    return rows


def _value(legs, mk: Market, spot, days_fwd=0.0, dvol=0.0):
    spot = np.asarray(spot, dtype=float)
    tot = np.zeros_like(spot)
    for lg in legs:
        T = max(mk.years(lg.expiry) - days_fwd / 365, 0.0)
        out = O.bs_vec(spot, lg.strike, T, mk.r, mk.q, max(mk.vol(lg.strike, lg.expiry) + dvol, 1e-4), lg.option_type == "CALL")
        tot += (1 if lg.side == "BUY" else -1) * lg.quantity * mk.multiplier * out["price"]
    return tot


def risk(legs, mk: Market, cfg: dict) -> dict:
    """Everything the explanation may quote. Numbers only from here."""
    rows = leg_rows(legs, mk)
    premium = sum(r["premium_usd"] for r in rows)                       # > 0 debit, < 0 credit
    contracts = max(r["qty"] for r in rows)
    first = min(lg.expiry for lg in legs)
    days = (mk.years(first)) * 365
    lo, hi = cfg["payoff_range"]
    s = np.linspace(mk.spot * max(lo, 1e-6), mk.spot * hi, 3001)
    pnl = _value(legs, mk, s, days) - premium                          # at the first expiry (later legs revalued)
    # tail behaviour beyond the grid: slope of P&L as spot → ∞ decides "unlimited"
    slope = (pnl[-1] - pnl[-50]) / (s[-1] - s[-50])
    unlimited_loss = slope < -1e-6 * mk.multiplier
    unlimited_gain = slope > 1e-6 * mk.multiplier
    sign = np.sign(pnl)
    be = s[np.where(np.diff(sign) != 0)[0]]
    per_structure = premium / (contracts * mk.multiplier)
    grid = {}
    for dv in cfg["scenario_vol"]:
        for ds in cfg["scenario_spot"]:
            grid[f"spot {ds:+.0%} / vol {dv * 100:+.0f}"] = round(float(_value(legs, mk, [mk.spot * (1 + ds)], 1, dv)[0] - premium), 2)
    worst = min(grid, key=grid.get)
    out = {
        "net_premium_usd": round(premium, 2), "price_per_structure": round(per_structure, 4),
        "premium_type": "DEBIT" if premium > 0 else "CREDIT",
        "position_delta_shares": round(sum(r["position_delta_shares"] for r in rows), 2),
        "position_gamma": round(sum(r["position_gamma"] for r in rows), 4),
        "position_vega_usd": round(sum(r["position_vega_usd"] for r in rows), 2),
        "position_theta_usd": round(sum(r["position_theta_usd"] for r in rows), 2),
        "max_loss_usd": "unlimited" if unlimited_loss else round(float(-pnl.min()), 2),
        "max_profit_usd": "unlimited" if unlimited_gain else round(float(pnl.max()), 2),
        "breakevens": [round(float(x), 2) for x in be[:4]],
        "worst_scenario": worst, "worst_scenario_pnl_usd": grid[worst],
        "days_to_first_expiry": int(round(days)),
    }
    view = (s >= mk.spot * 0.6) & (s <= mk.spot * 1.4)          # the chart shows ±40%; max loss used the full range
    return {"legs": rows, "summary": out, "scenarios": grid,
            "payoff": {"spot": s[view].round(2).tolist(), "pnl": pnl[view].round(2).tolist()}}


def cross_check(legs, mk: Market, cfg: dict) -> dict:
    """Price the structure by BSM, a Leisen-Reimer tree and Monte Carlo (antithetic + control variate)."""
    tot = {"bsm": 0.0, "lr_tree": 0.0, "mc": 0.0}
    var = 0.0
    for lg in legs:
        T, vol, call = mk.years(lg.expiry), mk.vol(lg.strike, lg.expiry), lg.option_type == "CALL"
        w = (1 if lg.side == "BUY" else -1) * lg.quantity * mk.multiplier
        tot["bsm"] += w * O.bs(mk.spot, lg.strike, T, mk.r, mk.q, vol, call)["price"]
        tot["lr_tree"] += w * O.binomial(mk.spot, lg.strike, T, mk.r, mk.q, vol, cfg["tree_steps"], call, False, "lr")["price"]
        m = O.mc(mk.spot, lg.strike, T, mk.r, mk.q, vol, call, "european", cfg["mc_paths"], 1, True, True, 0.0, 42)
        tot["mc"] += w * m["price"]
        var += (w * m["stderr"]) ** 2
    return {k: round(v, 2) for k, v in tot.items()} | {"mc_ci95_usd": round(1.96 * var ** 0.5, 2)}
