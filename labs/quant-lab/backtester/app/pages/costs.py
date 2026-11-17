import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common import BLUE, GREY, RED, data_badge, exec_controls, get_ticks, heatmap
from qlbt import run_kernel
from qlbt.metrics import perf
from qlbt.walkforward import bars_per_year

st.title("💸 Cost & latency sensitivity")
data_badge()
st.caption("How much friction can the edge survive? Uses the C++ kernel (MA crossover), with runs in parallel threads.")
ticks = get_ticks()
with st.sidebar:
    st.subheader("Strategy (MA crossover)")
    c1, c2 = st.columns(2)
    fast = int(c1.number_input("Fast", 1, 500, 10))
    slow = int(c2.number_input("Slow", 2, 2000, 40))
    lo = st.checkbox("Long only")
cfg = exec_controls("c_", show_mode=False)
bpy = bars_per_year(ticks, cfg.bar)


def sharpe_of(c):
    k = run_kernel(ticks, fast, slow, c, lo)
    p = perf(k["equity"], bpy)
    return p.get("Sharpe", np.nan), p.get("Total return", np.nan), k


mults = [0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6]
lats = [0, 10, 100, 1_000, 5_000, 30_000, 60_000, 120_000]

tab1, tab2, tab3 = st.tabs(["Costs × latency grid", "Break-even cost", "Order size & market impact"])
with tab1:
    if st.button("Run grid (72 backtests)", type="primary") or "cgrid" not in st.session_state:
        t0 = time.perf_counter()
        jobs = [(m, l) for l in lats for m in mults]
        with ThreadPoolExecutor() as ex:
            out = list(ex.map(lambda ml: sharpe_of(replace(cfg.scaled_costs(ml[0]), latency_ms=float(ml[1])))[0], jobs))
        z = np.array(out).reshape(len(lats), len(mults))
        st.session_state.cgrid = (z, time.perf_counter() - t0)
    z, secs = st.session_state.cgrid
    st.plotly_chart(heatmap(z, [f"{m}×" for m in mults], [f"{l / 1000:g}s" if l >= 1000 else f"{l}ms" for l in lats],
                            "Net Sharpe by cost multiplier and decision latency", "cost multiplier (1× = sidebar settings)",
                            "latency"), width="stretch")
    st.caption(f"{z.size} full tick-level backtests of {len(ticks):,} ticks in {secs:.2f}s. "
               "Look down a column for latency decay (alpha that the market prices in before you trade) and along a row for cost drag.")

with tab2:
    ms = np.linspace(0, 6, 25)
    with ThreadPoolExecutor() as ex:
        res = list(ex.map(lambda m: sharpe_of(cfg.scaled_costs(m))[:2], ms))
    sh = np.array([r[0] for r in res])
    gross = sharpe_of(cfg.scaled_costs(0.0))[0]
    be = np.interp(0, sh[::-1], ms[::-1]) if (sh[0] > 0 > sh[-1]) else None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ms, y=sh, mode="lines+markers", name="net Sharpe", line=dict(color=BLUE)))
    fig.add_hline(y=0, line_color=GREY)
    fig.add_vline(x=1, line_dash="dot", annotation_text="your settings")
    if be is not None:
        fig.add_vline(x=be, line_color=RED, annotation_text=f"break-even {be:.2f}×")
    fig.update_layout(height=420, xaxis_title="cost multiplier (commission, slippage, impact; spread always paid)",
                      yaxis_title="Sharpe", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    c = st.columns(3)
    c[0].metric("Sharpe at 0× explicit costs (spread only)", f"{gross:.2f}")
    c[1].metric("Sharpe at your costs", f"{np.interp(1, ms, sh):.2f}")
    c[2].metric("Break-even multiplier", f"{be:.2f}×" if be is not None else ("> 6×" if sh[-1] > 0 else "< 0× (spread alone kills it)"))

with tab3:
    sizes = np.unique(np.round(np.geomspace(50, 200_000, 18), -1))
    with ThreadPoolExecutor() as ex:
        rs = list(ex.map(lambda s: sharpe_of(replace(cfg, size=float(s), init_cash=max(cfg.init_cash, s * 150))), sizes))
    rows = []
    for s, (sh_, tr, k) in zip(sizes, rs):
        notional = k["traded_notional"]
        rows.append({"shares per signal": s, "% of ADV per order": 100 * s / cfg.adv,
                     "impact bps": k["impact_cost"] / notional * 1e4 if notional else 0,
                     "spread bps": k["spread_cost"] / notional * 1e4 if notional else 0,
                     "commission bps": k["commission"] / notional * 1e4 if notional else 0, "net Sharpe": sh_})
    d = pd.DataFrame(rows)
    c1, c2 = st.columns(2)
    m = d.melt(id_vars="% of ADV per order", value_vars=["impact bps", "spread bps", "commission bps"], var_name="cost", value_name="bps")
    f1 = px.area(m, x="% of ADV per order", y="bps", color="cost", log_x=True, title="Cost per traded dollar vs order size")
    c1.plotly_chart(f1, width="stretch")
    f2 = px.line(d, x="% of ADV per order", y="net Sharpe", markers=True, log_x=True, title="Capacity: net Sharpe vs size")
    f2.add_hline(y=0, line_color=GREY)
    c2.plotly_chart(f2, width="stretch")
    st.caption("Commission per share dominates tiny orders (minimum ticket), impact (√size) dominates large ones. "
               "Where the Sharpe line crosses zero is a rough capacity estimate for the strategy.")
