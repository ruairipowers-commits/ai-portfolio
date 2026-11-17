from __future__ import annotations

import time

import numpy as np
import streamlit as st

import optlib as O

BLUE, RED, GREEN, GREY, ORANGE, PURPLE = "#4575b4", "#d73027", "#1a9850", "#8c8c8c", "#f46d43", "#762a83"


def market_inputs(show_type: bool = True):
    """Shared sidebar inputs (widget keys persist across pages)."""
    with st.sidebar:
        st.subheader("Market & contract")
        c1, c2 = st.columns(2)
        S = c1.number_input("Spot", 0.01, 1e6, 100.0, step=1.0, key="S")
        K = c2.number_input("Strike", 0.01, 1e6, 100.0, step=1.0, key="K")
        days = c1.number_input("Days to expiry", 1, 3650, 365, key="days")
        vol = c2.number_input("Vol %", 1.0, 300.0, 20.0, step=1.0, key="vol") / 100
        r = c1.number_input("Rate %", -5.0, 30.0, 5.0, step=0.25, key="r") / 100
        q = c2.number_input("Div yield %", 0.0, 30.0, 2.0, step=0.25, key="q") / 100
        call = True
        if show_type:
            call = st.radio("Type", ["Call", "Put"], horizontal=True, key="cp") == "Call"
    return dict(S=S, K=K, T=days / 365.0, r=r, q=q, vol=vol, call=call)


def timed(fn, *a, repeat: int = 1, **kw):
    t0 = time.perf_counter()
    for _ in range(repeat):
        out = fn(*a, **kw)
    return out, (time.perf_counter() - t0) / repeat


def mc_greeks(p, paths, payoff="european", steps=1, antithetic=True, control=True, barrier=0.0, seed=42, rel_bump=0.01):
    """Bump-and-revalue Greeks with common random numbers (the C++ engine seeds paths by block,
    so the same seed reproduces the same paths)."""
    def price(S=p["S"], vol=p["vol"], T=p["T"]):
        return O.mc(S, p["K"], T, p["r"], p["q"], vol, p["call"], payoff, paths, steps, antithetic, control, barrier, seed)["price"]
    h = p["S"] * rel_bump
    up, mid, dn = price(S=p["S"] + h), price(), price(S=p["S"] - h)
    dv = 0.01
    vu, vd = price(vol=p["vol"] + dv), price(vol=max(1e-4, p["vol"] - dv))
    dt = 1 / 365
    th = price(T=max(p["T"] - dt, 1e-6)) - mid
    return dict(price=mid, delta=(up - dn) / (2 * h), gamma=(up - 2 * mid + dn) / h ** 2, vega=(vu - vd) / 2, theta=th)


def fmt_time(s: float) -> str:
    if s < 1e-6:
        return f"{s * 1e9:.0f} ns"
    if s < 1e-3:
        return f"{s * 1e6:.1f} µs"
    if s < 1:
        return f"{s * 1e3:.1f} ms"
    return f"{s:.2f} s"


def bs_ns_per_option(n: int = 1_000_000) -> float:
    S = np.random.default_rng(0).uniform(50, 150, n)
    _, t = timed(O.bs_vec, S, 100.0, 1.0, 0.05, 0.0, 0.2, True)
    return t / n
