"""Event-driven tick backtester.

Components talk only through events on a time-ordered queue:

    DataHandler --TickEvent/BarEvent--> Strategy --target--> Portfolio --OrderEvent--> ExecutionHandler
         ^                                                                    |
         +------------------------------ FillEvent <---------------------------+

Lookahead protection
--------------------
* The DataHandler streams ticks one at a time; a bar is only published once a tick from a *later*
  bucket arrives, so a strategy never sees an incomplete bar.
* Strategies receive a `History` that exposes completed bars only (read-only views). Asking for
  anything beyond "now" raises `LookaheadError`.
* Orders become active at decision time + latency and fill against the first tick at or after
  activation: you can't trade at the price that generated your signal.
* `fill_mode="same_bar_close"` deliberately breaks the last rule so you can measure the bias.
"""
from __future__ import annotations

import heapq
import itertools
import math
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .data import as_arrays


class LookaheadError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- events
TICK, BAR, ORDER, FILL = "TICK", "BAR", "ORDER", "FILL"
PRIO = {BAR: 0, FILL: 1, ORDER: 2, TICK: 3}


@dataclass
class Event:
    kind: str
    ts: int
    payload: object = None


class EventQueue:
    def __init__(self):
        self._h, self._c = [], itertools.count()
        self.counts = {k: 0 for k in PRIO}

    def put(self, ev: Event):
        self.counts[ev.kind] += 1
        heapq.heappush(self._h, (ev.ts, PRIO[ev.kind], next(self._c), ev))

    def get(self) -> Event:
        return heapq.heappop(self._h)[3]

    def __bool__(self):
        return bool(self._h)


# ----------------------------------------------------------------------------- config
@dataclass
class ExecConfig:
    bar: str = "5min"
    size: float = 500.0                 # shares per unit of target
    latency_ms: float = 0.0
    order_type: str = "market"          # "market" | "limit" (passive join, converts to market after timeout)
    limit_timeout_bars: int = 1
    comm_per_share: float = 0.0035
    comm_bps: float = 0.0
    min_comm: float = 0.35
    slip_bps: float = 0.0
    impact_bps_at_1pct: float = 10.0    # square-root impact: bps paid for an order of 1% of ADV
    adv: float = 2_000_000.0
    init_cash: float = 100_000.0
    fill_mode: str = "next_tick"        # "next_tick" | "same_bar_close" (biased, for the demo)

    @property
    def bar_ns(self) -> int:
        return pd.Timedelta(self.bar).value

    def kernel_params(self, long_only: bool = False) -> dict:
        return dict(size=self.size, long_only=long_only, bar_ns=self.bar_ns, latency_ns=int(self.latency_ms * 1e6),
                    comm_per_share=self.comm_per_share, comm_bps=self.comm_bps, min_comm=self.min_comm,
                    slip_bps=self.slip_bps, impact_bps_at_1pct=self.impact_bps_at_1pct, adv=self.adv,
                    init_cash=self.init_cash)

    def scaled_costs(self, k: float) -> "ExecConfig":
        d = asdict(self)
        for f in ("comm_per_share", "comm_bps", "min_comm", "slip_bps", "impact_bps_at_1pct"):
            d[f] *= k
        return ExecConfig(**d)


# ----------------------------------------------------------------------------- history (lookahead guard)
class History:
    """Completed bars only. Index 0 = oldest, -1 = the bar that just closed."""

    FIELDS = ("ts", "open", "high", "low", "close", "volume", "vwap", "spread")

    def __init__(self, capacity: int):
        self._a = {f: np.zeros(capacity, dtype=np.int64 if f == "ts" else np.float64) for f in self.FIELDS}
        self.n = 0

    def _append(self, **bar):
        if self.n == len(self._a["ts"]):
            for f in self.FIELDS:
                self._a[f] = np.concatenate([self._a[f], np.zeros_like(self._a[f])])
        for f in self.FIELDS:
            self._a[f][self.n] = bar[f]
        self.n += 1

    def __len__(self):
        return self.n

    def _view(self, f):
        v = self._a[f][: self.n].view()
        v.flags.writeable = False
        return v

    def __getattr__(self, f):
        if f in History.FIELDS:
            return self._view(f)
        raise AttributeError(f)

    def at(self, i: int, f: str = "close"):
        """Absolute bar index access with an explicit future check."""
        if i >= self.n:
            raise LookaheadError(f"bar {i} requested at bar {self.n - 1}: that bar hasn't closed yet")
        return self._a[f][i]

    def ago(self, k: int, f: str = "close"):
        if k < 0:
            raise LookaheadError(f"ago({k}) asks for the future")
        return self._a[f][self.n - 1 - k]


@dataclass
class Context:
    bars: History
    position: float
    cash: float
    equity: float
    bar_index: int
    time: pd.Timestamp
    state: dict


# ----------------------------------------------------------------------------- portfolio / execution
@dataclass
class Order:
    qty: float
    decision_ts: int
    active_ts: int
    arrival_mid: float
    otype: str
    limit: float | None
    bar_index: int
    expire_bar: int


class Execution:
    def __init__(self, cfg: ExecConfig):
        self.cfg = cfg
        self.pending: Order | None = None

    def fill_price(self, qty, bid, ask):
        c = self.cfg
        sgn = 1.0 if qty > 0 else -1.0
        q = abs(qty)
        quote = ask if sgn > 0 else bid
        impact = c.impact_bps_at_1pct * math.sqrt(100.0 * q / c.adv) if (c.adv > 0 and c.impact_bps_at_1pct > 0) else 0.0
        px = quote * (1.0 + sgn * (c.slip_bps + impact) / 1e4)
        return sgn, q, quote, px

    def commission(self, q, px):
        c = self.cfg
        return max(c.min_comm, q * c.comm_per_share + px * q * c.comm_bps / 1e4)

    def on_tick(self, ts, bid, ask, bar_index):
        """Return a fill dict if the pending order executes on this tick."""
        o = self.pending
        if o is None or ts < o.active_ts:
            return None
        mid = 0.5 * (bid + ask)
        if o.otype == "limit" and bar_index < o.expire_bar:
            hit = (o.qty > 0 and ask <= o.limit) or (o.qty < 0 and bid >= o.limit)
            if not hit:
                return None
            sgn, q = (1.0 if o.qty > 0 else -1.0), abs(o.qty)
            px, quote = o.limit, o.limit
            otype = "limit"
        else:
            sgn, q, quote, px = self.fill_price(o.qty, bid, ask)
            otype = "market" if o.otype == "market" else "limit→market"
        comm = self.commission(q, px)
        self.pending = None
        return dict(ts=ts, decision_ts=o.decision_ts, bar_index=o.bar_index, side="buy" if sgn > 0 else "sell", qty=q,
                    signed_qty=sgn * q, price=px, quote=quote, mid=mid, arrival_mid=o.arrival_mid, commission=comm,
                    spread_cost=q * (abs(quote - mid) if otype != "limit" else -abs(quote - mid)),
                    impact_cost=q * abs(px - quote), delay_cost=sgn * q * (mid - o.arrival_mid), otype=otype)


class Portfolio:
    def __init__(self, cfg: ExecConfig):
        self.cfg = cfg
        self.pos = 0.0
        self.cash = cfg.init_cash
        self.ppos = 0.0                 # frictionless paper portfolio (trades at bar close mid)
        self.pcash = cfg.init_cash
        self.target: float | None = None
        self.fills: list[dict] = []

    def apply_fill(self, f):
        self.cash -= f["signed_qty"] * f["price"] + f["commission"]
        self.pos += f["signed_qty"]
        self.fills.append(f)


# ----------------------------------------------------------------------------- strategy base
class Strategy:
    name = "base"
    long_only = False

    def on_bar(self, ctx: Context) -> float | None:
        """Return a target exposure in units (+1 long `size` shares, -1 short), or None to keep the last target."""
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


# ----------------------------------------------------------------------------- results
@dataclass
class Result:
    bars: pd.DataFrame
    fills: pd.DataFrame
    events: dict
    runtime_s: float
    ticks: int
    cfg: ExecConfig
    strategy: str
    bars_per_year: float
    errors: list = field(default_factory=list)


# ----------------------------------------------------------------------------- the engine
class Backtest:
    def __init__(self, ticks: pd.DataFrame, strategy: Strategy, cfg: ExecConfig):
        self.ticks, self.strategy, self.cfg = ticks, strategy, cfg

    def run(self, progress=None) -> Result:
        cfg, strat = self.cfg, self.strategy
        ts, bid, ask, vol = as_arrays(self.ticks)
        n = len(ts)
        bar_ns = cfg.bar_ns
        q = EventQueue()
        ex, pf = Execution(cfg), Portfolio(cfg)
        hist = History(capacity=max(16, int((ts[-1] - ts[0]) // bar_ns) // 4 + 16))
        state: dict = {}
        rows = []
        errors = []
        t0 = time.perf_counter()

        # bar accumulator (data handler state)
        cur = ts[0] // bar_ns
        acc = dict(open=None, high=-np.inf, low=np.inf, close=0.0, volume=0.0, pv=0.0, spr=0.0, cnt=0)
        last_mid = 0.5 * (bid[0] + ask[0])
        last_bid, last_ask = bid[0], ask[0]
        i_next = 0

        def push_tick(i):
            q.put(Event(TICK, int(ts[i]), i))

        push_tick(0)
        report = max(1, n // 50)
        while q:
            ev = q.get()
            if ev.kind == TICK:
                i = ev.payload
                b = ts[i] // bar_ns
                if b != cur:
                    # publish the completed bar before this tick is processed
                    q.put(Event(BAR, int((cur + 1) * bar_ns), dict(acc)))
                    q.put(Event(TICK, int(ts[i]), i))  # re-queue tick behind the bar
                    cur = b
                    acc = dict(open=None, high=-np.inf, low=np.inf, close=0.0, volume=0.0, pv=0.0, spr=0.0, cnt=0)
                    continue
                f = ex.on_tick(int(ts[i]), bid[i], ask[i], hist.n - 1)
                if f is not None:
                    q.put(Event(FILL, int(ts[i]), f))
                m = 0.5 * (bid[i] + ask[i])
                if acc["open"] is None:
                    acc["open"] = m
                acc["high"] = max(acc["high"], m); acc["low"] = min(acc["low"], m); acc["close"] = m
                acc["volume"] += vol[i]; acc["pv"] += vol[i] * m; acc["spr"] += ask[i] - bid[i]; acc["cnt"] += 1
                last_mid, last_bid, last_ask = m, bid[i], ask[i]
                if i + 1 < n:
                    push_tick(i + 1)
                elif not acc.get("final"):
                    acc["final"] = True
                    q.put(Event(BAR, int((cur + 1) * bar_ns), dict(acc)))
                if progress and i % report == 0:
                    progress(i / n)
            elif ev.kind == FILL:
                pf.apply_fill(ev.payload)
            elif ev.kind == BAR:
                a = ev.payload
                c = a["close"]
                hist._append(ts=ev.ts, open=a["open"], high=a["high"], low=a["low"], close=c, volume=a["volume"],
                             vwap=a["pv"] / a["volume"] if a["volume"] else c, spread=a["spr"] / max(a["cnt"], 1))
                eq, geq = pf.cash + pf.pos * c, pf.pcash + pf.ppos * c
                rows.append((ev.ts, c, eq, geq, pf.pos, pf.target if pf.target is not None else np.nan))
                ctx = Context(hist, pf.pos, pf.cash, eq, hist.n - 1, pd.Timestamp(ev.ts), state)
                try:
                    tgt = strat.on_bar(ctx)
                except LookaheadError as e:
                    errors.append(f"bar {hist.n - 1}: {e}")
                    tgt = None
                if tgt is not None and np.isfinite(tgt):
                    pf.target = float(np.round(tgt * cfg.size))
                if pf.target is not None:
                    pf.pcash -= (pf.target - pf.ppos) * c
                    pf.ppos = pf.target
                    qty = pf.target - pf.pos
                    if qty == 0:
                        ex.pending = None
                    elif ex.pending is not None and ex.pending.qty == qty:
                        pass  # working order already has the right size: keep its place/clock
                    elif cfg.fill_mode == "same_bar_close":
                        # BIASED: trade at the very price that produced the signal, no spread, no latency
                        pf.apply_fill(dict(ts=ev.ts, decision_ts=ev.ts, bar_index=hist.n - 1, side="buy" if qty > 0 else "sell",
                                           qty=abs(qty), signed_qty=qty, price=c, quote=c, mid=c, arrival_mid=c,
                                           commission=ex.commission(abs(qty), c), spread_cost=0.0, impact_cost=0.0,
                                           delay_cost=0.0, otype="close (biased)"))
                    else:
                        lim = (last_bid if qty > 0 else last_ask) if cfg.order_type == "limit" else None
                        o = Order(qty, ev.ts, ev.ts + int(cfg.latency_ms * 1e6), c, cfg.order_type, lim, hist.n - 1,
                                  hist.n - 1 + cfg.limit_timeout_bars)
                        ex.pending = o
                        q.put(Event(ORDER, ev.ts, o))
            # ORDER events are informational: Execution already holds the working order.

        bars = pd.DataFrame(rows, columns=["ts", "close", "equity", "gross_equity", "position", "target"])
        bars["ts"] = pd.to_datetime(bars.ts)
        bars["drawdown"] = bars.equity / bars.equity.cummax() - 1
        fills = pd.DataFrame(pf.fills)
        if not fills.empty:
            for c_ in ("ts", "decision_ts"):
                fills[c_] = pd.to_datetime(fills[c_])
            fills["delay_ms"] = (fills.ts - fills.decision_ts).dt.total_seconds() * 1e3
            fills["shortfall_bps"] = np.sign(fills.signed_qty) * (fills.price - fills.arrival_mid) / fills.arrival_mid * 1e4
        per_day = bars.groupby(bars.ts.dt.date).size().median() if len(bars) else 1
        return Result(bars, fills, dict(q.counts), time.perf_counter() - t0, n, cfg, strat.describe(),
                      float(per_day) * 252, errors)


def run_kernel(ticks: pd.DataFrame, fast: int, slow: int, cfg: ExecConfig, long_only: bool = False) -> dict:
    """Same MA-cross backtest through the C++ kernel."""
    from . import _core as qlbt_core
    ts, b, a, _ = as_arrays(ticks)
    return qlbt_core.run_ma_cross(ts, b, a, fast, slow, cfg.kernel_params(long_only))
