"""Order-flow sessions: a seeded synthetic generator, the data gate (DATA-02) and replay through the Rust engine.

A session is a table of commands (one row per new / cancel / modify), the same shape a venue's order-entry log
would have. Replay is deterministic: the engine assigns order ids in submission order, so the same commands always
produce the same event log.
"""
from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import _engine as L

COLUMNS = ["seq", "ts_ms", "trader", "action", "side", "otype", "price", "qty", "trigger", "ref", "memo"]
ACTIONS = {"new", "cancel", "modify"}
OTYPES = {"limit", "market", "ioc", "fok", "post_only", "stop_market", "stop_limit"}
PRICED = {"limit", "ioc", "fok", "post_only", "stop_limit"}
BEHAVIOURS = ("layering", "wash", "stuffing", "ignition")
SCRIPTED_TRADERS = {"layering": "L07", "wash": "W03", "stuffing": "Q11", "ignition": "M05"}
BENIGN_MEMOS = ["", "", "", "", "VWAP slice", "client basket rebalance", "hedge for index futures", "inventory unwind"]
DEFAULT_LAYER_MEMO = "client rebalancing, working the offer"


# ---------------------------------------------------------------------------------------------- generator
@dataclass
class _Gen:
    rng: random.Random
    band: tuple[int, int]
    book: "L.OrderBook"
    rows: list = field(default_factory=list)
    live: dict = field(default_factory=dict)   # trader -> list of (ref, side, price, qty)
    t: float = 0.0
    nref: int = 0

    def mid(self) -> float:
        b, a = self.book.best_bid, self.book.best_ask
        if b and a:
            return (b + a) / 2
        return float(self.book.last_price or 10_000)

    def emit(self, trader, action, side="", otype="", price=0, qty=0, trigger=None, ref="", memo=""):
        if action == "new":
            self.nref += 1
            ref = f"{trader}-{self.nref}"
        row = dict(seq=len(self.rows) + 1, ts_ms=int(self.t), trader=trader, action=action, side=side, otype=otype,
                   price=int(price), qty=int(qty), trigger=trigger, ref=ref, memo=memo)
        self.rows.append(row)
        apply_row(self.book, row, self._ids, self._tno.setdefault(trader, len(self._tno) + 1))
        if action == "new" and otype in ("limit", "post_only"):
            self.live.setdefault(trader, []).append((ref, side, int(price), int(qty)))
        return ref

    _ids: dict = field(default_factory=dict)
    _tno: dict = field(default_factory=dict)

    def tick(self, mean_ms=25.0):
        self.t += self.rng.expovariate(1 / mean_ms)

    # -- noise
    def noise(self):
        r = self.rng
        trader = f"N{r.randint(1, 20):02d}"
        u = r.random()
        mid = self.mid()
        side = r.choice(["buy", "sell"])
        if u < 0.58:
            off = 1 + int(r.expovariate(1 / 4))
            px = math.floor(mid - off) if side == "buy" else math.ceil(mid + off)
            self.emit(trader, "new", side, "limit", px, max(1, int(r.expovariate(1 / 30))), memo=r.choice(BENIGN_MEMOS))
        elif u < 0.90:
            mine = self.live.get(trader) or []
            if mine:
                ref, *_ = mine.pop(r.randrange(len(mine)))
                self.emit(trader, "cancel", ref=ref)
        elif u < 0.95:
            self.emit(trader, "new", side, "market", 0, max(1, int(r.expovariate(1 / 15))))
        else:
            px = math.ceil(mid) if side == "buy" else math.floor(mid)
            self.emit(trader, "new", side, "ioc", px, max(1, int(r.expovariate(1 / 20))))

    def level_qty(self, side: str, price: int) -> int:
        lv = self.book.depth(50)["asks" if side == "sell" else "bids"]
        return sum(q for p, q, _ in lv if p == price)

    # -- scripted behaviours (fictional traders)
    def layering(self, memo: str):
        tr = "L07"
        ask = self.book.best_ask or int(self.mid()) + 1
        refs = []
        for k in range(5):
            self.t += 120
            refs.append(self.emit(tr, "new", "sell", "limit", ask + 2 + k, 400, memo=memo))
        self.t += 1500
        self.emit(tr, "new", "buy", "ioc", self.book.best_ask or ask, 40, memo=memo)
        for ref in refs:
            self.t += 150
            self.emit(tr, "cancel", ref=ref, memo=memo)
        self.live.pop(tr, None)

    def wash(self):
        tr = "W03"
        for _ in range(3):
            b, a = self.book.best_bid, self.book.best_ask
            px = (b + 1) if (b and a and a - b >= 2) else (a or int(self.mid()) + 1)
            self.t += 200
            self.emit(tr, "new", "sell", "limit", px, 50)
            self.t += 300
            self.emit(tr, "new", "buy", "ioc", px, self.level_qty("sell", px) + 1)
            self.t += 4000

    def stuffing(self, n=200):
        tr = "Q11"
        for _ in range(n):
            self.tick(30)
            b = self.book.best_bid or int(self.mid()) - 1
            ref = self.emit(tr, "new", "buy", "post_only", b - 3, 10)
            self.t += self.rng.uniform(20, 80)
            self.emit(tr, "cancel", ref=ref)
            for _ in range(2):
                self.tick()
                self.noise()

    def ignition(self):
        tr = "M05"
        start_last = self.book.last_price
        for _ in range(6):
            self.t += 350
            a = self.book.best_ask
            q = self.level_qty("sell", a) if a else 50
            self.emit(tr, "new", "buy", "market", 0, int(q * 1.5) + 10)
        self.t += 2500
        b = self.book.best_bid or int(self.mid())
        self.emit(tr, "new", "sell", "ioc", b, 400)
        return start_last


def generate(seed: int = 7, noise_commands: int = 12_000, behaviours=BEHAVIOURS,
             layer_memo: str = DEFAULT_LAYER_MEMO, band=(5_000, 15_000)) -> pd.DataFrame:
    """Synthetic session: noise traders N01–N20 plus the scripted behaviours requested."""
    rng = random.Random(seed)
    g = _Gen(rng, tuple(band), L.OrderBook(band[0], band[1], stp=True))
    # opening book: both sides around $100.00
    for i in range(400):
        side = "buy" if i % 2 == 0 else "sell"
        off = 1 + int(rng.expovariate(1 / 5))
        g.emit(f"N{rng.randint(1, 20):02d}", "new", side, "limit", 10_000 - off if side == "buy" else 10_000 + off,
               max(1, int(rng.expovariate(1 / 40))))
    plan = {b: int(noise_commands * f) for b, f in zip(BEHAVIOURS, (0.25, 0.45, 0.6, 0.8)) if b in behaviours}
    for i in range(noise_commands):
        g.tick()
        g.noise()
        for b, at in plan.items():
            if i == at:
                g.t += 1000
                if b == "layering":
                    g.layering(layer_memo)
                elif b == "wash":
                    g.wash()
                elif b == "stuffing":
                    g.stuffing()
                else:
                    g.ignition()
    df = pd.DataFrame(g.rows, columns=COLUMNS)
    return df


# ---------------------------------------------------------------------------------------------- data gate
@dataclass
class GateResult:
    ok: bool
    errors: list[str]
    rows: int

    @property
    def message(self) -> str:
        return (f"Data gate passed: {self.rows:,} commands" if self.ok
                else f"Data gate failed ({len(self.errors)} problem(s)): " + "; ".join(self.errors[:5]))


def validate(df: pd.DataFrame, band=(5_000, 15_000), max_rows=500_000, require_monotonic=True) -> GateResult:
    """DATA-02: a session must pass every check before replay and before any model call."""
    errs: list[str] = []
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        return GateResult(False, [f"missing columns: {missing}"], len(df))
    if len(df) == 0:
        errs.append("no commands")
    if len(df) > max_rows:
        errs.append(f"{len(df):,} rows exceeds the {max_rows:,}-row limit")
    bad_action = ~df.action.isin(ACTIONS)
    if bad_action.any():
        errs.append(f"{int(bad_action.sum())} rows with unknown action")
    new = df[df.action == "new"]
    if (~new.otype.isin(OTYPES)).any():
        errs.append(f"{int((~new.otype.isin(OTYPES)).sum())} new orders with unknown type")
    if (~new.side.isin(["buy", "sell"])).any():
        errs.append(f"{int((~new.side.isin(['buy', 'sell'])).sum())} new orders without buy/sell")
    q = pd.to_numeric(new.qty, errors="coerce")
    if (q.isna() | (q <= 0)).any():
        errs.append(f"{int((q.isna() | (q <= 0)).sum())} new orders with non-positive quantity")
    priced = new[new.otype.isin(PRICED)]
    p = pd.to_numeric(priced.price, errors="coerce")
    out = p.isna() | (p < band[0]) | (p > band[1])
    if out.any():
        errs.append(f"{int(out.sum())} priced orders outside the {band[0]}–{band[1]} tick band")
    ts = pd.to_numeric(df.ts_ms, errors="coerce")
    if ts.isna().any():
        errs.append("timestamps missing or non-numeric")
    elif require_monotonic and (ts.diff().dropna() < 0).any():
        errs.append(f"time goes backwards on {int((ts.diff() < 0).sum())} rows")
    known: set = set(new.ref)
    refs = df[df.action.isin(["cancel", "modify"])].ref
    orphan = ~refs.isin(known)
    if orphan.any():
        errs.append(f"{int(orphan.sum())} cancels/modifies reference unknown orders")
    if df.ref[df.action == "new"].duplicated().any():
        errs.append("duplicate order references")
    return GateResult(not errs, errs, len(df))


def read_csv(buf: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(buf), keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    for c in COLUMNS:
        if c not in df.columns and c in ("trigger", "memo", "seq"):
            df[c] = "" if c != "seq" else range(1, len(df) + 1)
    return df


# ---------------------------------------------------------------------------------------------- replay
def apply_row(book, row: dict, ids: dict, trader_no: int = 0) -> list[dict]:
    """Send one command to the engine. `ids` maps client refs to engine order ids; trader_no drives STP."""
    a = row["action"]
    if a == "new":
        trig = row.get("trigger")
        trig = None if trig in (None, "", "nan") or (isinstance(trig, float) and math.isnan(trig)) else int(trig)
        oid, ev = book.submit(row["side"], row["otype"], int(row["price"] or 0), int(row["qty"]), trader_no, trig)
        ids[row["ref"]] = oid
        return ev
    oid = ids.get(row["ref"])
    if oid is None:
        return []
    if a == "cancel":
        return book.cancel(oid)[1]
    return book.modify(oid, int(row["price"]), int(row["qty"]))[1]


@dataclass
class Replay:
    events: pd.DataFrame
    snapshots: pd.DataFrame
    orders: pd.DataFrame          # one row per order: ref, engine id, trader, side, type, price, qty, memo, ts
    stats: dict
    seconds: float


def replay(df: pd.DataFrame, band=(5_000, 15_000), stp=True, snapshot_every=100) -> Replay:
    """Replay a validated session. Trader ids are carried in Python; the engine sees one shared trader id so that
    STP is applied per *trader*: each trader gets their own engine trader number."""
    import time

    book = L.OrderBook(band[0], band[1], stp=stp)
    trader_no = {t: i + 1 for i, t in enumerate(sorted(df.trader.astype(str).unique()))}
    ids: dict[str, int] = {}
    owner: dict[int, str] = {}
    orders, events, snaps = [], [], []
    eid = 0
    t0 = time.perf_counter()
    for row in df.to_dict("records"):
        trader = str(row["trader"])
        a = row["action"]
        if a == "new":
            trig = row.get("trigger")
            trig = None if trig in (None, "") or (isinstance(trig, float) and math.isnan(trig)) else int(trig)
            oid, ev = book.submit(row["side"], row["otype"], int(row["price"] or 0), int(row["qty"]),
                                  trader_no[trader], trig)
            ids[row["ref"]] = oid
            owner[oid] = trader
            orders.append({"ref": row["ref"], "order_id": oid, "trader": trader, "side": row["side"],
                           "otype": row["otype"], "price": int(row["price"] or 0), "qty": int(row["qty"]),
                           "ts_ms": int(row["ts_ms"]), "memo": str(row.get("memo") or "")})
        else:
            oid = ids.get(row["ref"])
            ev = [] if oid is None else (book.cancel(oid)[1] if a == "cancel"
                                         else book.modify(oid, int(row["price"]), int(row["qty"]))[1])
        for e in ev:
            eid += 1
            d = {"event_id": eid, "cmd_seq": int(row["seq"]), "ts_ms": int(row["ts_ms"]), "event": e["event"],
                 "order_id": e.get("id", e.get("taker")), "trader": owner.get(e.get("id", e.get("taker")), trader),
                 "side": e.get("side", e.get("aggressor", "")), "price": e.get("price", 0), "qty": e.get("qty", 0),
                 "reason": e.get("reason", ""), "maker_id": e.get("maker"), "maker_trader": None}
            if e["event"] == "trade":
                d["trader"] = owner.get(e["taker"], trader)
                d["maker_trader"] = owner.get(e["maker"])
            events.append(d)
        if int(row["seq"]) % snapshot_every == 0:
            snaps.append({"cmd_seq": int(row["seq"]), "ts_ms": int(row["ts_ms"]), "best_bid": book.best_bid,
                          "best_ask": book.best_ask, "last": book.last_price,
                          **_depth(book)})
    secs = time.perf_counter() - t0
    ev = pd.DataFrame(events)
    sn = pd.DataFrame(snaps)
    od = pd.DataFrame(orders)
    return Replay(ev, sn, od, market_quality(ev, sn, od, book), secs)


def _depth(book, n=5) -> dict:
    d = book.depth(n)
    return {"bid_depth5": sum(q for _, q, _ in d["bids"]), "ask_depth5": sum(q for _, q, _ in d["asks"])}


def market_quality(ev: pd.DataFrame, sn: pd.DataFrame, od: pd.DataFrame, book) -> dict:
    """FR-3: market-quality statistics, all computed here (the model never computes numbers)."""
    tr = ev[ev.event == "trade"] if len(ev) else ev
    spread = (sn.best_ask - sn.best_bid).dropna() if len(sn) else pd.Series(dtype=float)
    stats = {
        "commands": int(ev.cmd_seq.max()) if len(ev) else 0,
        "orders": len(od),
        "trades": int(len(tr)),
        "volume": int(tr.qty.sum()) if len(tr) else 0,
        "vwap": round(float((tr.price * tr.qty).sum() / tr.qty.sum()) / 100, 4) if len(tr) else None,
        "median_spread_ticks": float(spread.median()) if len(spread) else None,
        "avg_top5_depth": float(((sn.bid_depth5 + sn.ask_depth5) / 2).mean()) if len(sn) else None,
        "order_to_trade": round(len(od) / max(len(tr), 1), 2),
        "cancels": int((ev.event == "cancelled").sum()) if len(ev) else 0,
        "stp_cancels": int((ev.reason == "self-trade prevention").sum()) if len(ev) else 0,
        "resting_end": book.order_count,
    }
    # Kyle's lambda: signed trade volume per snapshot bucket vs mid change (ticks per 1,000 shares)
    if len(tr) and len(sn) > 10:
        mid = ((sn.best_bid + sn.best_ask) / 2).ffill().values
        b = np.searchsorted(sn.cmd_seq.values, tr.cmd_seq.values)
        signed = np.where(tr.side == "buy", tr.qty, -tr.qty)
        ofi = np.bincount(np.clip(b, 0, len(sn) - 1), weights=signed, minlength=len(sn))[1:]
        dm = np.diff(mid)
        m = np.isfinite(dm)
        if m.sum() > 5 and np.std(ofi[m]) > 0:
            stats["kyle_lambda_ticks_per_1k"] = round(float(np.polyfit(ofi[m], dm[m], 1)[0] * 1000), 3)
    return stats
