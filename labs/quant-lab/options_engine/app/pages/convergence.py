import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import optlib as O
from common import BLUE, GREEN, GREY, ORANGE, PURPLE, RED, fmt_time, market_inputs, timed

st.title("📉 Convergence & speed lab")
st.caption("How fast does each numerical method approach the analytical answer, and what does each digit of accuracy cost in time?")
p = market_inputs()
S, K, T, r, q, vol, call = p["S"], p["K"], p["T"], p["r"], p["q"], p["vol"], p["call"]
exact = O.bs(S, K, T, r, q, vol, call)["price"]
st.metric("Black-Scholes reference", f"{exact:.8f}")


def rgba(h, a):
    h = h.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def slope(x, y):
    m = (np.asarray(y) > 0) & np.isfinite(y)
    return np.polyfit(np.log(np.asarray(x)[m]), np.log(np.asarray(y)[m]), 1)[0] if m.sum() > 2 else np.nan


t1, t2, t3, t4 = st.tabs(["Binomial trees", "Monte Carlo", "Accuracy vs time frontier", "Thread scaling"])

with t1:
    steps = np.unique(np.round(np.geomspace(10, st.select_slider("Max steps", [500, 1000, 2000, 5000], value=2000), 60)).astype(int))
    rows = []
    for m, name in (("crr", "CRR"), ("jr", "Jarrow-Rudd"), ("lr", "Leisen-Reimer")):
        for n in steps:
            o, t = timed(O.binomial, S, K, T, r, q, vol, int(n), call, False, m)
            rows.append({"method": name, "steps": n + (1 if m == "lr" and n % 2 == 0 else 0), "price": o["price"],
                         "abs error": abs(o["price"] - exact), "seconds": t})
    df = pd.DataFrame(rows)
    st.session_state.binom = df
    c1, c2 = st.columns(2)
    f1 = px.line(df, x="steps", y="price", color="method", title="Price vs steps (note CRR's odd/even sawtooth)")
    f1.add_hline(y=exact, line_dash="dot", line_color="black", annotation_text="BS")
    c1.plotly_chart(f1, width="stretch")
    f2 = px.line(df, x="steps", y="abs error", color="method", log_x=True, log_y=True, title="Absolute error (log-log)")
    c2.plotly_chart(f2, width="stretch")
    sl = df.groupby("method").apply(lambda g: pd.Series({"empirical order": -slope(g.steps, g["abs error"]),
                                                         "error @ max steps": g["abs error"].iloc[-1],
                                                         "time @ max steps": fmt_time(g.seconds.iloc[-1])}), include_groups=False)
    st.dataframe(sl.reset_index(), hide_index=True, width="stretch",
                 column_config={"empirical order": st.column_config.NumberColumn(format="%.2f"),
                                "error @ max steps": st.column_config.NumberColumn(format="%.2e")})
    st.caption("CRR and JR converge at O(1/n) with oscillation, because the strike lands at a different place on the "
               "grid as n changes. Leisen-Reimer centres the tree on the strike and converges at about O(1/n²), so "
               "~100 steps beats CRR at 5,000.")

with t2:
    c1, c2 = st.columns([1, 3])
    max_paths = c1.select_slider("Max paths", [100_000, 1_000_000, 4_000_000], value=1_000_000)
    seed = c1.number_input("Seed", 0, 10**6, 42, key="mcseed")
    ns = np.unique(np.round(np.geomspace(1_000, max_paths, 18)).astype(int))
    variants = {"plain": (False, False), "antithetic": (True, False), "control variate": (False, True), "antithetic + CV": (True, True)}
    rows = []
    for name, (a, cv) in variants.items():
        for n in ns:
            o = O.mc(S, K, T, r, q, vol, call, "european", int(n), 1, a, cv, 0.0, int(seed))
            rows.append({"variant": name, "paths": n, "price": o["price"], "stderr": o["stderr"], "seconds": o["seconds"],
                         "abs error": abs(o["price"] - exact)})
    mc = pd.DataFrame(rows)
    st.session_state.mcconv = mc
    fig = go.Figure()
    cols = {"plain": GREY, "antithetic": BLUE, "control variate": ORANGE, "antithetic + CV": GREEN}
    for name, g in mc.groupby("variant", sort=False):
        fig.add_trace(go.Scatter(x=g.paths, y=g.price + 1.96 * g.stderr, line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=g.paths, y=g.price - 1.96 * g.stderr, fill="tonexty", line=dict(width=0),
                                 fillcolor=rgba(cols[name], 0.18), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=g.paths, y=g.price, name=name, line=dict(color=cols[name])))
    fig.add_hline(y=exact, line_dash="dot", line_color="black")
    fig.update_layout(title="Estimate with 95% confidence band", xaxis_type="log", height=420, margin=dict(l=10, r=10, t=40, b=10))
    c2.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns(2)
    f2 = px.line(mc, x="paths", y="stderr", color="variant", log_x=True, log_y=True, title="Standard error vs paths (slope −½)",
                 color_discrete_map=cols)
    c1.plotly_chart(f2, width="stretch")
    last = mc[mc.paths == mc.paths.max()].set_index("variant")
    vrf = (last.loc["plain", "stderr"] / last.stderr) ** 2
    eff = vrf * last.loc["plain", "seconds"] / last.seconds
    tab = pd.DataFrame({"stderr": last.stderr, "variance reduction ×": vrf, "time": last.seconds.map(fmt_time),
                        "efficiency gain ×": eff, "order": [-slope(g.paths, g.stderr) for _, g in mc.groupby("variant", sort=False)]})
    c2.markdown(f"**At {int(mc.paths.max()):,} paths**")
    c2.dataframe(tab.reset_index(), hide_index=True, width="stretch",
                 column_config={"stderr": st.column_config.NumberColumn(format="%.2e"),
                                "variance reduction ×": st.column_config.NumberColumn(format="%.1f"),
                                "efficiency gain ×": st.column_config.NumberColumn(format="%.1f"),
                                "order": st.column_config.NumberColumn(format="%.2f")})
    c2.caption("Efficiency gain = variance reduction × (plain time / method time): how many times fewer CPU-seconds the "
               "variant needs for the same accuracy. The control variate here is the discounted terminal stock price.")

with t3:
    pts = []
    _, tb = timed(O.bs, S, K, T, r, q, vol, call, repeat=5000)
    pts.append({"method": "Black-Scholes", "seconds": tb, "abs error": 1e-15, "label": "closed form"})
    b = st.session_state.get("binom")
    if b is not None:
        for _, rr in b.iterrows():
            pts.append({"method": f"Binomial {rr.method}", "seconds": rr.seconds, "abs error": max(rr["abs error"], 1e-15), "label": f"{rr.steps} steps"})
    m = st.session_state.get("mcconv")
    if m is not None:
        for _, rr in m.iterrows():
            pts.append({"method": f"MC {rr.variant}", "seconds": rr.seconds, "abs error": max(rr.stderr, 1e-15), "label": f"{rr.paths:,} paths"})
    d = pd.DataFrame(pts)
    fig = px.line(d, x="seconds", y="abs error", color="method", markers=True, log_x=True, log_y=True, hover_data=["label"],
                  title="Accuracy vs wall time (MC uses its standard error)")
    fig.update_traces(marker=dict(size=5))
    fig.update_layout(height=520)
    st.plotly_chart(fig, width="stretch")
    st.caption("Down-and-left is better. Closed form is ~a microsecond at machine precision. Leisen-Reimer reaches 1e-6 "
               "in about a millisecond. Monte Carlo pays √n: each extra digit costs 100× the paths, which is why "
               "variance reduction (and threads) matter. MC is still the only general tool for path-dependent, "
               "high-dimensional payoffs.")

with t4:
    hw = O.hardware_threads
    c1, c2 = st.columns([1, 3])
    payoff = c1.radio("Workload", ["european (1 step)", "asian (52 fixings)"])
    n = c1.select_slider("Paths", [500_000, 1_000_000, 4_000_000, 10_000_000], value=1_000_000 if "asian" in payoff else 4_000_000)
    ths = sorted(set([1, 2, 3, 4, 6, 8, 12, 16, 24, 32, hw, 2 * hw]) & set(range(1, 2 * hw + 1)))
    if c1.button("Run scaling test", type="primary") or "scal" not in st.session_state:
        rows = []
        for t in ths:
            pf, stp = ("asian", 52) if "asian" in payoff else ("european", 1)
            O.mc(S, K, T, r, q, vol, call, pf, int(n) // 10, stp, True, False, 0.0, 7, int(t))  # warm-up
            runs = [O.mc(S, K, T, r, q, vol, call, pf, int(n), stp, True, False, 0.0, 7, int(t)) for _ in range(3)]
            rows.append({"threads": t, "seconds": min(o["seconds"] for o in runs), "price": runs[0]["price"]})
        st.session_state.scal = pd.DataFrame(rows)
    sc = st.session_state.scal
    sc["speed-up"] = sc.seconds.iloc[0] / sc.seconds
    sc["efficiency"] = sc["speed-up"] / sc.threads
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sc.threads, y=sc["speed-up"], mode="lines+markers", name="measured", line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=sc.threads, y=np.minimum(sc.threads, hw), name=f"ideal (≤ {hw} hardware threads)", line=dict(dash="dot", color=GREY)))
    fig.update_layout(title="Speed-up vs threads", xaxis_title="threads", yaxis_title="× vs 1 thread", height=400)
    c2.plotly_chart(fig, width="stretch")
    st.dataframe(sc.assign(seconds=sc.seconds.map(fmt_time)), hide_index=True, width="stretch",
                 column_config={"price": st.column_config.NumberColumn(format="%.10f"),
                                "speed-up": st.column_config.NumberColumn(format="%.2f"),
                                "efficiency": st.column_config.NumberColumn(format="%.0%")})
    same = sc.price.nunique() == 1
    (st.success if same else st.warning)(
        "Identical price for every thread count: paths are generated in fixed blocks seeded by block id, so the "
        "work split never changes the random numbers." if same else "Prices differ across thread counts.")
    st.caption(f"Best of 3 runs per point. This machine reports {hw} hardware threads; past that, extra threads only add "
               "scheduling overhead, and small workloads are dominated by thread start-up.")
