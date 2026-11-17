"""Tick data: a realistic synthetic generator and a CSV loader."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

TICK_SIZE = 0.01
SESSION = (9.5, 16.0)  # hours, US equities regular session


def synthetic_ticks(
    days: int = 60,
    ticks_per_day: int = 8_000,
    start_price: float = 100.0,
    annual_vol: float = 0.25,
    trend_strength: float = 0.012,
    trend_persistence: float = 0.98,
    vol_regimes: bool = True,
    jumps_per_day: float = 0.3,
    spread_bps: float = 2.0,
    overnight_gap_vol: float = 0.006,
    start: str = "2026-01-05",
    seed: int = 7,
) -> pd.DataFrame:
    """Quote/trade ticks with U-shaped intraday activity, persistent intraday drift regimes
    (so trend and mean-reversion strategies both have something to find), volatility regimes,
    jumps, overnight gaps and a stochastic, open/close-widened bid-ask spread on a 1-cent grid."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days)
    sess_sec = (SESSION[1] - SESSION[0]) * 3600
    sigma_day = annual_vol / np.sqrt(252)

    # U-shaped intensity -> inverse-CDF sampling of tick times
    grid = np.linspace(0, 1, 2001)
    inten = 1 + 3.0 * (2 * grid - 1) ** 4
    cdf = np.cumsum(inten); cdf = (cdf - cdf[0]) / (cdf[-1] - cdf[0])

    frames = []
    logp = np.log(start_price)
    vol_state = 1.0
    for d in dates:
        n = int(ticks_per_day * rng.uniform(0.8, 1.2))
        u = np.sort(rng.uniform(0, 1, n))
        frac = np.interp(u, cdf, grid)
        t_ns = (d + pd.Timedelta(hours=SESSION[0])).value + (frac * sess_sec * 1e9).astype(np.int64)
        t_ns = np.maximum.accumulate(t_ns + np.arange(n))  # strictly increasing

        if vol_regimes and rng.uniform() < 0.25:
            vol_state = rng.choice([0.6, 1.0, 1.8], p=[0.35, 0.45, 0.2])
        # per-tick diffusion scaled by local activity so daily variance matches sigma_day
        local = np.interp(frac, grid, inten); local = local / local.mean()
        step_sd = sigma_day * vol_state / np.sqrt(n)
        eps = rng.standard_normal(n) * step_sd
        # persistent drift (AR(1) on a coarse clock) -> intraday trends that MA strategies can catch
        k = 50
        nd = n // k + 1
        dr = np.zeros(nd)
        for i in range(1, nd):
            dr[i] = trend_persistence * dr[i - 1] + np.sqrt(1 - trend_persistence ** 2) * rng.standard_normal()
        drift = np.repeat(dr, k)[:n] * trend_strength * step_sd
        jumps = np.zeros(n)
        nj = rng.poisson(jumps_per_day)
        if nj:
            jumps[rng.integers(0, n, nj)] = rng.standard_normal(nj) * 4 * sigma_day * vol_state / np.sqrt(8)
        logp += rng.standard_normal() * overnight_gap_vol
        path = logp + np.cumsum(eps + drift + jumps)
        logp = path[-1]
        mid = np.exp(path)

        widen = 1 + 1.5 * (2 * frac - 1) ** 8
        half = mid * spread_bps / 2e4 * widen * rng.lognormal(0, 0.25, n)
        spread_ticks = np.maximum(1, np.round(2 * half / TICK_SIZE)).astype(int)
        bid = np.floor((mid - spread_ticks * TICK_SIZE / 2) / TICK_SIZE + 1e-9) * TICK_SIZE
        ask = bid + spread_ticks * TICK_SIZE
        vol = np.ceil(rng.lognormal(4.0, 1.0, n) / 10) * 10
        side = rng.uniform(size=n) < 0.5 + 0.4 * np.tanh(np.r_[0, np.diff(mid)] / (step_sd * mid + 1e-12))
        last = np.where(side, ask, bid)
        frames.append(pd.DataFrame({
            "ts": t_ns, "bid": np.round(bid, 2), "ask": np.round(ask, 2),
            "bid_size": rng.integers(1, 30, n) * 100, "ask_size": rng.integers(1, 30, n) * 100,
            "last": np.round(last, 2), "volume": vol,
        }))
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df.ts)
    return df


def load_csv(buf: bytes | str, default_spread_bps: float = 2.0) -> pd.DataFrame:
    """Accepts ts,bid,ask[,volume] quotes or ts,price[,volume] trades (spread synthesised)."""
    df = pd.read_csv(io.BytesIO(buf) if isinstance(buf, bytes) else buf)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in df.columns if c in ("ts", "timestamp", "time", "datetime", "date")), None)
    if tcol is None:
        raise ValueError("CSV needs a timestamp column (ts / timestamp / time / datetime).")
    out = pd.DataFrame({"ts": pd.to_datetime(df[tcol])})
    if {"bid", "ask"} <= set(df.columns):
        out["bid"], out["ask"] = df.bid.astype(float), df.ask.astype(float)
    else:
        pcol = next((c for c in df.columns if c in ("price", "last", "close", "mid")), None)
        if pcol is None:
            raise ValueError("CSV needs bid/ask columns or a price column.")
        p = df[pcol].astype(float)
        hs = np.maximum(TICK_SIZE / 2, p * default_spread_bps / 2e4)
        out["bid"], out["ask"] = (p - hs).round(4), (p + hs).round(4)
    out["volume"] = df["volume"].astype(float) if "volume" in df.columns else 100.0
    out["last"] = df["last"].astype(float) if "last" in df.columns else (out.bid + out.ask) / 2
    out = out.dropna().sort_values("ts", kind="stable").reset_index(drop=True)
    if (out.ask < out.bid).any():
        raise ValueError("Found rows with ask < bid.")
    return out


def as_arrays(ticks: pd.DataFrame):
    return (ticks.ts.values.astype("datetime64[ns]").astype(np.int64),
            ticks.bid.to_numpy(np.float64), ticks.ask.to_numpy(np.float64),
            ticks.volume.to_numpy(np.float64))


def resample(ticks: pd.DataFrame, bar: str = "5min") -> pd.DataFrame:
    """Bars from ticks using the C++ kernel (falls back to pandas)."""
    bar_ns = pd.Timedelta(bar).value
    try:
        from . import _core as qlbt_core
        ts, b, a, v = as_arrays(ticks)
        r = qlbt_core.resample_ticks(ts, b, a, v, bar_ns)
        df = pd.DataFrame({k: r[k] for k in ["open", "high", "low", "close", "volume", "vwap", "avg_spread", "ticks"]})
        df.insert(0, "ts", pd.to_datetime(r["ts"]))
        return df
    except ImportError:
        return resample_pandas(ticks, bar)


def resample_pandas(ticks: pd.DataFrame, bar: str = "5min") -> pd.DataFrame:
    t = ticks.assign(mid=(ticks.bid + ticks.ask) / 2, spr=ticks.ask - ticks.bid, pv=lambda x: x.volume * (x.bid + x.ask) / 2)
    g = t.groupby(t.ts.dt.floor(bar))
    df = g.mid.ohlc()
    df["volume"] = g.volume.sum()
    df["vwap"] = g.pv.sum() / df.volume
    df["avg_spread"] = g.spr.mean()
    df["ticks"] = g.size()
    return df.reset_index().rename(columns={"ts": "ts"})
