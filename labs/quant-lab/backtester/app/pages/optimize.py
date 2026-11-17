import time

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import qlbt_core
from common import BLUE, GREY, RED, data_badge, exec_controls, get_ticks, heatmap
from qlbt import run_kernel
from qlbt.metrics import perf
from qlbt.walkforward import sweep, walk_forward

st.title("🧭 Parameter sweep & walk-forward")
data_badge()
ticks = get_ticks()
with st.sidebar:
    st.subheader("Grid (MA crossover)")
    f_lo, f_hi = st.slider("Fast window range", 1, 100, (2, 30))
    f_step = st.number_input("Fast step", 1, 20, 2)
    s_lo, s_hi = st.slider("Slow window range", 5, 600, (20, 240))
    s_step = st.number_input("Slow step", 1, 100, 10)
    lo = st.checkbox("Long only")
cfg = exec_controls("o_", show_mode=False)
fasts = list(range(f_lo, f_hi + 1, int(f_step)))
slows = list(range(s_lo, s_hi + 1, int(s_step)))

tab1, tab2 = st.tabs(["Grid sweep", "Walk-forward"])
with tab1:
    c1, c2 = st.columns([1, 3])
    metric = c1.radio("Colour by", ["sharpe", "gross_sharpe", "total_return", "max_dd", "turnover", "cost_bps"])
    threads = c1.slider("Threads", 1, max(1, qlbt_core.hardware_threads), max(1, qlbt_core.hardware_threads))
    if c1.button("Run sweep", type="primary") or "grid" not in st.session_state:
        st.session_state.grid = (sweep(ticks, fasts, slows, cfg, lo, threads), fasts, slows, threads)
    g, gf, gs, th = st.session_state.grid
    z = g[metric]
    best = np.unravel_index(np.nanargmax(np.where(np.isnan(g["sharpe"]), -np.inf, g["sharpe"])), g["sharpe"].shape)
    n = int(np.sum(~np.isnan(g["sharpe"])))
    fmt = ".1%" if metric in ("total_return", "max_dd") else ".2f"
    c2.plotly_chart(heatmap(z, gs, gf, f"{metric} over {n} parameter pairs", "slow window", "fast window", fmt=fmt,
                            colorscale="RdYlGn_r" if metric in ("cost_bps", "turnover") else "RdYlGn",
                            zmid=None if metric in ("cost_bps", "turnover", "max_dd") else 0,
                            mark=(gs[best[1]], gf[best[0]])), width="stretch")
    c1.metric("Backtests run", f"{n:,}")
    c1.metric("Wall time", f"{g['seconds']:.2f} s", f"{n * len(ticks) / g['seconds'] / 1e6:,.0f}M tick-steps/s", delta_color="off")
    c1.metric("Best (net Sharpe)", f"{gf[best[0]]}/{gs[best[1]]}", f"{g['sharpe'][best]:.2f}", delta_color="off")

    vals = g["sharpe"][~np.isnan(g["sharpe"])]
    cA, cB = st.columns(2)
    fh = px.histogram(vals, nbins=40, title="Distribution of net Sharpe across the grid")
    fh.add_vline(x=np.max(vals), line_color=RED, annotation_text="what you'd report")
    fh.add_vline(x=np.median(vals), line_color=GREY, annotation_text="median")
    fh.update_layout(showlegend=False, height=330)
    cA.plotly_chart(fh, width="stretch")
    # crude multiple-testing haircut: expected max of N iid N(0,1) Sharpe estimates over this many bars
    nb = len(run_kernel(ticks, 2, 3, cfg)["equity"])
    yrs = nb / g["bars_per_year"]
    e_max = np.sqrt(2 * np.log(max(n, 2))) / np.sqrt(max(yrs, 1e-9))
    cB.markdown(f"""
**Selection-bias check**

- {n:,} configurations tested on {yrs:.2f} years of bars.
- With **zero** true edge, the best of {n:,} noisy Sharpe estimates would still be ≈ **{e_max:.2f}**.
- Best found: **{np.max(vals):.2f}**; grid median **{np.median(vals):.2f}**.

A best value not far above the noise level, or a smooth plateau only in one corner, is a warning sign.
Walk-forward (next tab) tests the *process* of picking parameters, not the lucky winner.
""")
    if st.button("Scaling test: 1 thread vs all threads"):
        r1 = sweep(ticks, fasts, slows, cfg, lo, 1)["seconds"]
        rn = sweep(ticks, fasts, slows, cfg, lo, 0)["seconds"]
        st.info(f"1 thread {r1:.2f}s → {qlbt_core.hardware_threads} threads {rn:.2f}s · speed-up {r1 / rn:.2f}×")

with tab2:
    c = st.columns(4)
    folds = c[0].slider("Folds", 2, 12, 5)
    train = c[1].slider("Train share of each fold", 0.5, 0.9, 0.75)
    anchored = c[2].checkbox("Anchored (expanding) window")
    target = c[3].selectbox("Optimise", ["sharpe", "total_return"])
    if st.button("Run walk-forward", type="primary") or "wf" not in st.session_state:
        try:
            st.session_state.wf = walk_forward(ticks, fasts, slows, cfg, folds, train, anchored, lo, target)
        except ValueError as e:
            st.error(str(e)); st.stop()
    wf, oos = st.session_state.wf
    # hindsight benchmark: best params chosen on the full sample
    full = sweep(ticks, fasts, slows, cfg, lo)
    bi = np.unravel_index(np.nanargmax(np.where(np.isnan(full["sharpe"]), -np.inf, full["sharpe"])), full["sharpe"].shape)
    hb = run_kernel(ticks, fasts[bi[0]], slows[bi[1]], cfg, lo)
    hind = pd.DataFrame({"ts": pd.to_datetime(hb["bar_end"]), "equity": hb["equity"]})
    if len(oos):
        hind = hind[hind.ts >= oos.ts.min()]
        hind["equity"] = hind.equity / hind.equity.iloc[0] * oos.equity.iloc[0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hind.ts, y=hind.equity, name=f"Hindsight best {fasts[bi[0]]}/{slows[bi[1]]} (in-sample!)",
                             line=dict(color=GREY, dash="dot")))
    for k_, gg in oos.groupby("fold"):
        fig.add_trace(go.Scatter(x=gg.ts, y=gg.equity, name=f"OOS fold {k_}", line=dict(width=2)))
    fig.update_layout(title="Stitched out-of-sample equity vs hindsight-optimised equity", height=430,
                      margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")]))
    st.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns([1.6, 1])
    c1.dataframe(wf, hide_index=True, width="stretch",
                 column_config={"IS sharpe": st.column_config.NumberColumn(format="%.2f"),
                                "OOS sharpe": st.column_config.NumberColumn(format="%.2f"),
                                "OOS return": st.column_config.NumberColumn(format="%.2%")})
    if len(wf):
        m = wf.melt(id_vars="fold", value_vars=["IS sharpe", "OOS sharpe"], var_name="", value_name="Sharpe")
        c2.plotly_chart(px.bar(m, x="fold", y="Sharpe", color="", barmode="group", height=300), width="stretch")
        deg = 1 - wf["OOS sharpe"].mean() / wf["IS sharpe"].mean() if wf["IS sharpe"].mean() else np.nan
        stitched = perf(oos.equity.values, full["bars_per_year"]).get("Sharpe", np.nan)
        c2.metric("Stitched OOS Sharpe", f"{stitched:.2f}")
        c2.metric("IS → OOS degradation", f"{deg:.0%}")
