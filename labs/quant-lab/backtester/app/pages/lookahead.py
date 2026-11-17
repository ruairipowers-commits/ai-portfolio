from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import data_badge, exec_controls, get_ticks
from qlbt import Backtest, LeakyStrategy, MACross, resample
from qlbt.metrics import perf

st.title("🔮 Lookahead-bias lab")
data_badge()
st.caption("The same MA-crossover idea, backtested honestly and with the classic mistakes. "
           "On data with no edge, the biased versions still look great.")
ticks = get_ticks()
with st.sidebar:
    st.subheader("Strategy (MA crossover)")
    c1, c2 = st.columns(2)
    fast = int(c1.number_input("Fast", 1, 500, 10))
    slow = int(c2.number_input("Slow", 2, 2000, 40))
cfg = exec_controls("l_", show_mode=False)

if st.button("Run all variants", type="primary") or "la" not in st.session_state:
    with st.spinner("Running event-driven and vectorised variants…"):
        good = Backtest(ticks, MACross(fast, slow), cfg).run()
        same_close = Backtest(ticks, MACross(fast, slow), replace(cfg, fill_mode="same_bar_close")).run()
        leaky = Backtest(ticks.iloc[: min(len(ticks), 50_000)], LeakyStrategy(), cfg).run()

        bars = resample(ticks, cfg.bar).set_index("ts")
        c = bars.close
        r = c.pct_change().fillna(0)
        units = cfg.size * c.iloc[0] / cfg.init_cash  # same capital at work as the event engine
        sig = np.sign(c.rolling(fast).mean() - c.rolling(slow).mean()).fillna(0)
        sig_c = np.sign(c.rolling(fast, center=True).mean() - c.rolling(slow).mean()).fillna(0)  # fast MA uses future bars
        z = (c - c.mean()) / c.std()  # full-sample normalisation
        sig_z = -np.sign(z - z.rolling(slow).mean()).fillna(0)
        vec = {
            "Vectorised, correct (signal shifted 1 bar, no costs)": (1 + units * sig.shift(1).fillna(0) * r).cumprod(),
            "Vectorised, forgot .shift(1)": (1 + units * sig * r).cumprod(),
            "Vectorised, centred fast MA (rolling(center=True))": (1 + units * sig_c.shift(1).fillna(0) * r).cumprod(),
            "Vectorised, peeks at next bar (shift(-1) target)": (1 + units * np.sign(r) * r).cumprod(),
        }
        st.session_state.la = dict(good=good, same=same_close, leaky=leaky, vec=vec, bars=bars)

S = st.session_state.la
good, same = S["good"], S["same"]
bpy = good.bars_per_year
curves = {
    "Event-driven: next tick + latency + costs (honest)": (good.bars.ts, good.bars.equity / good.cfg.init_cash),
    "Event-driven: filled at the signal bar's close": (same.bars.ts, same.bars.equity / same.cfg.init_cash),
}
for k, v in S["vec"].items():
    curves[k] = (v.index, v.values)

rows = []
honest = perf(curves["Event-driven: next tick + latency + costs (honest)"][1], bpy)["Sharpe"]
for name, (x, y) in curves.items():
    p = perf(np.asarray(y), bpy)
    rows.append({"variant": name, "Sharpe": p["Sharpe"], "Total return": p["Total return"], "Max DD": p["Max drawdown"],
                 "Sharpe inflation": p["Sharpe"] - honest})
tbl = pd.DataFrame(rows)

fig = go.Figure()
styles = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"]
for i, (name, (x, y)) in enumerate(curves.items()):
    fig.add_trace(go.Scatter(x=x, y=y, name=name, line=dict(width=3 if i == 0 else 1.5, dash=styles[i % 6])))
fig.update_layout(height=470, yaxis_title="growth of $1", legend=dict(orientation="h", y=-0.15),
                  margin=dict(l=10, r=10, t=10, b=10),
                  xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")]))
st.plotly_chart(fig, width="stretch")
st.dataframe(tbl, hide_index=True, width="stretch",
             column_config={"Sharpe": st.column_config.NumberColumn(format="%.2f"),
                            "Total return": st.column_config.NumberColumn(format="%.2%"),
                            "Max DD": st.column_config.NumberColumn(format="%.2%"),
                            "Sharpe inflation": st.column_config.NumberColumn(format="%+.2f")})
st.caption("Tip: on *Market data*, set trend strength to 0 (a pure random walk). Any positive Sharpe that survives is bias.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("What each mistake does")
    st.markdown("""
- **Filled at the signal bar's close.** The close that triggers the signal is also your fill price. In reality you
  decide *after* the bar closes and cross the spread on a later tick.
- **Forgot `.shift(1)`.** The position held over bar *t* is decided using bar *t*'s own close, so you earn a return
  you could only know afterwards.
- **Centred rolling window.** `rolling(center=True)` averages over future bars. It looks smooth and it is impossible to trade.
- **Peeking at the next bar.** The extreme case: the "signal" is next bar's direction.
""")
with c2:
    st.subheader("How the event engine prevents it")
    st.markdown(f"""
- Bars are published **only after a tick from the next bucket arrives**, as events on a time-ordered queue.
- Strategies get a read-only `History` of completed bars; `bars.at(i)` for an unclosed bar raises `LookaheadError`.
- Orders activate at decision time + latency and fill on the **first tick at or after** that time, at the bid/ask.

The deliberately leaky strategy below was run through the engine:
""")
    lk = S["leaky"]
    st.error(f"LookaheadError raised {len(lk.errors):,}× and 0 trades were placed. First: `{lk.errors[0] if lk.errors else ''}`")
    st.code("def on_bar(ctx):\n    nxt = ctx.bars.at(ctx.bar_index + 1)   # next bar's close\n    return 1 if nxt > ctx.bars.close[-1] else -1", "python")
