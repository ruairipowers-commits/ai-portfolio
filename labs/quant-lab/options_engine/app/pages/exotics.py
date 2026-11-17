import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import optlib as O
from common import BLUE, GREEN, GREY, ORANGE, RED, fmt_time, market_inputs

st.title("🧩 Exotics & American options")
st.caption("Where closed forms run out: path-dependent payoffs and early exercise, with analytic anchors where they exist.")
p = market_inputs(show_type=False)
S, K, T, r, q, vol = p["S"], p["K"], p["T"], p["r"], p["q"], p["vol"]

t1, t2, t3 = st.tabs(["Asian (arithmetic average)", "Barrier (up-and-out call)", "American put"])

with t1:
    c1, c2 = st.columns([1, 2.3])
    fix = c1.slider("Averaging fixings", 2, 252, 52)
    paths = c1.select_slider("Paths", [20_000, 100_000, 400_000, 1_000_000], value=400_000, key="ap")
    call = c1.radio("Type", ["Call", "Put"], horizontal=True, key="acp") == "Call"
    plain = O.mc(S, K, T, r, q, vol, call, "asian", paths, fix, False, False)
    anti = O.mc(S, K, T, r, q, vol, call, "asian", paths, fix, True, False)
    cv = O.mc(S, K, T, r, q, vol, call, "asian", paths, fix, True, True)
    geo = O.geometric_asian(S, K, T, r, q, vol, fix, call)
    van = O.bs(S, K, T, r, q, vol, call)["price"]
    df = pd.DataFrame([
        {"estimator": "Plain MC", "price": plain["price"], "±95%": 1.96 * plain["stderr"], "time": fmt_time(plain["seconds"])},
        {"estimator": "Antithetic", "price": anti["price"], "±95%": 1.96 * anti["stderr"], "time": fmt_time(anti["seconds"])},
        {"estimator": "Antithetic + geometric-Asian control", "price": cv["price"], "±95%": 1.96 * cv["stderr"], "time": fmt_time(cv["seconds"])},
        {"estimator": "Geometric Asian (closed form)", "price": geo, "±95%": 0.0, "time": "—"},
        {"estimator": "European vanilla (closed form)", "price": van, "±95%": 0.0, "time": "—"},
    ])
    c1.dataframe(df, hide_index=True, width="stretch",
                 column_config={"price": st.column_config.NumberColumn(format="%.5f"), "±95%": st.column_config.NumberColumn(format="%.5f")})
    c1.metric("Variance reduction from the control", f"{(plain['stderr'] / cv['stderr']) ** 2:,.0f}×",
              f"β = {cv['beta']:.3f}", delta_color="off")
    paths_ = O.sample_paths(S, T, r, q, vol, fix, 40, 3)
    t = np.linspace(0, T, fix + 1)
    fig = go.Figure()
    for i in range(len(paths_)):
        fig.add_trace(go.Scatter(x=t, y=paths_[i], line=dict(width=0.8, color=GREY), opacity=0.5, showlegend=False))
        fig.add_trace(go.Scatter(x=[T], y=[paths_[i, 1:].mean()], mode="markers", marker=dict(color=BLUE, size=6), showlegend=i == 0, name="arithmetic average"))
        fig.add_trace(go.Scatter(x=[T], y=[paths_[i, -1]], mode="markers", marker=dict(color=ORANGE, size=6, symbol="x"), showlegend=i == 0, name="terminal price"))
    fig.add_hline(y=K, line_dash="dot", annotation_text="strike")
    fig.update_layout(title="Averaging dampens the payoff: averages cluster far tighter than terminal prices", height=440,
                      xaxis_title="years", margin=dict(l=10, r=10, t=40, b=10))
    c2.plotly_chart(fig, width="stretch")
    st.caption("The geometric average of lognormal prices is lognormal, so its option has a closed form. It is "
               "almost perfectly correlated with the arithmetic payoff, which makes it a near-ideal control variate.")

with t2:
    c1, c2 = st.columns([1, 2.3])
    H = c1.number_input("Barrier (up-and-out)", float(K) * 1.001, float(K) * 5, float(round(max(S, K) * 1.3, 2)))
    paths_b = c1.select_slider("Paths", [50_000, 200_000, 500_000], value=200_000, key="bp")
    cont = O.up_and_out_call(S, K, H, T, r, q, vol)
    van = O.bs(S, K, T, r, q, vol, True)["price"]
    rows = []
    for label, m in (("monthly", 12), ("weekly", 52), ("daily", 252), ("4× daily", 1008)):
        n = max(1, int(round(m * T)))
        o = O.mc(S, K, T, r, q, vol, True, "barrier_uo", paths_b, n, True, True, H)
        bgk = O.up_and_out_call(S, K, H * np.exp(0.5826 * vol * np.sqrt(T / n)), T, r, q, vol)
        rows.append({"monitoring": label, "fixings": n, "MC price": o["price"], "±95%": 1.96 * o["stderr"],
                     "BGK-corrected closed form": bgk, "time": fmt_time(o["seconds"])})
    bt = pd.DataFrame(rows)
    c1.metric("Continuous-monitoring closed form", f"{cont:.4f}")
    c1.metric("Vanilla call", f"{van:.4f}", f"knock-out discount {(1 - cont / van):.0%}", delta_color="off")
    c1.dataframe(bt, hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="%.4f") for k in ["MC price", "±95%", "BGK-corrected closed form"]})
    Hs = np.linspace(K * 1.02, K * 2.2, 80)
    curve = [O.up_and_out_call(S, K, h, T, r, q, vol) for h in Hs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=Hs, y=curve, name="continuous closed form", line=dict(color=BLUE)))
    fig.add_hline(y=van, line_dash="dot", annotation_text="vanilla")
    hs_mc = np.linspace(K * 1.05, K * 2.0, 10)
    mc_pts = [O.mc(S, K, T, r, q, vol, True, "barrier_uo", 50_000, max(1, int(52 * T)), True, True, h)["price"] for h in hs_mc]
    fig.add_trace(go.Scatter(x=hs_mc, y=mc_pts, mode="markers", name="MC, weekly monitoring", marker=dict(color=ORANGE, size=9)))
    fig.add_vline(x=H, line_dash="dash", line_color=RED, annotation_text="your barrier")
    fig.update_layout(title="Up-and-out call vs barrier level", xaxis_title="barrier", yaxis_title="price", height=440)
    c2.plotly_chart(fig, width="stretch")
    st.caption("Discrete monitoring misses crossings between fixings, so it is worth more than the continuous price. "
               "The Broadie-Glasserman-Kou trick (shift the barrier by e^{0.5826 σ√Δt}) maps the continuous formula onto "
               "a discretely monitored one.")

with t3:
    c1, c2 = st.columns([1, 2.3])
    lsm_paths = c1.select_slider("LSM paths", [20_000, 50_000, 100_000, 200_000, 400_000], value=100_000)
    lsm_steps = c1.slider("LSM exercise dates", 10, 200, 50)
    tree = O.binomial(S, K, T, r, q, vol, 2001, False, True, "lr", True)
    euro = O.bs(S, K, T, r, q, vol, False)["price"]
    lsm = O.lsm_american(S, K, T, r, q, vol, False, lsm_steps, lsm_paths, 11)
    c1.metric("Leisen-Reimer tree (2001 steps)", f"{tree['price']:.4f}")
    c1.metric("Longstaff-Schwartz MC", f"{lsm['price']:.4f}", f"± {1.96 * lsm['stderr']:.4f} · {fmt_time(lsm['seconds'])}", delta_color="off")
    c1.metric("European put", f"{euro:.4f}", f"early-exercise premium {tree['price'] - euro:.4f}", delta_color="off")
    c1.caption("LSM is biased low: it only exercises on its discrete dates and its regression policy is sub-optimal.")
    fig = go.Figure()
    bt = pd.DataFrame({"t": tree["boundary_t"], "S": tree["boundary_S"]}).dropna()
    bl = pd.DataFrame({"t": lsm["boundary_t"], "S": lsm["boundary_S"]}).dropna()
    paths_ = O.sample_paths(S, T, r, q, vol, 252, 25, 5)
    tt = np.linspace(0, T, 253)
    bS = np.interp(tt, bt.t, bt.S, left=np.nan) if len(bt) else np.full_like(tt, np.nan)
    for i in range(len(paths_)):
        hit = np.where(paths_[i] <= bS)[0]
        fig.add_trace(go.Scatter(x=tt, y=paths_[i], line=dict(width=0.7, color=GREY), opacity=0.6, showlegend=False))
        if len(hit):
            fig.add_trace(go.Scatter(x=[tt[hit[0]]], y=[paths_[i, hit[0]]], mode="markers", marker=dict(color=RED, size=8),
                                     showlegend=i == 0 or False, name="optimal exercise"))
    fig.add_trace(go.Scatter(x=bt.t, y=bt.S, name="exercise boundary (tree)", line=dict(color=BLUE, width=3)))
    fig.add_trace(go.Scatter(x=bl.t, y=bl.S, name="exercise boundary (LSM)", mode="markers", marker=dict(color=GREEN, size=5)))
    fig.add_hline(y=K, line_dash="dot", annotation_text="strike")
    fig.update_layout(title="Exercise the put once the stock falls below the boundary", xaxis_title="years", yaxis_title="stock",
                      height=480, margin=dict(l=10, r=10, t=40, b=10))
    c2.plotly_chart(fig, width="stretch")
    rs = np.linspace(0.0, 0.12, 13)
    prem = [O.binomial(S, K, T, x, q, vol, 501, False, True, "lr")["price"] - O.bs(S, K, T, x, q, vol, False)["price"] for x in rs]
    f2 = px.line(x=rs * 100, y=prem, markers=True, labels={"x": "interest rate %", "y": "early-exercise premium"},
                 title="Higher rates make early exercise of puts more valuable")
    f2.update_layout(height=300)
    st.plotly_chart(f2, width="stretch")
