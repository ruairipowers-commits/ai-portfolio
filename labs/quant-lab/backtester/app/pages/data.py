import time

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common import BLUE, get_ticks, make_ticks
from qlbt import load_csv, resample
from qlbt.data import resample_pandas

st.title("📦 Market data")
st.caption("Generate realistic synthetic ticks or upload your own. Everything downstream (backtests, sweeps, "
           "walk-forward) uses the dataset chosen here.")

src = st.radio("Source", ["Synthetic generator", "Upload CSV"], horizontal=True)
if src == "Synthetic generator":
    with st.form("gen"):
        c = st.columns(4)
        days = c[0].slider("Trading days", 5, 250, 60)
        tpd = c[1].select_slider("Ticks per day", [1_000, 2_000, 5_000, 8_000, 15_000, 30_000], value=8_000)
        vol = c[2].slider("Annual volatility", 0.05, 1.0, 0.25)
        spread = c[3].slider("Typical spread (bps)", 0.5, 30.0, 2.0)
        trend = c[0].slider("Trend strength", 0.0, 0.08, 0.012, step=0.002, format="%.3f",
                            help="Persistent intraday drift. 0 = pure random walk (no edge for anyone).")
        pers = c[1].slider("Trend persistence", 0.80, 0.999, 0.98, format="%.3f")
        jumps = c[2].slider("Jumps per day", 0.0, 5.0, 0.3)
        seed = c[3].number_input("Seed", 0, 10_000, 7)
        regimes = st.checkbox("Volatility regimes", True)
        if st.form_submit_button("Generate", type="primary"):
            st.session_state.ticks = make_ticks(days=days, ticks_per_day=tpd, annual_vol=vol, spread_bps=spread,
                                                trend_strength=trend, trend_persistence=pers, jumps_per_day=jumps,
                                                vol_regimes=regimes, seed=int(seed))
            st.session_state.ticks_label = f"Synthetic · {days}d · σ={vol:.0%} · trend={trend:.3f} · seed {seed}"
else:
    st.markdown("CSV with `ts,bid,ask[,volume]` quotes, or `ts,price[,volume]` trades (a spread is synthesised).")
    up = st.file_uploader("Tick file", type=["csv"])
    sp = st.number_input("Spread to synthesise for trade-only files (bps)", 0.1, 50.0, 2.0)
    if up is not None and st.button("Load file", type="primary"):
        try:
            st.session_state.ticks = load_csv(up.getvalue(), sp)
            st.session_state.ticks_label = f"Upload · {up.name}"
        except Exception as e:  # show a friendly parsing error
            st.error(f"Couldn't read that file: {e}")
    sample = make_ticks(days=2, ticks_per_day=1000)[["ts", "bid", "ask", "volume"]]
    st.download_button("Download a sample CSV", sample.to_csv(index=False), "sample_ticks.csv")

t = get_ticks()
mid = (t.bid + t.ask) / 2
spr_bps = (t.ask - t.bid) / mid * 1e4
st.subheader(st.session_state.get("ticks_label", ""))
k = st.columns(6)
k[0].metric("Ticks", f"{len(t):,}")
k[1].metric("Days", t.ts.dt.date.nunique())
k[2].metric("First / last mid", f"{mid.iloc[0]:.2f} → {mid.iloc[-1]:.2f}")
k[3].metric("Median spread", f"{spr_bps.median():.1f} bps")
dly = mid.groupby(t.ts.dt.date).last().pct_change().dropna()
k[4].metric("Realised vol (ann.)", f"{dly.std() * np.sqrt(252):.0%}" if len(dly) > 2 else "—")
k[5].metric("Volume", f"{t.volume.sum():,.0f}")

bar = st.select_slider("Chart bar size", ["5min", "15min", "30min", "1h"], value="30min")
t0 = time.perf_counter(); bars = resample(t, bar); cpp = time.perf_counter() - t0
t0 = time.perf_counter(); resample_pandas(t, bar); pdt = time.perf_counter() - t0
fig = go.Figure(go.Candlestick(x=bars.ts, open=bars.open, high=bars.high, low=bars.low, close=bars.close, name="mid"))
fig.update_layout(height=430, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10),
                  xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")]))
st.plotly_chart(fig, width="stretch")
st.caption(f"Resampling {len(t):,} ticks → {len(bars):,} bars: C++ kernel {cpp * 1e3:.1f} ms vs pandas groupby {pdt * 1e3:.1f} ms "
           f"({pdt / max(cpp, 1e-9):.0f}× faster).")

c1, c2, c3 = st.columns(3)
act = t.groupby(t.ts.dt.floor("15min").dt.time).size() / t.ts.dt.date.nunique()
f1 = px.bar(x=[str(x)[:5] for x in act.index], y=act.values, title="Intraday activity (ticks per 15 min)",
            labels={"x": "time", "y": "ticks"}, color_discrete_sequence=[BLUE])
c1.plotly_chart(f1, width="stretch")
f2 = px.histogram(spr_bps.clip(upper=spr_bps.quantile(0.995)), nbins=50, title="Spread distribution (bps)")
f2.update_layout(showlegend=False)
c2.plotly_chart(f2, width="stretch")
r = np.diff(np.log(bars.close.values))
f3 = px.histogram(r * 1e4, nbins=80, title=f"{bar} log returns (bps) — fat tails?")
f3.update_layout(showlegend=False)
c3.plotly_chart(f3, width="stretch")
kurt = pd.Series(r).kurt()
st.caption(f"Excess kurtosis of {bar} returns: **{kurt:.1f}** (0 for a normal distribution).")
with st.expander("Raw ticks (first 500)"):
    st.dataframe(t.head(500), width="stretch", hide_index=True)
