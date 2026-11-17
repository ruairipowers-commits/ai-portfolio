import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from options_greeks_engine import _optlib as O
from options_greeks_engine.lab.common import fmt_time, market_inputs, timed

st.title("🗻 Greeks explorer")
st.caption("Price and Greeks over a grid, computed by the vectorised C++ Black-Scholes kernel. Second-order Greeks "
           "(vanna, volga, charm, speed) come from finite differences of the first-order ones.")
p = market_inputs()
S, K, T, r, q, vol, call = p["S"], p["K"], p["T"], p["r"], p["q"], p["vol"], p["call"]

GREEKS = ["price", "delta", "gamma", "vega", "theta", "rho", "vanna", "volga", "charm", "speed"]
c1, c2, c3, c4 = st.columns(4)
greek = c1.selectbox("Greek", GREEKS, index=2)
yaxis = c2.selectbox("Against spot and…", ["days to expiry", "volatility"])
res = c3.select_slider("Grid resolution", [40, 80, 160, 320], value=160)
view = c4.radio("View", ["3D surface", "Heatmap"], horizontal=True)

spots = np.linspace(S * 0.5, S * 1.5, res)
if yaxis == "days to expiry":
    ys = np.linspace(max(1, T * 365 * 0.02), max(T * 365 * 1.5, 30), res)
    Sg, Yg = np.meshgrid(spots, ys)
    Tg, Vg = Yg / 365, np.full_like(Sg, vol)
else:
    ys = np.linspace(0.05, max(0.8, vol * 2), res)
    Sg, Yg = np.meshgrid(spots, ys)
    Tg, Vg = np.full_like(Sg, T), Yg


def grid(Sx=Sg, Tx=Tg, Vx=Vg):
    return O.bs_vec(Sx, K, Tx, r, q, Vx, call)


out, secs = timed(grid)
if greek in ("vanna", "volga", "charm", "speed"):
    h, dv, dt = S * 1e-3, 1e-4, 1 / 3650
    if greek == "vanna":   # d delta / d vol
        Z = (grid(Vx=Vg + dv)["delta"] - grid(Vx=Vg - dv)["delta"]) / (2 * dv) / 100
    elif greek == "volga":  # d vega / d vol
        Z = (grid(Vx=Vg + dv)["vega"] - grid(Vx=Vg - dv)["vega"]) / (2 * dv) / 100
    elif greek == "charm":  # d delta / d time (per day, as time passes)
        Z = -(grid(Tx=Tg + dt)["delta"] - grid(Tx=np.maximum(Tg - dt, 1e-6))["delta"]) / (2 * dt) / 365
    else:                   # d gamma / d spot
        Z = (grid(Sx=Sg + h)["gamma"] - grid(Sx=Sg - h)["gamma"]) / (2 * h)
else:
    Z = out[greek]

ylab = "days to expiry" if yaxis == "days to expiry" else "volatility"
if view == "3D surface":
    fig = go.Figure(go.Surface(x=spots, y=ys if yaxis == "days to expiry" else ys * 100, z=Z, colorscale="Viridis",
                               contours=dict(z=dict(show=True, usecolormap=True, project_z=True))))
    fig.update_layout(height=620, scene=dict(xaxis_title="spot", yaxis_title=ylab + ("" if yaxis == "days to expiry" else " %"),
                                             zaxis_title=greek), margin=dict(l=0, r=0, t=10, b=0))
else:
    fig = px.imshow(Z, x=spots, y=ys if yaxis == "days to expiry" else ys * 100, origin="lower", aspect="auto",
                    color_continuous_scale="RdBu_r", labels=dict(x="spot", y=ylab, color=greek))
    fig.add_vline(x=K, line_dash="dot", annotation_text="strike")
    fig.update_layout(height=560)
st.plotly_chart(fig, width="stretch")
st.caption(f"{Z.size:,} option valuations in {fmt_time(secs)} ({secs / Z.size * 1e9:.0f} ns each, including NumPy broadcasting).")

st.subheader(f"{greek.capitalize()} vs spot: slices")
c1, c2 = st.columns(2)
dd = [7, 30, 90, 180, 365]
x = np.linspace(S * 0.6, S * 1.4, 400)
rows = []
for d in dd:
    g = O.bs_vec(x, K, d / 365, r, q, vol, call)
    if greek in GREEKS[:6]:
        rows.append(pd.DataFrame({"spot": x, "value": g[greek], "slice": f"{d}d"}))
if rows:
    c1.plotly_chart(px.line(pd.concat(rows), x="spot", y="value", color="slice", title=f"{greek} by time to expiry"), width="stretch")
rows = []
for v in [0.1, 0.2, 0.4, 0.8]:
    g = O.bs_vec(x, K, T, r, q, v, call)
    if greek in GREEKS[:6]:
        rows.append(pd.DataFrame({"spot": x, "value": g[greek], "slice": f"σ={v:.0%}"}))
if rows:
    c2.plotly_chart(px.line(pd.concat(rows), x="spot", y="value", color="slice", title=f"{greek} by volatility"), width="stretch")
with st.expander("Reading the shapes"):
    st.markdown("""
- **Gamma** and **theta** spike at the strike as expiry approaches: short-dated at-the-money options are the most
  convex and decay the fastest.
- **Vega** is largest for long-dated, at-the-money options.
- **Vanna** (Δ sensitivity to vol) changes sign at the strike; it drives how delta hedges drift when vol moves.
- **Charm** is the delta you lose or gain overnight with nothing else changing, which matters for end-of-day hedging.
""")
