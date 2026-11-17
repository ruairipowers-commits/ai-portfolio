"""Grid sweeps and walk-forward optimisation on the C++ kernel."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .data import as_arrays
from .engine import ExecConfig
from .metrics import perf


def bars_per_year(ticks: pd.DataFrame, bar: str) -> float:
    b = ticks.ts.dt.floor(bar)
    return float(b.groupby(ticks.ts.dt.date).nunique().median() * 252)


def sweep(ticks, fasts, slows, cfg: ExecConfig, long_only=False, threads=0):
    import qlbt_core
    ts, b, a, _ = as_arrays(ticks)
    bpy = bars_per_year(ticks, cfg.bar)
    t0 = time.perf_counter()
    r = qlbt_core.sweep_ma_cross(ts, b, a, list(fasts), list(slows), cfg.kernel_params(long_only), bpy, threads)
    r["seconds"] = time.perf_counter() - t0
    r["bars_per_year"] = bpy
    return r


def walk_forward(ticks, fasts, slows, cfg: ExecConfig, n_folds=5, train_frac=0.7, anchored=False, long_only=False,
                 metric="sharpe"):
    """Split days into folds. In each fold: optimise (fast, slow) on the training window, then
    trade the next out-of-sample window with the chosen pair. OOS equity is stitched together."""
    import qlbt_core
    days = np.array(sorted(ticks.ts.dt.normalize().unique()))
    if len(days) < n_folds + 2:
        raise ValueError("Not enough days for that many folds.")
    fold_len = len(days) / (n_folds + (train_frac / (1 - train_frac)))
    train_len = max(2, int(round(fold_len * train_frac / (1 - train_frac))))
    test_len = max(1, int(round(fold_len)))
    bpy = bars_per_year(ticks, cfg.bar)
    rows, oos = [], []
    eq_scale = cfg.init_cash
    start = 0
    for k in range(n_folds):
        tr0 = 0 if anchored else start
        tr1 = start + train_len
        te1 = min(tr1 + test_len, len(days))
        if tr1 >= len(days) or te1 <= tr1:
            break
        tr = ticks[(ticks.ts >= days[tr0]) & (ticks.ts < days[tr1])]
        te = ticks[(ticks.ts >= days[tr1]) & (ticks.ts < (days[te1] if te1 < len(days) else days[-1] + np.timedelta64(1, "D")))]
        g = sweep(tr, fasts, slows, cfg, long_only)
        m = np.where(np.isnan(g[metric]), -np.inf, g[metric])
        i, j = np.unravel_index(np.argmax(m), m.shape)
        f, s = fasts[i], slows[j]
        ts, b, a, _ = as_arrays(te)
        p = cfg.kernel_params(long_only)
        p["init_cash"] = eq_scale
        r = qlbt_core.run_ma_cross(ts, b, a, int(f), int(s), p)
        oos_perf = perf(r["equity"], bpy)
        eq_scale = r["equity"][-1]
        oos.append(pd.DataFrame({"ts": pd.to_datetime(r["bar_end"]), "equity": r["equity"], "fold": k + 1}))
        rows.append({"fold": k + 1, "train": f"{pd.Timestamp(days[tr0]).date()} → {pd.Timestamp(days[tr1 - 1]).date()}",
                     "test": f"{pd.Timestamp(days[tr1]).date()} → {pd.Timestamp(days[te1 - 1]).date()}",
                     "fast": f, "slow": s, "IS sharpe": g["sharpe"][i, j], "OOS sharpe": oos_perf.get("Sharpe", np.nan),
                     "OOS return": oos_perf.get("Total return", np.nan)})
        start += test_len
    return pd.DataFrame(rows), (pd.concat(oos, ignore_index=True) if oos else pd.DataFrame())
