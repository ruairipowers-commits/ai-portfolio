"""Surveillance detectors (FR-4). Rules in code decide what is an alert; the model only explains it.

Each alert carries the engine event ids that triggered it (for citation checks, OBS-02) and a facts dict of
numbers computed here. Thresholds live in config/settings.yaml `detectors`.
"""
from __future__ import annotations

import pandas as pd


def _alert(pattern, trader, events, facts, severity_map):
    ids = sorted(int(x) for x in events)
    return {"pattern": pattern, "severity": severity_map.get(pattern, "medium"), "trader": trader,
            "event_ids": ids, "facts": facts}


def detect_all(orders: pd.DataFrame, events: pd.DataFrame, cfg: dict) -> list[dict]:
    sev = cfg.get("severity", {})
    alerts = (layering(orders, events, cfg["layering"], sev) + wash(orders, events, cfg["wash"], sev)
              + stuffing(orders, events, cfg["stuffing"], sev) + ignition(orders, events, cfg["ignition"], sev))
    for i, a in enumerate(sorted(alerts, key=lambda a: a["event_ids"][0]), start=1):
        a["alert_id"] = f"A{i:03d}"
    return sorted(alerts, key=lambda a: a["alert_id"])


def _fills(events: pd.DataFrame, trader: str) -> pd.DataFrame:
    """Trades where `trader` was taker or maker, with that trader's side."""
    tr = events[events.event == "trade"]
    as_taker = tr[tr.trader == trader].assign(my_side=lambda d: d.side)
    as_maker = tr[tr.maker_trader == trader].assign(my_side=lambda d: d.side.map({"buy": "sell", "sell": "buy"}))
    return pd.concat([as_taker, as_maker]).sort_values("event_id")


def layering(orders, events, c, sev) -> list[dict]:
    """Several large passive orders on one side, a fill on the other side, then most of the layer cancelled."""
    out = []
    if orders.empty:
        return out
    med = float(orders[orders.otype.isin(["limit", "post_only"])].qty.median() or 1)
    acc = events[events.event == "accepted"].set_index("order_id")
    canc = events[events.event == "cancelled"].set_index("order_id")
    big = orders[(orders.otype == "limit") & (orders.qty >= c["min_qty_multiple"] * med)]
    for trader, g in big.groupby("trader"):
        g = g.sort_values("ts_ms")
        used: set = set()
        for i, first in g.iterrows():
            if first.order_id in used:
                continue
            layer = g[(g.side == first.side) & (g.ts_ms >= first.ts_ms) & (g.ts_ms <= first.ts_ms + c["window_ms"])]
            if len(layer) < c["min_orders"]:
                continue
            fills = _fills(events, trader)
            opp = fills[(fills.my_side != first.side) & (fills.ts_ms >= first.ts_ms)
                        & (fills.ts_ms <= first.ts_ms + c["window_ms"])]
            if opp.empty:
                continue
            fill_ts = int(opp.ts_ms.iloc[0])
            lc = canc.loc[canc.index.intersection(layer.order_id)]
            lc = lc[(lc.ts_ms >= fill_ts) & (lc.ts_ms <= fill_ts + c["cancel_within_ms"])]
            share = float(lc.qty.sum()) / float(layer.qty.sum())
            if share < c["min_cancel_share"]:
                continue
            used |= set(layer.order_id)
            ev = list(acc.loc[acc.index.intersection(layer.order_id), "event_id"]) + list(opp.event_id) + list(lc.event_id)
            out.append(_alert("layering", trader, ev, {
                "layer_side": first.side, "layer_orders": int(len(layer)), "layer_qty": int(layer.qty.sum()),
                "median_order_qty": med, "layer_qty_vs_median": round(float(layer.qty.mean()) / med, 1),
                "opposite_fill_qty": int(opp.qty.sum()), "opposite_fill_price": round(int(opp.price.iloc[0]) / 100, 2),
                "cancelled_share_of_layer": round(share, 3),
                "seconds_layer_to_fill": round((fill_ts - int(first.ts_ms)) / 1000, 2),
                "seconds_fill_to_cancel": round((int(lc.ts_ms.max()) - fill_ts) / 1000, 2)}, sev))
    return out


def wash(orders, events, c, sev) -> list[dict]:
    """Self-trade attempts that STP blocked: the trader rests an order, then quickly crosses it (age <= 1s)."""
    out = []
    stp = events[events.reason == "self-trade prevention"]
    if stp.empty:
        return out
    born = orders.set_index("order_id").ts_ms
    stp = stp.assign(age_ms=stp.order_id.map(born))
    quick = stp[(stp.ts_ms - stp.age_ms) <= 1000]
    for trader, g in quick.groupby("trader"):
        if len(g) < c["min_stp_events"]:
            continue
        out.append(_alert("wash", trader, list(g.event_id), {
            "stp_blocked_attempts": int(len(g)), "blocked_qty": int(g.qty.sum()),
            "median_order_age_ms": float((g.ts_ms - g.age_ms).median()),
            "trades_printed_between_same_trader": 0}, sev))
    return out


def stuffing(orders, events, c, sev) -> list[dict]:
    """Excessive add/cancel with almost no fills and very short order lifetimes."""
    out = []
    canc = events[(events.event == "cancelled") & (events.reason == "user cancel")]
    life = canc.set_index("order_id").ts_ms
    for trader, g in orders.groupby("trader"):
        if len(g) < c["min_orders"]:
            continue
        cancelled = g[g.order_id.isin(life.index)]
        ratio = len(cancelled) / len(g)
        fills = _fills(events, trader)
        fill_ratio = len(fills) / len(g)
        lifetimes = life.loc[cancelled.order_id].values - cancelled.ts_ms.values
        med_life = float(pd.Series(lifetimes).median()) if len(lifetimes) else 1e9
        if ratio >= c["min_cancel_ratio"] and fill_ratio <= c["max_fill_ratio"] and med_life <= c["max_lifetime_ms"]:
            ids = events[events.order_id.isin(cancelled.order_id.head(20))].event_id
            out.append(_alert("stuffing", trader, list(ids), {
                "orders": int(len(g)), "cancel_ratio": round(ratio, 3), "fill_ratio": round(fill_ratio, 4),
                "median_lifetime_ms": med_life}, sev))
    return out


def ignition(orders, events, c, sev) -> list[dict]:
    """A burst of same-side aggressive orders that moves the price, then a fill on the other side."""
    out = []
    aggr = orders[orders.otype.isin(["market", "ioc"])]
    tr = events[events.event == "trade"]
    for trader, g in aggr.groupby("trader"):
        g = g.sort_values("ts_ms")
        for side in ("buy", "sell"):
            s = g[g.side == side]
            for i in range(len(s) - c["min_aggressive"] + 1):
                w = s.iloc[i:i + c["min_aggressive"]]
                if int(w.ts_ms.iloc[-1] - w.ts_ms.iloc[0]) > c["window_ms"]:
                    continue
                prints = tr[tr.order_id.isin(w.order_id)]
                if prints.empty:
                    continue
                move = (int(prints.price.max() - prints.price.iloc[0]) if side == "buy"
                        else int(prints.price.iloc[0] - prints.price.min()))
                if move < c["min_move_ticks"]:
                    continue
                end = int(w.ts_ms.iloc[-1])
                fills = _fills(events, trader)
                rev = fills[(fills.my_side != side) & (fills.ts_ms > end) & (fills.ts_ms <= end + c["reverse_within_ms"])]
                if rev.empty:
                    continue
                out.append(_alert("ignition", trader, list(prints.event_id) + list(rev.event_id), {
                    "burst_side": side, "burst_orders": int(len(w)), "burst_seconds": round((end - int(w.ts_ms.iloc[0])) / 1000, 2),
                    "price_move_ticks": move, "reverse_fill_qty": int(rev.qty.sum()),
                    "reverse_fill_price": round(int(rev.price.iloc[0]) / 100, 2),
                    "seconds_to_reverse": round((int(rev.ts_ms.iloc[0]) - end) / 1000, 2)}, sev))
                break
            else:
                continue
            break
    return out
