import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from event_backtester import demo
from event_backtester.lab.common import BLUE, GREEN, GREY, RED, data_badge, exec_controls, fmt_metrics, get_ticks
from event_backtester import (CUSTOM_TEMPLATE, Backtest, BollingerReversion, CodeStrategy, DonchianBreakout, MACross,
                  VolTargetMomentum, run_kernel)
from event_backtester.metrics import cost_waterfall, perf, round_trips, trade_stats

st.title("🔁 Strategy lab")
data_badge()
ticks = get_ticks()

with st.sidebar:
    st.subheader("Strategy")
    kind = st.selectbox("Strategy", ["MA crossover", "Bollinger mean reversion", "Donchian breakout",
                                     "Vol-target momentum"] + ([] if demo.enabled() else ["Custom Python"]),
                        help="Custom strategy code runs locally only; it is disabled in the hosted demo.")
    long_only = False
    if kind == "MA crossover":
        c1, c2 = st.columns(2)
        fast = c1.number_input("Fast", 1, 500, 10)
        slow = c2.number_input("Slow", 2, 2000, 40)
        long_only = st.checkbox("Long only")
    elif kind == "Bollinger mean reversion":
        w = st.slider("Window", 5, 200, 30)
        ez = st.slider("Entry |z|", 0.5, 4.0, 2.0, 0.1)
        xz = st.slider("Exit |z|", 0.0, 2.0, 0.5, 0.1)
        long_only = st.checkbox("Long only")
    elif kind == "Donchian breakout":
        en = st.slider("Entry channel (bars)", 5, 300, 40)
        exn = st.slider("Exit channel (bars)", 2, 200, 20)
        long_only = st.checkbox("Long only")
    elif kind == "Vol-target momentum":
        lb = st.slider("Lookback (bars)", 2, 300, 48)
        vw = st.slider("Vol window (bars)", 10, 500, 96)
        tv = st.slider("Target vol per bar (bps)", 1.0, 60.0, 15.0)
cfg = exec_controls()

if kind == "Custom Python":
    st.markdown("**Custom strategy.** Your `on_bar` only ever sees completed bars; the engine handles orders, latency and costs.")
    code = st.text_area("on_bar(ctx)", CUSTOM_TEMPLATE, height=330, key="code")


def build():
    if kind == "MA crossover":
        return MACross(int(fast), int(slow), long_only)
    if kind == "Bollinger mean reversion":
        return BollingerReversion(w, ez, xz, long_only)
    if kind == "Donchian breakout":
        return DonchianBreakout(en, exn, long_only)
    if kind == "Vol-target momentum":
        return VolTargetMomentum(lb, vw, tv)
    return CodeStrategy(st.session_state.code)


if st.button("▶ Run backtest", type="primary") or "bt" not in st.session_state:
    try:
        strat = build()
        bar = st.progress(0.0, "Streaming ticks through the event queue…")
        res = Backtest(ticks, strat, cfg).run(progress=lambda x: bar.progress(min(x, 1.0)))
        bar.empty()
        st.session_state.bt = res
        st.session_state.bt_kind = (kind, long_only, getattr(strat, "fast", None), getattr(strat, "slow", None))
    except Exception as e:
        st.error(f"Strategy error: {type(e).__name__}: {e}")
        st.stop()

res = st.session_state.bt
b, f = res.bars, res.fills
if res.errors:
    st.error(f"Lookahead guard tripped {len(res.errors)}× — e.g. {res.errors[0]}")
net, gross = perf(b.equity, res.bars_per_year), perf(b.gross_equity, res.bars_per_year)
ts_ = trade_stats(f, b, res.cfg.init_cash)

k = st.columns(7)
k[0].metric("Net Sharpe", f"{net.get('Sharpe', 0):.2f}", f"{net.get('Sharpe', 0) - gross.get('Sharpe', 0):+.2f} vs frictionless")
k[1].metric("Net return", f"{net.get('Total return', 0):.2%}", f"gross {gross.get('Total return', 0):.2%}", delta_color="off")
k[2].metric("Max drawdown", f"{net.get('Max drawdown', 0):.2%}")
k[3].metric("Fills", f"{ts_.get('Fills', 0):,}")
k[4].metric("Cost / fill", f"{ts_.get('Avg cost per fill (bps)', 0):.1f} bps")
k[5].metric("Impl. shortfall", f"{ts_.get('Avg implementation shortfall (bps)', 0):.1f} bps" if len(f) else "—")
k[6].metric("Engine", f"{res.runtime_s:.2f} s", f"{res.ticks / res.runtime_s / 1e3:,.0f}k ticks/s", delta_color="off")

t1, t2, t3, t4, t5 = st.tabs(["Equity & risk", "Fills on the tape", "Cost attribution", "Trades & blotter", "Engine internals"])

with t1:
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.55, 0.2, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Scatter(x=b.ts, y=b.gross_equity, name="Frictionless (signal at close mid)", line=dict(color=GREY, dash="dot")), 1, 1)
    fig.add_trace(go.Scatter(x=b.ts, y=b.equity, name="Net (event-driven, with costs)", line=dict(color=BLUE)), 1, 1)
    fig.add_trace(go.Scatter(x=b.ts, y=b.position, name="position", line=dict(color="#762a83", shape="hv"), fill="tozeroy"), 2, 1)
    fig.add_trace(go.Scatter(x=b.ts, y=b.drawdown * 100, name="drawdown %", line=dict(color=RED), fill="tozeroy"), 3, 1)
    fig.update_layout(height=620, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.05),
                      xaxis3=dict(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")]))
    fig.update_yaxes(title_text="equity $", row=1); fig.update_yaxes(title_text="shares", row=2); fig.update_yaxes(title_text="DD %", row=3)
    st.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns([1, 1.4])
    both = fmt_metrics(net).merge(fmt_metrics(gross), on="metric", suffixes=(" (net)", " (frictionless)"))
    c1.dataframe(pd.concat([both, fmt_metrics(ts_).rename(columns={"value": "value (net)"})]), hide_index=True, width="stretch")
    daily = b.set_index("ts").equity.resample("D").last().dropna().pct_change().dropna()
    if len(daily) > 3:
        dd = daily.to_frame("ret")
        dd["week"] = dd.index.to_period("W").start_time.date
        dd["dow"] = dd.index.day_name().str[:3]
        piv = dd.pivot_table(index="dow", columns="week", values="ret").reindex(["Mon", "Tue", "Wed", "Thu", "Fri"])
        fh = px.imshow(piv * 100, color_continuous_scale="RdYlGn", color_continuous_midpoint=0, aspect="auto",
                       title="Daily net returns (%) by week", labels=dict(color="%"))
        fh.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
        c2.plotly_chart(fh, width="stretch")

with t2:
    days = sorted(b.ts.dt.date.unique())
    day = st.select_slider("Day", days, value=days[len(days) // 2])
    tk = ticks[ticks.ts.dt.date == day]
    tk = tk.iloc[:: max(1, len(tk) // 4000)]
    fd = f[f.ts.dt.date == day] if len(f) else f
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=tk.ts, y=tk.ask, line=dict(color=RED, width=0.7), name="ask"))
    fig.add_trace(go.Scatter(x=tk.ts, y=tk.bid, line=dict(color=GREEN, width=0.7), name="bid", fill="tonexty", fillcolor="rgba(150,150,150,0.15)"))
    bd = b[b.ts.dt.date == day]
    fig.add_trace(go.Scatter(x=bd.ts, y=bd.close, mode="markers", marker=dict(size=4, color="black"), name="bar close (decision)"))
    if len(fd):
        for side, sym, col in (("buy", "triangle-up", GREEN), ("sell", "triangle-down", RED)):
            s = fd[fd.side == side]
            fig.add_trace(go.Scatter(x=s.ts, y=s.price, mode="markers", name=f"{side} fill",
                                     marker=dict(symbol=sym, size=13, color=col, line=dict(width=1, color="black")),
                                     customdata=np.c_[s.qty, s.shortfall_bps, s.delay_ms, s.otype],
                                     hovertemplate="%{customdata[0]:.0f} sh @ %{y:.4f}<br>shortfall %{customdata[1]:.1f} bps"
                                                   "<br>delay %{customdata[2]:.0f} ms<br>%{customdata[3]}<extra></extra>"))
            for r in s.itertuples():
                fig.add_shape(type="line", x0=r.decision_ts, x1=r.ts, y0=r.arrival_mid, y1=r.price, line=dict(color=col, dash="dot"))
    fig.update_layout(height=480, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.06))
    st.plotly_chart(fig, width="stretch")
    st.caption("Dotted lines join each decision (bar close mid) to its actual fill: the gap is your implementation shortfall.")

with t3:
    wf = cost_waterfall(res)
    meas = ["absolute"] + ["relative"] * (len(wf) - 2) + ["total"]
    fw = go.Figure(go.Waterfall(x=wf.component, y=wf.value, measure=meas, text=[f"${v:,.0f}" for v in wf.value],
                                decreasing=dict(marker_color=RED), increasing=dict(marker_color=GREEN),
                                totals=dict(marker_color=BLUE)))
    fw.update_layout(title="From frictionless to net P&L", height=420, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fw, width="stretch")
    if len(f):
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.histogram(f, x="shortfall_bps", nbins=40, color="side",
                                     color_discrete_map={"buy": GREEN, "sell": RED},
                                     title="Implementation shortfall per fill (bps)"), width="stretch")
        fc = f.assign(notional=f.qty * f.price)
        fc["cost_bps"] = (fc.commission + fc.spread_cost + fc.impact_cost) / fc.notional * 1e4
        c2.plotly_chart(px.scatter(fc, x="qty", y="cost_bps", color="otype", title="Cost vs order size",
                                   labels={"qty": "shares", "cost_bps": "explicit + spread + impact (bps)"}), width="stretch")
    st.caption("Latency/delay = how far the mid moved between the decision and the fill. Spread = half-spread crossed "
               "(negative for passive limit fills: you earned it). Impact follows a square-root law in order size / ADV.")

with t4:
    rt = round_trips(f)
    if len(rt):
        c = st.columns(4)
        c[0].metric("Round trips", len(rt))
        c[1].metric("Hit rate", f"{(rt.pnl > 0).mean():.0%}")
        c[2].metric("Payoff ratio", f"{rt.pnl[rt.pnl > 0].mean() / -rt.pnl[rt.pnl < 0].mean():.2f}" if (rt.pnl < 0).any() and (rt.pnl > 0).any() else "—")
        c[3].metric("Median holding", str(rt.holding.median()).split(".")[0])
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.histogram(rt, x="pnl", color="side", nbins=40, title="Round-trip P&L ($)"), width="stretch")
        rt2 = rt.assign(hours=rt.holding.dt.total_seconds() / 3600)
        c2.plotly_chart(px.scatter(rt2, x="hours", y="pnl", color="side", title="P&L vs holding time"), width="stretch")
    st.markdown("**Fill blotter**")
    if len(f):
        cols = ["decision_ts", "ts", "delay_ms", "side", "qty", "otype", "arrival_mid", "quote", "price", "commission",
                "spread_cost", "impact_cost", "delay_cost", "shortfall_bps"]
        st.dataframe(f[cols], hide_index=True, width="stretch", height=320)
        st.download_button("Download fills CSV", f[cols].to_csv(index=False), "fills.csv")

with t5:
    c1, c2 = st.columns([1, 1.3])
    ev = pd.DataFrame(res.events.items(), columns=["event", "count"])
    c1.plotly_chart(px.bar(ev, x="event", y="count", log_y=True, title="Events processed"), width="stretch")
    c1.caption(f"{sum(res.events.values()):,} events in {res.runtime_s:.2f}s → "
               f"{sum(res.events.values()) / res.runtime_s / 1e3:,.0f}k events/s in pure Python.")
    with c2:
        st.markdown("**Cross-check against the C++ kernel**")
        kk = st.session_state.get("bt_kind", (None,))
        if kk[0] == "MA crossover" and res.cfg.order_type == "market" and res.cfg.fill_mode == "next_tick":
            kr = run_kernel(ticks, kk[2], kk[3], res.cfg, kk[1])
            diff = np.max(np.abs(kr["equity"] - b.equity.values)) if len(kr["equity"]) == len(b) else np.inf
            st.metric("Max |equity difference|", f"${diff:.6f}")
            (st.success if diff < 1e-6 else st.error)(
                f"Python engine and C++ kernel {'agree' if diff < 1e-6 else 'DISAGREE'}: {kr['fills']} vs {len(f)} fills.")
            st.caption("Same event semantics, latency, spread crossing, impact and commission, implemented twice. "
                       "This is what makes the fast C++ sweeps trustworthy.")
        else:
            st.info("Available for MA crossover with market orders. The kernel mirrors that strategy for fast sweeps.")
