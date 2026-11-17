"""Example strategies. Each returns a target exposure in units of `size` shares (or None = keep)."""
from __future__ import annotations

import math

import numpy as np

from .engine import Context, Strategy


class MACross(Strategy):
    """Long when the fast SMA of bar closes is above the slow SMA, short (or flat) below.
    Sums are taken left-to-right exactly like the C++ kernel, so both engines agree bit-for-bit."""

    def __init__(self, fast: int = 10, slow: int = 40, long_only: bool = False):
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast, self.slow, self.long_only = fast, slow, long_only
        self.name = f"MA cross {fast}/{slow}" + (" long-only" if long_only else "")

    def on_bar(self, ctx: Context):
        c = ctx.bars.close
        k = len(c)
        if k < self.slow:
            return None
        f = sum(c[k - self.fast:].tolist()) / self.fast
        s = sum(c[k - self.slow:].tolist()) / self.slow
        tol = 1e-12 * abs(s)  # mids sit on a half-cent grid, so exact ties are common: treat near-ties as no signal
        if f > s + tol:
            return 1.0
        if f < s - tol:
            return 0.0 if self.long_only else -1.0
        return None


class BollingerReversion(Strategy):
    """Fade z-score extremes of close vs its rolling mean; exit when it reverts toward the mean."""

    def __init__(self, window: int = 30, entry_z: float = 2.0, exit_z: float = 0.5, long_only: bool = False):
        self.window, self.entry_z, self.exit_z, self.long_only = window, entry_z, exit_z, long_only
        self.name = f"Bollinger reversion w={window} in={entry_z} out={exit_z}"

    def on_bar(self, ctx: Context):
        c = ctx.bars.close
        if len(c) < self.window:
            return None
        w = c[-self.window:]
        sd = w.std(ddof=1)
        if sd == 0:
            return None
        z = (c[-1] - w.mean()) / sd
        pos = np.sign(ctx.position)
        if z <= -self.entry_z:
            return 1.0
        if z >= self.entry_z:
            return 0.0 if self.long_only else -1.0
        if (pos > 0 and z >= -self.exit_z) or (pos < 0 and z <= self.exit_z):
            return 0.0
        return None


class DonchianBreakout(Strategy):
    """Enter on a break of the N-bar high/low, exit on the opposite M-bar channel."""

    def __init__(self, entry: int = 40, exit: int = 20, long_only: bool = False):
        self.entry, self.exit, self.long_only = entry, exit, long_only
        self.name = f"Donchian breakout {entry}/{exit}"

    def on_bar(self, ctx: Context):
        h, l, c = ctx.bars.high, ctx.bars.low, ctx.bars.close
        if len(c) <= self.entry:
            return None
        hi, lo = h[-self.entry - 1:-1].max(), l[-self.entry - 1:-1].min()   # channel excludes the current bar
        xhi, xlo = h[-self.exit - 1:-1].max(), l[-self.exit - 1:-1].min()
        pos = np.sign(ctx.position)
        if c[-1] > hi:
            return 1.0
        if c[-1] < lo:
            return 0.0 if self.long_only else -1.0
        if (pos > 0 and c[-1] < xlo) or (pos < 0 and c[-1] > xhi):
            return 0.0
        return None


class VolTargetMomentum(Strategy):
    """Sign of the lookback return, sized so expected volatility hits a target (fractional exposure)."""

    def __init__(self, lookback: int = 48, vol_window: int = 96, target_vol_bps: float = 15.0, max_units: float = 3.0):
        self.lookback, self.vol_window, self.target, self.max_units = lookback, vol_window, target_vol_bps, max_units
        self.name = f"Vol-target momentum lb={lookback}"

    def on_bar(self, ctx: Context):
        c = ctx.bars.close
        if len(c) <= max(self.lookback, self.vol_window):
            return None
        r = np.diff(np.log(c[-self.vol_window - 1:]))
        vol_bps = r.std(ddof=1) * 1e4
        if vol_bps == 0:
            return None
        sig = math.copysign(1.0, c[-1] / c[-1 - self.lookback] - 1)
        return float(np.clip(sig * self.target / vol_bps, -self.max_units, self.max_units))


class LeakyStrategy(Strategy):
    """Deliberately tries to read the next bar's close. The History guard stops it."""
    name = "Leaky (peeks at next bar)"

    def on_bar(self, ctx: Context):
        nxt = ctx.bars.at(ctx.bar_index + 1)  # raises LookaheadError
        return 1.0 if nxt > ctx.bars.close[-1] else -1.0


class CodeStrategy(Strategy):
    """Wraps user code that defines `on_bar(ctx)`; `np`, `math` and `state` are available."""

    def __init__(self, code: str, name: str = "Custom"):
        ns = {"np": np, "math": math}
        exec(compile(code, "<strategy>", "exec"), ns)  # local, single-user app
        if "on_bar" not in ns:
            raise ValueError("Your code must define on_bar(ctx).")
        self._fn = ns["on_bar"]
        self.name = name

    def on_bar(self, ctx: Context):
        return self._fn(ctx)


CUSTOM_TEMPLATE = '''# ctx.bars.{open,high,low,close,volume,vwap,spread,ts}: numpy arrays of COMPLETED bars only
# ctx.position (shares), ctx.cash, ctx.equity, ctx.bar_index, ctx.time, ctx.state (dict you can use)
# Return a target in units of "size" shares (1 = long, -1 = short, 0 = flat), or None to keep the last one.

def on_bar(ctx):
    c = ctx.bars.close
    if len(c) < 60:
        return None
    # RSI-style mean reversion on 14 bars, but only trade with the 60-bar trend
    d = np.diff(c[-15:])
    up, dn = d.clip(min=0).mean(), (-d).clip(min=0).mean()
    rsi = 100 if dn == 0 else 100 - 100 / (1 + up / dn)
    trend_up = c[-1] > c[-60:].mean()
    if trend_up and rsi < 30:
        return 1
    if not trend_up and rsi > 70:
        return -1
    if (ctx.position > 0 and rsi > 55) or (ctx.position < 0 and rsi < 45):
        return 0
    return None
'''
