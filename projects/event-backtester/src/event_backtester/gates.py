"""Data gate (DATA-02) and promotion checks (FR-4). Code computes every number the memo may quote."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .engine import Backtest, ExecConfig, Strategy
from .metrics import perf, trade_stats


@dataclass
class GateResult:
    ok: bool
    errors: list[str]
    rows: int

    @property
    def message(self) -> str:
        return (f"Data gate passed: {self.rows:,} ticks" if self.ok
                else f"Data gate failed ({len(self.errors)} problem(s)): " + "; ".join(self.errors[:5]))


def validate_ticks(t: pd.DataFrame, cfg: dict) -> GateResult:
    errs = []
    need = {"ts", "bid", "ask", "volume"}
    if not need <= set(t.columns):
        return GateResult(False, [f"missing columns: {sorted(need - set(t.columns))}"], len(t))
    n = len(t)
    if n < cfg["min_ticks"]:
        errs.append(f"only {n:,} ticks (need {cfg['min_ticks']:,})")
    if t[["bid", "ask"]].isna().any().any():
        errs.append(f"{int(t[['bid', 'ask']].isna().any(axis=1).sum())} rows with missing bid/ask")
    if (t.bid <= 0).any() or (t.ask <= 0).any():
        errs.append("non-positive prices")
    crossed = t.ask < t.bid
    if crossed.any():
        errs.append(f"{int(crossed.sum())} rows with ask < bid")
    ts = pd.to_datetime(t.ts)
    back = ts.diff().dt.total_seconds() < 0
    if back.any():
        errs.append(f"time goes backwards on {int(back.sum())} rows")
    mid = (t.bid + t.ask) / 2
    wide = ((t.ask - t.bid) / mid * 1e4) > cfg["max_spread_bps"]
    if wide.any():
        errs.append(f"{int(wide.sum())} rows with spread > {cfg['max_spread_bps']} bps")
    same_day = ts.dt.date.eq(ts.dt.date.shift())
    gaps = (ts.diff().dt.total_seconds() / 60)[same_day] > cfg["max_gap_minutes"]
    if gaps.any():
        errs.append(f"{int(gaps.sum())} intraday gaps longer than {cfg['max_gap_minutes']} minutes")
    return GateResult(not errs, errs, n)


def _split(t: pd.DataFrame, holdout: float):
    days = sorted(t.ts.dt.normalize().unique())
    cut = days[max(1, int(len(days) * (1 - holdout)))]
    return t[t.ts < cut], t[t.ts >= cut]


def compute(t: pd.DataFrame, strategy_factory, cfg: ExecConfig, promo: dict, trials: int = 1) -> tuple[dict, list[dict], object]:
    """Run the full backtest plus the stress and holdout runs. Returns (metrics, checks, main result)."""
    res = Backtest(t, strategy_factory(), cfg).run()
    net, gross = perf(res.bars.equity, res.bars_per_year), perf(res.bars.gross_equity, res.bars_per_year)
    ts_ = trade_stats(res.fills, res.bars, cfg.init_cash)
    stress = Backtest(t, strategy_factory(), cfg.scaled_costs(promo["stress_cost_multiple"])).run()
    s_net = perf(stress.bars.equity, stress.bars_per_year)
    is_t, oos_t = _split(t, promo["holdout_share"])
    is_r = Backtest(is_t, strategy_factory(), cfg).run()
    oos_r = Backtest(oos_t, strategy_factory(), cfg).run()
    is_s = perf(is_r.bars.equity, res.bars_per_year).get("Sharpe", 0.0)
    oos_s = perf(oos_r.bars.equity, res.bars_per_year).get("Sharpe", 0.0)
    years = len(res.bars) / res.bars_per_year
    haircut = math.sqrt(2 * math.log(max(trials, 1)))
    t_stat = net.get("Sharpe", 0.0) * math.sqrt(years)
    f = res.fills
    r = lambda x, k=4: None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), k)
    m = {
        "strategy": res.strategy, "bar": cfg.bar, "days": int(t.ts.dt.date.nunique()), "years": r(years),
        "net_sharpe": r(net.get("Sharpe"), 3), "gross_sharpe": r(gross.get("Sharpe"), 3),
        "net_total_return": r(net.get("Total return")), "gross_total_return": r(gross.get("Total return")),
        "max_drawdown": r(net.get("Max drawdown")), "annualised_vol": r(net.get("Annualised vol")),
        "fills": int(ts_.get("Fills", 0)),
        "avg_cost_bps": r(ts_.get("Avg cost per fill (bps)"), 2) if len(f) else 0.0,
        "avg_shortfall_bps": r(ts_.get("Avg implementation shortfall (bps)"), 2) if len(f) else 0.0,
        "time_in_market": r(ts_.get("Time in market"), 3) if len(f) else 0.0,
        "cost_spread_usd": r(f.spread_cost.sum(), 2) if len(f) else 0.0,
        "cost_impact_usd": r(f.impact_cost.sum(), 2) if len(f) else 0.0,
        "cost_commission_usd": r(f.commission.sum(), 2) if len(f) else 0.0,
        "cost_latency_usd": r(f.delay_cost.sum(), 2) if len(f) else 0.0,
        "is_sharpe": r(is_s, 3), "oos_sharpe": r(oos_s, 3),
        "degradation": r(1 - oos_s / is_s, 3) if is_s > 0 else None,
        "trials": int(trials), "t_stat": r(t_stat, 3), "selection_haircut": r(haircut, 3),
        "selection_adjusted_t": r(t_stat - haircut, 3),
        "sharpe_at_stress_costs": r(s_net.get("Sharpe"), 3), "stress_cost_multiple": promo["stress_cost_multiple"],
        "lookahead_errors": len(res.errors),
    }
    checks = [
        _c("lookahead_clean", m["lookahead_errors"], "== 0", m["lookahead_errors"] == 0),
        _c("enough_fills", m["fills"], f">= {promo['min_fills']}", m["fills"] >= promo["min_fills"]),
        _c("significance", m["selection_adjusted_t"], f">= {promo['min_selection_adjusted_t']}",
           (m["selection_adjusted_t"] or -9) >= promo["min_selection_adjusted_t"]),
        _c("out_of_sample", m["oos_sharpe"], f"> {promo['min_oos_sharpe']}", (m["oos_sharpe"] or -9) > promo["min_oos_sharpe"]),
        _c("degradation", m["degradation"], f"<= {promo['max_degradation']}",
           m["degradation"] is None and (m["is_sharpe"] or 0) <= 0 and (m["oos_sharpe"] or -9) > 0
           or (m["degradation"] is not None and m["degradation"] <= promo["max_degradation"])),
        _c("cost_robustness", m["sharpe_at_stress_costs"], "> 0", (m["sharpe_at_stress_costs"] or -9) > 0),
    ]
    return m, checks, res


def _c(name, value, threshold, ok) -> dict:
    return {"check": name, "value": value, "threshold": threshold, "passed": bool(ok)}
