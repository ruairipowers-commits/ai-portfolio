import time

import numpy as np
import pandas as pd
import plotly.express as px_
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from lob_matching_engine import _engine as L
from lob_matching_engine.lab.common import BAND, GREEN, RED, TICK, Desk

st.title("🌊 Market simulator")
st.caption("Agent-style order flow (adds, cancels, modifies, marketable orders, stops) run natively in Rust. "
           "Tune the flow, inject a liquidity shock and study the microstructure that emerges.")

with st.sidebar.form("simparams"):
    st.subheader("Order flow")
    steps = st.select_slider("Events", [5_000, 10_000, 20_000, 50_000, 100_000, 250_000], value=50_000)
    snap = st.select_slider("Snapshot every", [10, 25, 50, 100, 250, 500], value=100)
    st.markdown("**Mix (relative weights)**")
    c1, c2 = st.columns(2)
    mix = dict(limit=c1.slider("Limit", 0.0, 1.0, 0.45), cancel=c2.slider("Cancel", 0.0, 1.0, 0.32),
               market=c1.slider("Market", 0.0, 0.5, 0.05), ioc=c2.slider("IOC", 0.0, 0.5, 0.05),
               fok=c1.slider("FOK", 0.0, 0.3, 0.02), post_only=c2.slider("Post-only", 0.0, 0.5, 0.05),
               stop=c1.slider("Stop", 0.0, 0.2, 0.01), modify=c2.slider("Modify", 0.0, 0.5, 0.05))
    mean_qty = st.slider("Mean order size", 1, 200, 20)
    depth_ticks = st.slider("Passive placement (mean ticks from mid)", 1.0, 40.0, 8.0)
    aggr = st.slider("Marketable share of limit/IOC/FOK", 0.0, 0.6, 0.10)
    buy_prob = st.slider("Buy probability (flow imbalance)", 0.3, 0.7, 0.5)
    seed = st.number_input("Seed", 0, 1_000_000, 42)
    st.subheader("Liquidity shock")
    use_shock = st.checkbox("Inject a sweep", value=True)
    shock_at = st.slider("At (% of run)", 5, 95, 50)
    shock_side = st.radio("Side", ["sell", "buy"], horizontal=True)
    shock_qty = st.number_input("Size (shares)", 100, 200_000, 3_000, step=500)
    go_btn = st.form_submit_button("Run simulation", type="primary", width="stretch")

if go_btn or "sim" not in st.session_state:
    params = dict(mix=mix, mean_qty=float(mean_qty), depth_ticks=depth_ticks, aggressive_frac=aggr,
                  buy_prob=buy_prob, seed=int(seed), mid=10_000)
    shock = (int(steps * shock_at / 100), shock_side, int(shock_qty)) if use_shock else None
    t0 = time.perf_counter()
    res, final_book = L.simulate(steps=steps, snapshot_every=snap, depth_levels=20, prefill=600, band=BAND,
                                 params=params, shock=shock)
    st.session_state.sim = dict(res=res, book=final_book, secs=time.perf_counter() - t0, shock=shock, snap=snap, steps=steps)

S = st.session_state.sim
res, shock = S["res"], S["shock"]
snaps = pd.DataFrame({k: res[k] for k in ["step", "best_bid", "best_ask", "last", "bid_depth", "ask_depth", "resting"]})
for c in ["best_bid", "best_ask", "last"]:
    snaps[c] = snaps[c].astype(float) * TICK
snaps["mid"] = (snaps.best_bid + snaps.best_ask) / 2
snaps["spread_ticks"] = (snaps.best_ask - snaps.best_bid) / TICK
snaps["imbalance"] = (snaps.bid_depth - snaps.ask_depth) / (snaps.bid_depth + snaps.ask_depth).clip(lower=1)
trades = pd.DataFrame(res["trades"], columns=["step", "price", "qty", "aggressor"])
trades["price"] *= TICK
kinds = dict(res["kind_counts"])
n_orders = sum(kinds.values())

# ------------------------------------------------------------------ KPIs
k = st.columns(6)
k[0].metric("Engine time", f"{S['secs'] * 1e3:.0f} ms", f"{S['steps'] / S['secs'] / 1e6:.2f} M events/s incl. snapshots", delta_color="off")
k[1].metric("Trades", f"{len(trades):,}", f"{trades.qty.sum():,} sh", delta_color="off")
k[2].metric("Order-to-trade ratio", f"{n_orders / max(len(trades), 1):.1f}")
k[3].metric("Median spread", f"{snaps.spread_ticks.median():.0f} ticks")
rets = np.diff(np.log(snaps.mid.dropna().values))
k[4].metric("Mid vol / snapshot", f"{rets.std() * 1e4:.1f} bps" if len(rets) > 2 else "—")
k[5].metric("Resting at end", f"{res['resting'][-1]:,}")

tab1, tab2, tab3, tab4 = st.tabs(["Price & liquidity", "Book replay", "Microstructure", "Flow breakdown"])

with tab1:
    cells = pd.DataFrame(res["depth_cells"], columns=["snap", "price", "qty"])
    cells["step"] = snaps.step.values[cells.snap]
    cells["price"] *= TICK
    piv = cells.pivot_table(index="price", columns="step", values="qty", aggfunc="sum")
    zmax = np.nanpercentile(np.abs(piv.values), 98) if piv.size else 1
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.04,
                        subplot_titles=("Liquidity heatmap (green = bids, red = asks) with best quotes and trades", "Spread (ticks)"))
    fig.add_trace(go.Heatmap(x=piv.columns, y=piv.index, z=piv.values, zmid=0, zmin=-zmax, zmax=zmax,
                             colorscale=[[0, RED], [0.5, "#f7f7f7"], [1, GREEN]], showscale=False,
                             hovertemplate="step %{x}<br>price %{y:.2f}<br>qty %{z}<extra></extra>"), 1, 1)
    fig.add_trace(go.Scatter(x=snaps.step, y=snaps.best_bid, line=dict(color=GREEN, width=1.5), name="best bid"), 1, 1)
    fig.add_trace(go.Scatter(x=snaps.step, y=snaps.best_ask, line=dict(color=RED, width=1.5), name="best ask"), 1, 1)
    tr = trades.sample(min(len(trades), 4000), random_state=1) if len(trades) else trades
    for side, col in (("buy", "#2166ac"), ("sell", "#b2182b")):
        t = tr[tr.aggressor == side]
        fig.add_trace(go.Scatter(x=t.step, y=t.price, mode="markers", name=f"{side}-initiated trade",
                                 marker=dict(size=np.clip(np.sqrt(t.qty), 2, 14), color=col, opacity=0.5, line_width=0)), 1, 1)
    fig.add_trace(go.Scatter(x=snaps.step, y=snaps.spread_ticks, line=dict(color="#555"), name="spread", showlegend=False), 2, 1)
    if shock:
        for r in (1, 2):
            fig.add_vline(x=shock[0], line_dash="dot", line_color="black", row=r, col=1)
    fig.update_layout(height=640, margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.08))
    st.plotly_chart(fig, width="stretch")

    if shock:
        st.subheader("Shock recovery")
        pre = snaps[snaps.step < shock[0]].tail(20)
        post = snaps[snaps.step >= shock[0]]
        base_spread, base_depth = pre.spread_ticks.median(), (pre.bid_depth + pre.ask_depth).median()
        rec = post[(post.spread_ticks <= base_spread) & ((post.bid_depth + post.ask_depth) >= 0.9 * base_depth)]
        rec_step = int(rec.step.iloc[0] - shock[0]) if not rec.empty else None
        shock_trades = trades[trades.step == shock[0]]
        c = st.columns(4)
        if len(shock_trades):
            vwap = (shock_trades.price * shock_trades.qty).sum() / shock_trades.qty.sum()
            pre_mid = pre.mid.iloc[-1]
            c[0].metric("Sweep VWAP vs prior mid", f"{(vwap - pre_mid) / pre_mid * 1e4:+.1f} bps")
            c[1].metric("Levels consumed", f"{shock_trades.price.nunique()}")
        c[2].metric("Pre-shock spread / depth", f"{base_spread:.0f} t / {base_depth:,.0f}")
        c[3].metric("Events to recover", f"{rec_step:,}" if rec_step is not None else "not within run",
                    help="Events until spread ≤ pre-shock median and top-20 depth ≥ 90% of pre-shock.")

with tab2:
    st.caption("Scrub through snapshots to watch the book reshape itself.")
    i = st.slider("Snapshot", 0, len(snaps) - 1, len(snaps) // 2 if not shock else int(np.searchsorted(snaps.step, shock[0])))
    row = snaps.iloc[i]
    cs = cells[cells.snap == i].copy()
    cs["side"] = np.where(cs.qty > 0, "bid", "ask")
    cs["qty"] = cs.qty.abs()
    c1, c2 = st.columns([2, 1])
    f2 = px_.bar(cs, x="price", y="qty", color="side", color_discrete_map={"bid": GREEN, "ask": RED},
                 title=f"Book at event {int(row.step):,}: bid {row.best_bid:.2f} / ask {row.best_ask:.2f}")
    f2.update_layout(height=380, bargap=0.05, margin=dict(l=10, r=10, t=40, b=10))
    c1.plotly_chart(f2, width="stretch")
    w = trades[(trades.step <= row.step) & (trades.step > row.step - S["snap"] * 5)]
    c2.markdown(f"**Last {S['snap'] * 5:,} events**")
    c2.metric("Trades", len(w))
    c2.metric("Buy-initiated volume share", f"{(w.qty * (w.aggressor == 'buy')).sum() / max(w.qty.sum(), 1):.0%}")
    c2.metric("Top-20 imbalance", f"{row.imbalance:+.2f}")

with tab3:
    st.markdown("**Order-flow imbalance → price impact.** Signed trade volume per snapshot interval vs the mid move over the "
                "same interval. The slope is an empirical *Kyle's lambda*.")
    tb = trades.copy()
    tb["signed"] = np.where(tb.aggressor == "buy", tb.qty, -tb.qty)
    tb["bucket"] = np.searchsorted(snaps.step.values, tb.step.values)
    ofi = tb.groupby("bucket").signed.sum().reindex(range(len(snaps)), fill_value=0)
    dmid = snaps.mid.diff().shift(-1) / TICK
    d = pd.DataFrame({"ofi": ofi.values, "dmid": dmid.values}).dropna()
    if shock is not None:
        d = d[np.abs(d.ofi) < d.ofi.abs().quantile(0.995)]
    if len(d) > 5:
        slope, icpt = np.polyfit(d.ofi, d.dmid, 1)
        r2 = np.corrcoef(d.ofi, d.dmid)[0, 1] ** 2
        c1, c2 = st.columns([2, 1])
        f3 = px_.scatter(d, x="ofi", y="dmid", opacity=0.4, labels={"ofi": "signed volume (shares)", "dmid": "mid change (ticks)"})
        xs = np.linspace(d.ofi.min(), d.ofi.max(), 50)
        f3.add_trace(go.Scatter(x=xs, y=slope * xs + icpt, line=dict(color="black"), name="OLS"))
        f3.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10))
        c1.plotly_chart(f3, width="stretch")
        c2.metric("λ (ticks per 1,000 sh)", f"{slope * 1000:.2f}")
        c2.metric("R²", f"{r2:.2f}")
        c2.caption("Try lowering the passive placement distance or raising order size, then rerun: a thicker book "
                   "near the touch lowers λ.")
    c1, c2 = st.columns(2)
    f4 = px_.histogram(trades, x="qty", nbins=60, log_y=True, title="Trade size distribution")
    f4.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
    c1.plotly_chart(f4, width="stretch")
    f5 = px_.histogram(snaps, x="spread_ticks", nbins=30, title="Spread distribution (ticks)")
    f5.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
    c2.plotly_chart(f5, width="stretch")

with tab4:
    c1, c2 = st.columns(2)
    kd = pd.DataFrame(kinds.items(), columns=["command", "count"])
    c1.plotly_chart(px_.pie(kd, names="command", values="count", hole=0.45, title="Commands sent"), width="stretch")
    cr = pd.DataFrame(res["cancels_by_reason"], columns=["reason", "count"])
    cr.loc[len(cr)] = ["rejected (incl. cancels of already-filled orders)", res["rejects"]]
    c2.plotly_chart(px_.bar(cr, x="count", y="reason", orientation="h", title="Why orders left the book (other than fills)"),
                    width="stretch")
    st.plotly_chart(px_.area(snaps, x="step", y=["bid_depth", "ask_depth"], title="Top-20 level depth over time",
                             color_discrete_sequence=[GREEN, RED]), width="stretch")

st.divider()
if st.button("Load this final book into the Trading desk"):
    st.session_state.desk = Desk(S["book"])
    st.success("Loaded. Open the Trading desk page to trade against it.")
