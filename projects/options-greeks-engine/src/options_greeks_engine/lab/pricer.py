import numpy as np
import pandas as pd
import streamlit as st

from options_greeks_engine import _optlib as O
from options_greeks_engine.lab.common import bs_ns_per_option, fmt_time, market_inputs, mc_greeks, timed

st.title("🧮 Pricer & Greeks")
st.caption("One contract, priced every way the engine knows. Errors are measured against the closed form.")
p = market_inputs()
S, K, T, r, q, vol, call = p["S"], p["K"], p["T"], p["r"], p["q"], p["vol"], p["call"]

with st.sidebar:
    st.subheader("Numerical settings")
    steps = st.select_slider("Tree steps", [25, 50, 100, 250, 500, 1000, 2000, 5000], value=500)
    paths = st.select_slider("MC paths", [10_000, 50_000, 100_000, 250_000, 1_000_000, 4_000_000], value=250_000)
    american = st.toggle("American exercise", value=False)
    seed = st.number_input("MC seed", 0, 10**6, 42)

bs = O.bs(S, K, T, r, q, vol, call)
rows = []


def add(name, out, secs, note=""):
    err = out["price"] - bs["price"] if not american else np.nan
    rows.append({"method": name, "price": out["price"], "error vs BS": err, "delta": out.get("delta"), "gamma": out.get("gamma"),
                 "vega (1 vol pt)": out.get("vega"), "theta (1 day)": out.get("theta"), "time": fmt_time(secs), "_t": secs, "note": note})


_, t_bs = timed(O.bs, S, K, T, r, q, vol, call, repeat=2000)
add("Black-Scholes (closed form)" + (" — European reference" if american else ""), bs, t_bs,
    f"vectorised: {bs_ns_per_option(200_000) * 1e9:.0f} ns/option")
for m, label in (("crr", "Binomial CRR"), ("jr", "Binomial Jarrow-Rudd"), ("lr", "Binomial Leisen-Reimer")):
    out, t = timed(O.binomial, S, K, T, r, q, vol, steps, call, american, m)
    add(f"{label} ({steps + (1 if m == 'lr' and steps % 2 == 0 else 0)} steps)", out, t, "Greeks from tree nodes")
if american:
    lsm, t = timed(O.lsm_american, S, K, T, r, q, vol, call, 50, min(paths, 400_000), int(seed))
    add(f"Longstaff-Schwartz MC ({min(paths, 400_000):,} paths, 50 dates)", lsm, t, f"± {1.96 * lsm['stderr']:.4f} (95%)")
else:
    for a, c, label in ((False, False, "plain"), (True, False, "antithetic"), (True, True, "antithetic + control variate")):
        out, t = timed(O.mc, S, K, T, r, q, vol, call, "european", paths, 1, a, c, 0.0, int(seed))
        add(f"Monte Carlo {label} ({paths:,})", out, t, f"± {1.96 * out['stderr']:.4f} (95%) · {out['threads']} threads")
    g, t = timed(mc_greeks, p, paths, seed=int(seed))
    add("MC Greeks: bump & revalue with common random numbers", g, t, "6 revaluations, same paths")

df = pd.DataFrame(rows)
st.dataframe(df.drop(columns="_t"), hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.6f") for c in
                            ["price", "error vs BS", "delta", "gamma", "vega (1 vol pt)", "theta (1 day)"]})

c = st.columns(4)
if american:
    euro = O.binomial(S, K, T, r, q, vol, 1001, call, False, "lr")["price"]
    am = O.binomial(S, K, T, r, q, vol, 1001, call, True, "lr")["price"]
    c[0].metric("American (LR 1001)", f"{am:.4f}")
    c[1].metric("European (LR 1001)", f"{euro:.4f}")
    c[2].metric("Early-exercise premium", f"{am - euro:.4f}", f"{(am / euro - 1) * 100:.2f}% of European", delta_color="off")
    c[3].caption("American calls on non-dividend stocks have zero premium: try q = 0 with a call.")
else:
    other = O.bs(S, K, T, r, q, vol, not call)["price"]
    c_, p_ = (bs["price"], other) if call else (other, bs["price"])
    parity = c_ - p_ - (S * np.exp(-q * T) - K * np.exp(-r * T))
    c[0].metric("Call", f"{c_:.4f}")
    c[1].metric("Put", f"{p_:.4f}")
    c[2].metric("Put-call parity residual", f"{parity:.2e}")
    c[3].metric("Rho (1%)", f"{bs['rho']:.4f}")

st.divider()
st.subheader("Implied volatility solver")
c1, c2, c3 = st.columns([1, 1, 2])
mkt = c1.number_input("Market price", 0.0001, 1e6, round(bs["price"] * 1.08, 4), format="%.4f")
iv = O.implied_vol(mkt, S, K, T, r, q, call)
c2.metric("Implied vol", f"{iv * 100:.3f}%" if np.isfinite(iv) else "no solution",
          f"{(iv - vol) * 100:+.2f} vol pts vs input" if np.isfinite(iv) else None)
c3.caption("Newton-Raphson on vega, safeguarded by bisection; returns no solution below intrinsic value or above the "
           "price at 500% vol. Below: a smile implied from prices generated with a skewed vol, to show the solver round-trips.")
strikes = np.linspace(S * 0.6, S * 1.4, 41)
true_vol = vol * (1 + 0.6 * (np.log(strikes / S)) ** 2 - 0.25 * np.log(strikes / S))
prices = O.bs_vec(S, strikes, T, r, q, true_vol, call)["price"]
ivs = np.array([O.implied_vol(pr, S, k, T, r, q, call) for pr, k in zip(prices, strikes)])
sm = pd.DataFrame({"strike": strikes, "input vol %": true_vol * 100, "recovered IV %": ivs * 100})
st.line_chart(sm, x="strike", y=["input vol %", "recovered IV %"], height=260)
st.caption(f"Max round-trip error: {np.nanmax(np.abs(ivs - true_vol)) * 100:.2e} vol pts across {len(strikes)} strikes.")
