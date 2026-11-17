import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import optlib as O
from common import BLUE, GREEN, GREY, ORANGE, RED

st.title("🛠️ Strategy builder & risk")
st.caption("Combine legs, then see payoff, position Greeks and a full revaluation P&L grid over spot, time and vol.")

with st.sidebar:
    st.subheader("Market")
    S = st.number_input("Spot", 0.01, 1e6, 100.0, key="sb_S")
    r = st.number_input("Rate %", -5.0, 30.0, 5.0, key="sb_r") / 100
    q = st.number_input("Div yield %", 0.0, 30.0, 0.0, key="sb_q") / 100
    base_vol = st.number_input("Implied vol %", 1.0, 300.0, 25.0, key="sb_v") / 100
    mult = st.number_input("Contract multiplier", 1, 1000, 100)


def L(kind, K, days, qty):
    return {"type": kind, "strike": float(K), "days": int(days), "qty": int(qty), "vol %": base_vol * 100}


PRESETS = {
    "Long straddle": lambda s: [L("call", s, 45, 1), L("put", s, 45, 1)],
    "Short strangle": lambda s: [L("call", s * 1.1, 45, -1), L("put", s * 0.9, 45, -1)],
    "Bull call spread": lambda s: [L("call", s, 60, 1), L("call", s * 1.1, 60, -1)],
    "Iron condor": lambda s: [L("put", s * 0.85, 45, 1), L("put", s * 0.92, 45, -1), L("call", s * 1.08, 45, -1), L("call", s * 1.15, 45, 1)],
    "Long butterfly": lambda s: [L("call", s * 0.95, 30, 1), L("call", s, 30, -2), L("call", s * 1.05, 30, 1)],
    "Covered call": lambda s: [L("stock", 0, 0, 100), L("call", s * 1.05, 30, -1)],
    "Protective put": lambda s: [L("stock", 0, 0, 100), L("put", s * 0.95, 90, 1)],
    "Risk reversal": lambda s: [L("call", s * 1.1, 90, 1), L("put", s * 0.9, 90, -1)],
    "Calendar spread": lambda s: [L("call", s, 30, -1), L("call", s, 120, 1)],
}
preset = st.selectbox("Start from a preset", list(PRESETS))
if st.session_state.get("preset") != (preset, S, base_vol):
    st.session_state.preset = (preset, S, base_vol)
    st.session_state.legs = pd.DataFrame(PRESETS[preset](S))
legs = st.data_editor(st.session_state.legs, num_rows="dynamic", width="stretch", key=f"legs_{preset}",
                      column_config={"type": st.column_config.SelectboxColumn(options=["call", "put", "stock"], required=True),
                                     "strike": st.column_config.NumberColumn(format="%.2f"),
                                     "days": st.column_config.NumberColumn("days to expiry", min_value=0),
                                     "qty": st.column_config.NumberColumn("qty (contracts; shares for stock)"),
                                     "vol %": st.column_config.NumberColumn(format="%.1f")})
legs = legs.dropna(subset=["type"]).reset_index(drop=True)
if legs.empty:
    st.info("Add at least one leg.")
    st.stop()


def value(spot, days_fwd=0.0, vol_shift=0.0, rate=r):
    """Portfolio value for array of spots, `days_fwd` days from now, vols shifted by `vol_shift` (abs)."""
    spot = np.asarray(spot, dtype=float)
    tot = np.zeros_like(spot)
    g = {k: np.zeros_like(spot) for k in ("delta", "gamma", "vega", "theta")}
    for lg in legs.to_dict("records"):
        if lg["type"] == "stock":
            tot += lg["qty"] * spot
            g["delta"] += lg["qty"]
            continue
        T = max((lg["days"] - days_fwd) / 365, 0.0)
        out = O.bs_vec(spot, lg["strike"], T, rate, q, max(lg["vol %"] / 100 + vol_shift, 1e-4), lg["type"] == "call")
        n = lg["qty"] * mult
        tot += n * out["price"]
        for k in g:
            g[k] += n * out[k]
    return tot, g


cost, g0 = value(np.array([S]))
cost = float(cost[0])
max_days = int(legs[legs.type != "stock"].days.min()) if (legs.type != "stock").any() else 30
spots = np.linspace(S * 0.6, S * 1.4, 401)
expiry_val, _ = value(spots, max_days)
now_val, _ = value(spots, 0)

k = st.columns(6)
k[0].metric("Net premium / cost", f"${cost:,.2f}", "debit" if cost > 0 else "credit", delta_color="off")
k[1].metric("Δ (shares)", f"{g0['delta'][0]:,.1f}")
k[2].metric("Γ (Δ per $1)", f"{g0['gamma'][0]:,.2f}")
k[3].metric("Vega ($ per vol pt)", f"{g0['vega'][0]:,.2f}")
k[4].metric("Θ ($ per day)", f"{g0['theta'][0]:,.2f}")
pnl_exp = expiry_val - cost
be = spots[np.where(np.diff(np.sign(pnl_exp)) != 0)[0]]
k[5].metric("Breakevens (at first expiry)", ", ".join(f"{b:.2f}" for b in be[:4]) if len(be) else "none in range")

t1, t2, t3 = st.tabs(["Payoff & value", "P&L heatmap", "Scenarios & Greeks profile"])
with t1:
    c1, c2 = st.columns([3, 1])
    days_slider = c2.slider("Value curve at day", 0, max_days, max_days // 2)
    vs = c2.slider("Vol shift (pts)", -20, 20, 0) / 100
    mid_val, _ = value(spots, days_slider, vs)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=spots, y=pnl_exp, name=f"at first expiry (day {max_days})", line=dict(color="black", width=3)))
    fig.add_trace(go.Scatter(x=spots, y=now_val - cost, name="today", line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=spots, y=mid_val - cost, name=f"day {days_slider}, vol {vs * 100:+.0f}", line=dict(color=ORANGE, dash="dash")))
    fig.add_hline(y=0, line_color=GREY)
    fig.add_vline(x=S, line_dash="dot", annotation_text="spot")
    fig.update_layout(height=470, xaxis_title="underlying", yaxis_title="P&L ($)", margin=dict(l=10, r=10, t=10, b=10))
    c1.plotly_chart(fig, width="stretch")
    c2.metric("Max profit (range)", f"${pnl_exp.max():,.0f}")
    c2.metric("Max loss (range)", f"${pnl_exp.min():,.0f}")
    lo_pr = (np.log(spots[1:] / S) - (r - q - 0.5 * base_vol ** 2) * max_days / 365) / (base_vol * np.sqrt(max_days / 365))
    from math import erf
    cdf = 0.5 * (1 + np.vectorize(erf)(lo_pr / np.sqrt(2)))
    pdf = np.diff(np.r_[0, cdf])
    c2.metric("P(profit) at expiry, lognormal", f"{pdf[pnl_exp[1:] > 0].sum():.0%}")

with t2:
    c1, c2 = st.columns([3, 1])
    vshift = c2.slider("Vol shift (pts)", -20, 20, 0, key="hm_v") / 100
    rel = np.linspace(-0.2, 0.2, 41)
    days = np.unique(np.linspace(0, max_days, min(max_days + 1, 16)).astype(int))
    Z = np.array([value(S * (1 + rel), d, vshift)[0] - cost for d in days])
    fig = px.imshow(Z, x=[f"{x:+.0%}" for x in rel], y=[f"day {d}" for d in days], color_continuous_scale="RdYlGn",
                    color_continuous_midpoint=0, aspect="auto", labels=dict(x="spot move", y="", color="P&L $"))
    fig.update_layout(height=520)
    c1.plotly_chart(fig, width="stretch")
    c2.caption("Full revaluation (not a Greek approximation) on a spot × time grid. Short-premium structures go green "
               "along the time axis (theta), long-gamma ones need the spot to move.")

with t3:
    moves = [-0.2, -0.1, -0.05, -0.02, 0, 0.02, 0.05, 0.1, 0.2]
    vols = [-0.10, -0.05, 0, 0.05, 0.10]
    grid = pd.DataFrame({f"vol {v * 100:+.0f}": [value(np.array([S * (1 + m)]), 1, v)[0][0] - cost for m in moves] for v in vols},
                        index=[f"spot {m:+.0%}" for m in moves])
    st.markdown("**Scenario P&L, one day forward ($)**")
    st.dataframe(grid.style.format("{:,.0f}").background_gradient(cmap="RdYlGn", axis=None), width="stretch")
    approx = pd.DataFrame({"spot move": moves})
    approx["full reval"] = [value(np.array([S * (1 + m)]))[0][0] - cost for m in moves]
    approx["Δ-Γ approx"] = [g0["delta"][0] * S * m + 0.5 * g0["gamma"][0] * (S * m) ** 2 for m in moves]
    approx["Δ only"] = [g0["delta"][0] * S * m for m in moves]
    c1, c2 = st.columns(2)
    c1.plotly_chart(px.line(approx, x="spot move", y=["full reval", "Δ-Γ approx", "Δ only"], markers=True,
                            title="Instant P&L: full revaluation vs Taylor approximations"), width="stretch")
    _, gs = value(spots, 0)
    gp = pd.DataFrame({"spot": spots, **{k: v for k, v in gs.items()}})
    which = c2.selectbox("Greek profile", ["delta", "gamma", "vega", "theta"])
    c2.plotly_chart(px.line(gp, x="spot", y=which, title=f"Position {which} vs spot"), width="stretch")
