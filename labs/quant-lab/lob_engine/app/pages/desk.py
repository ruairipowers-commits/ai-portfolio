import random

import pandas as pd
import streamlit as st

from common import (BAND, TICK, TRADERS, depth_chart, depth_frame, estimate_fill, get_desk, ladder, new_desk,
                    positions, px, ticks, tname)

st.title("🧾 Trading desk")
st.caption("Trade against a live Rust order book. Every click goes through the real matching engine; "
           "noise traders can hit your resting orders, and P&L is marked to mid.")

desk = get_desk()
book = desk.book

with st.sidebar:
    st.subheader("Desk controls")
    me = st.selectbox("Acting as", list(TRADERS)[:-1], format_func=tname, key="me")
    book.stp = st.toggle("Self-trade prevention", value=book.stp,
                         help="If your order would trade against your own resting order, the resting one is cancelled.")
    levels = st.slider("Ladder depth", 5, 30, 12)
    n_noise = st.number_input("Noise orders per burst", 10, 5000, 150, step=50)
    aggr = st.slider("Noise aggressiveness", 0.0, 0.6, 0.15, help="Share of noise orders that are market orders.")
    c1, c2 = st.columns(2)
    if c1.button("▶ Run burst", width="stretch"):
        desk.noise(int(n_noise), aggr, random.Random())
    if c2.button("↺ Reset book", width="stretch"):
        st.session_state.desk = new_desk(random.randint(0, 10_000))
        st.rerun()

# ------------------------------------------------------------------ headline metrics
bb, ba, last = book.best_bid, book.best_ask, book.last_price
stats = book.stats()
dp = book.depth(5)
bq, aq = sum(q for _, q, _ in dp["bids"]), sum(q for _, q, _ in dp["asks"])
m = st.columns(7)
m[0].metric("Best bid", f"{px(bb):.2f}" if bb else "—")
m[1].metric("Best ask", f"{px(ba):.2f}" if ba else "—")
if bb and ba:
    mid = (bb + ba) / 2
    m[2].metric("Spread", f"{ba - bb} ticks", f"{(ba - bb) / mid * 1e4:.1f} bps", delta_color="off")
    m[3].metric("Mid", f"{mid * TICK:.3f}")
else:
    m[2].metric("Spread", "—"); m[3].metric("Mid", "—")
m[4].metric("Last", f"{px(last):.2f}" if last else "—")
m[5].metric("Top-5 imbalance", f"{(bq - aq) / max(bq + aq, 1):+.2f}", help="(bid qty − ask qty) / total, top 5 levels")
m[6].metric("Trades / volume", f"{stats['trades']:,}", f"{stats['volume']:,} sh", delta_color="off")

left, mid_col, right = st.columns([1.05, 1.25, 1.2])

# ------------------------------------------------------------------ order ticket
with left:
    st.subheader("Order ticket")
    side = st.segmented_control("Side", ["buy", "sell"], default="buy", key="side") or "buy"
    otype = st.selectbox("Type", ["limit", "market", "ioc", "fok", "post_only", "stop_market", "stop_limit"],
                         format_func=lambda s: s.replace("_", "-").upper())
    ref = (bb if side == "buy" else ba) or last or 10_000
    needs_px = otype not in ("market", "stop_market")
    price = st.number_input("Limit price", min_value=BAND[0] * TICK, max_value=BAND[1] * TICK,
                            value=float(px(ref)), step=TICK, format="%.2f", disabled=not needs_px)
    qty = st.number_input("Quantity", 1, 1_000_000, 100, step=10)
    trigger = None
    if otype.startswith("stop"):
        dflt = (last or ref) + (5 if side == "buy" else -5)
        trigger = st.number_input("Stop trigger (last trade)", value=float(px(dflt)), step=TICK, format="%.2f")

    # Pre-trade analytics
    lim_t = ticks(price) if needs_px else None
    if not otype.startswith("stop") and otype != "post_only":
        filled, avg, worst = estimate_fill(book, side, int(qty), lim_t)
        if filled:
            ref_mid = (bb + ba) / 2 if bb and ba else avg
            slip = (avg - ref_mid) / ref_mid * 1e4 * (1 if side == "buy" else -1)
            st.info(f"**Immediate fill est.:** {filled:,}/{qty:,} sh @ avg {avg * TICK:.4f} "
                    f"(worst {px(worst):.2f}) · **{slip:+.1f} bps** vs mid"
                    + ("" if filled == qty else f" · {qty - filled:,} would " +
                       ("rest" if otype == "limit" else "be cancelled" if otype != "fok" else "kill the whole order")))
        else:
            st.caption("Passive: nothing would trade immediately." if otype == "limit" else "No marketable liquidity.")
    elif otype == "post_only" and lim_t and ((side == "buy" and ba and lim_t >= ba) or (side == "sell" and bb and lim_t <= bb)):
        st.warning("This post-only order would cross the spread and will be rejected.")

    if st.button(f"Send {side.upper()} {otype.replace('_', '-').upper()}", type="primary", width="stretch"):
        oid, ev = desk.submit(side, otype, lim_t or 0, int(qty), me, ticks(trigger) if trigger else None)
        st.session_state.last_events = (oid, ev)
    if "last_events" in st.session_state:
        oid, ev = st.session_state.last_events
        with st.expander(f"Engine response for order #{oid}", expanded=True):
            st.dataframe(pd.DataFrame(ev), hide_index=True, width="stretch")

# ------------------------------------------------------------------ ladder & depth
with mid_col:
    st.subheader("Depth ladder")
    lad = ladder(book, levels, me)
    st.dataframe(
        lad.style.format({"price": "{:.2f}"}, na_rep="")
        .background_gradient(subset=["bid qty"], cmap="Greens")
        .background_gradient(subset=["ask qty"], cmap="Reds"),
        hide_index=True, width="stretch", height=min(38 + 35 * len(lad), 760),
        column_config={"mine": st.column_config.NumberColumn("your qty", help="Your resting quantity at this level")},
    )

with right:
    st.plotly_chart(depth_chart(depth_frame(book, levels)), width="stretch")
    st.subheader("Queue inspector")
    q_side = st.radio("Side", ["buy", "sell"], horizontal=True, key="qside")
    lv = book.depth(levels)["bids" if q_side == "buy" else "asks"]
    if lv:
        q_px = st.selectbox("Level", [p for p, _, _ in lv], format_func=lambda p: f"{px(p):.2f}")
        qd = pd.DataFrame(book.queue(q_side, q_px))
        qd["ahead"] = qd.qty.cumsum() - qd.qty
        qd["trader"] = qd.trader.map(tname)
        mine = qd[qd.trader == tname(me)]
        if not mine.empty:
            r = mine.iloc[0]
            st.success(f"Your order #{r.id} is **#{mine.index[0] + 1} in queue** with **{r.ahead:,} shares ahead**.")
        st.dataframe(qd[["id", "trader", "qty", "orig_qty", "ahead"]], hide_index=True, width="stretch", height=220)

# ------------------------------------------------------------------ blotters
t1, t2, t3, t4, t5 = st.tabs(["My open orders", "Stop orders", "Trade tape", "P&L by trader", "Event log"])
with t1:
    mine = pd.DataFrame(book.open_orders(me))
    if mine.empty:
        st.caption("No resting orders.")
    else:
        mine["price"] = mine.price * TICK
        mine["cancel"] = False
        mine["new price"] = mine.price
        mine["new qty"] = mine.qty
        ed = st.data_editor(mine[["id", "side", "price", "qty", "orig_qty", "new price", "new qty", "cancel"]],
                            hide_index=True, width="stretch", key="ordered",
                            disabled=["id", "side", "price", "qty", "orig_qty"],
                            column_config={"new price": st.column_config.NumberColumn(format="%.2f", step=TICK)})
        st.caption("Shrinking size at the same price keeps queue priority; any other change is cancel/replace.")
        if st.button("Apply changes"):
            for _, r in ed.iterrows():
                if r["cancel"]:
                    desk.record(book.cancel(int(r["id"]))[1], "ticket")
                elif ticks(r["new price"]) != ticks(r["price"]) or int(r["new qty"]) != int(r["qty"]):
                    desk.record(book.modify(int(r["id"]), ticks(r["new price"]), int(r["new qty"]))[1], "ticket")
            st.rerun()
        if st.button("Cancel all mine"):
            for o in book.open_orders(me):
                desk.record(book.cancel(o["id"])[1], "ticket")
            st.rerun()
with t2:
    s = pd.DataFrame(book.stop_orders())
    if s.empty:
        st.caption("No pending stops.")
    else:
        s["trader"] = s.trader.map(tname)
        s["trigger"] = s.trigger * TICK
        st.dataframe(s, hide_index=True, width="stretch")
with t3:
    tp = pd.DataFrame(desk.tape[::-1][:500])
    st.dataframe(tp, hide_index=True, width="stretch") if not tp.empty else st.caption("No trades yet.")
with t4:
    st.dataframe(positions(desk).style.format({"realized": "${:,.2f}", "unrealized": "${:,.2f}", "total P&L": "${:,.2f}",
                                               "avg cost": "{:.3f}", "maker %": "{:.0f}%"}, na_rep="—"),
                 hide_index=True, width="stretch")
    st.caption("Marked to the current mid. Maker % = share of fills where the trader was providing liquidity.")
with t5:
    lg = pd.DataFrame(desk.log[::-1][:500])
    st.dataframe(lg, hide_index=True, width="stretch") if not lg.empty else st.caption("Empty.")
