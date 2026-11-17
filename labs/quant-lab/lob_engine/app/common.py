"""Shared state and helpers for the LOB Streamlit app."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import lob_engine as L

TICK = 0.01
BAND = (5_000, 15_000)  # $50.00 .. $150.00
GREEN, RED, GREY = "#1a9850", "#d73027", "#8c8c8c"
TRADERS = {1: "You", 2: "Alice (MM)", 3: "Bob", 4: "Carol", 5: "Dave", 99: "Noise flow"}


def px(t: int | None) -> float | None:
    return None if t is None else round(t * TICK, 2)


def ticks(p: float) -> int:
    return int(round(p / TICK))


def tname(t: int) -> str:
    return TRADERS.get(t, f"T{t}")


@dataclass
class Desk:
    book: L.OrderBook
    tape: list = field(default_factory=list)
    log: list = field(default_factory=list)
    fills: list = field(default_factory=list)  # per-trader fills
    seq: int = 0

    def record(self, events: list[dict], source: str):
        self.seq += 1
        for e in events:
            row = {"#": self.seq, "source": source, **e}
            self.log.append(row)
            if e["event"] == "trade":
                self.tape.append({"#": self.seq, "price": px(e["price"]), "qty": e["qty"], "aggressor": e["aggressor"],
                                  "taker": tname(e["taker_trader"]), "maker": tname(e["maker_trader"])})
                taker_sign = 1 if e["aggressor"] == "buy" else -1
                self.fills.append({"trader": e["taker_trader"], "qty": taker_sign * e["qty"], "price": e["price"], "role": "taker", "order": e["taker"]})
                self.fills.append({"trader": e["maker_trader"], "qty": -taker_sign * e["qty"], "price": e["price"], "role": "maker", "order": e["maker"]})
        self.log = self.log[-2000:]

    def submit(self, side, otype, price_t, qty, trader, trigger_t=None, source="ticket"):
        oid, ev = self.book.submit(side, otype, price_t, qty, trader, trigger_t)
        self.record(ev, source)
        return oid, ev

    def noise(self, n: int, aggression: float = 0.15, rng: random.Random | None = None):
        """Python-side random flow from several named traders (so your resting orders can get hit)."""
        rng = rng or random.Random()
        for _ in range(n):
            bb, ba = self.book.best_bid, self.book.best_ask
            mid = ((bb + ba) / 2) if bb and ba else (self.book.last_price or 10_000)
            trader = rng.choice([2, 3, 4, 5, 99])
            side = rng.choice(["buy", "sell"])
            r = rng.random()
            if r < aggression:
                self.submit(side, "market", 0, rng.randint(1, 40), trader, source="noise")
            elif r < 0.8:
                off = 1 + int(rng.expovariate(1 / 6))
                p = int(mid - off) if side == "buy" else int(mid + off + 0.5)
                self.submit(side, "limit", p, rng.randint(1, 60), trader, source="noise")
            else:
                mine = self.book.open_orders(trader)
                if mine:
                    oid, ev = self.book.cancel(rng.choice(mine)["id"])
                    self.record(ev, "noise")


def get_desk() -> Desk:
    if "desk" not in st.session_state:
        st.session_state.desk = new_desk()
    return st.session_state.desk


def new_desk(seed: int = 7) -> Desk:
    book = L.OrderBook(*BAND, stp=True)
    d = Desk(book)
    d.noise(600, aggression=0.02, rng=random.Random(seed))
    d.tape.clear(); d.log.clear(); d.fills.clear()
    return d


def depth_frame(book: L.OrderBook, levels: int = 15) -> pd.DataFrame:
    dp = book.depth(levels)
    rows = [{"side": "bid", "price": px(p), "qty": q, "orders": c} for p, q, c in dp["bids"]]
    rows += [{"side": "ask", "price": px(p), "qty": q, "orders": c} for p, q, c in dp["asks"]]
    df = pd.DataFrame(rows, columns=["side", "price", "qty", "orders"])
    if not df.empty:
        df["cum"] = df.groupby("side")["qty"].cumsum()
    return df


def depth_chart(df: pd.DataFrame, title: str = "Cumulative depth", height: int = 330) -> go.Figure:
    fig = go.Figure()
    for side, color in (("bid", GREEN), ("ask", RED)):
        s = df[df.side == side].sort_values("price", ascending=(side == "ask"))
        fig.add_trace(go.Scatter(x=s.price, y=s.cum, mode="lines", line_shape="hv", fill="tozeroy",
                                 line=dict(color=color), name=f"{side}s"))
        fig.add_trace(go.Bar(x=s.price, y=s.qty, marker_color=color, opacity=0.45, name=f"{side} level qty",
                             showlegend=False, width=TICK * 0.8))
    fig.update_layout(title=title, height=height, margin=dict(l=10, r=10, t=40, b=10), bargap=0,
                      xaxis_title="price", yaxis_title="shares", legend=dict(orientation="h", y=1.12))
    return fig


def ladder(book: L.OrderBook, levels: int = 10, my_trader: int | None = None) -> pd.DataFrame:
    """Classic DOM ladder: asks on top (descending), bids below."""
    dp = book.depth(levels)
    mine = {}
    if my_trader is not None:
        for o in book.open_orders(my_trader):
            mine[(o["side"], o["price"])] = mine.get((o["side"], o["price"]), 0) + o["qty"]
    rows = []
    for p, q, c in sorted(dp["asks"], reverse=True):
        rows.append({"bid orders": None, "bid qty": None, "price": px(p), "ask qty": q, "ask orders": c,
                     "mine": mine.get(("sell", p), 0) or None})
    for p, q, c in dp["bids"]:
        rows.append({"bid orders": c, "bid qty": q, "price": px(p), "ask qty": None, "ask orders": None,
                     "mine": mine.get(("buy", p), 0) or None})
    return pd.DataFrame(rows)


def estimate_fill(book: L.OrderBook, side: str, qty: int, limit_t: int | None):
    """Pre-trade estimate: walk the opposite side of the book."""
    dp = book.depth(500)
    levels = dp["asks"] if side == "buy" else dp["bids"]
    left, cost, worst = qty, 0, None
    for p, q, _ in levels:
        if limit_t is not None and ((side == "buy" and p > limit_t) or (side == "sell" and p < limit_t)):
            break
        take = min(q, left)
        cost += take * p
        left -= take
        worst = p
        if left == 0:
            break
    filled = qty - left
    return filled, (cost / filled if filled else None), worst


def positions(desk: Desk) -> pd.DataFrame:
    if not desk.fills:
        return pd.DataFrame(columns=["trader", "position", "avg cost", "realized", "unrealized", "total P&L", "maker %"])
    bb, ba = desk.book.best_bid, desk.book.best_ask
    mark = ((bb + ba) / 2) if bb and ba else (desk.book.last_price or 0)
    out = []
    f = pd.DataFrame(desk.fills)
    for t, g in f.groupby("trader"):
        pos, avg, realized = 0, 0.0, 0.0
        for q, p in zip(g.qty, g.price):
            if pos == 0 or (pos > 0) == (q > 0):  # opening / adding
                avg = (avg * abs(pos) + p * abs(q)) / (abs(pos) + abs(q))
                pos += q
            else:  # reducing / flipping
                close = min(abs(q), abs(pos))
                realized += close * (p - avg) * (1 if pos > 0 else -1)
                pos += q
                if pos != 0 and (pos > 0) == (q > 0):
                    avg = p
                if pos == 0:
                    avg = 0.0
        unreal = pos * (mark - avg) if pos else 0.0
        out.append({"trader": tname(int(t)), "position": pos, "avg cost": px(avg) if pos else None,
                    "realized": realized * TICK, "unrealized": unreal * TICK, "total P&L": (realized + unreal) * TICK,
                    "maker %": 100 * (g.role == "maker").mean()})
    return pd.DataFrame(out).sort_values("total P&L", ascending=False)
