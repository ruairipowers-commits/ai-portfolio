import math

import numpy as np
import pytest

import optlib as O

P = dict(S=100.0, K=105.0, T=0.75, r=0.04, q=0.01, vol=0.25)


def bsp(call=True, **kw):
    p = {**P, **kw}
    return O.bs(p["S"], p["K"], p["T"], p["r"], p["q"], p["vol"], call)


def test_put_call_parity():
    c, p = bsp(True)["price"], bsp(False)["price"]
    assert abs(c - p - (P["S"] * math.exp(-P["q"] * P["T"]) - P["K"] * math.exp(-P["r"] * P["T"]))) < 1e-12


def test_greeks_match_finite_differences():
    g, h = bsp(), 1e-4
    up, dn = bsp(S=P["S"] + h)["price"], bsp(S=P["S"] - h)["price"]
    assert abs((up - dn) / (2 * h) - g["delta"]) < 1e-6
    assert abs((up - 2 * g["price"] + dn) / h ** 2 - g["gamma"]) < 1e-4
    assert abs((bsp(vol=P["vol"] + 1e-4)["price"] - bsp(vol=P["vol"] - 1e-4)["price"]) / 2e-4 / 100 - g["vega"]) < 1e-6


def test_vectorised_matches_scalar():
    S = np.linspace(60, 140, 50)
    v = O.bs_vec(S, P["K"], P["T"], P["r"], P["q"], P["vol"], False)
    for i in (0, 25, 49):
        s = O.bs(S[i], P["K"], P["T"], P["r"], P["q"], P["vol"], False)
        assert abs(v["price"][i] - s["price"]) < 1e-12 and abs(v["theta"][i] - s["theta"]) < 1e-12


@pytest.mark.parametrize("call", [True, False])
def test_implied_vol_round_trip(call):
    for vol in (0.05, 0.2, 0.8, 2.0):
        px = bsp(call, vol=vol)["price"]
        assert abs(O.implied_vol(px, P["S"], P["K"], P["T"], P["r"], P["q"], call) - vol) < 1e-8


def test_binomial_convergence_orders():
    exact = bsp()["price"]
    lr = O.binomial(*P.values(), 401, True, False, "lr")["price"]
    crr = O.binomial(*P.values(), 400, True, False, "crr")["price"]
    assert abs(lr - exact) < 1e-5 and abs(crr - exact) < 1e-2


def test_american_put_premium_and_call_without_dividends():
    am = O.binomial(*P.values(), 801, False, True, "lr")["price"]
    eu = O.binomial(*P.values(), 801, False, False, "lr")["price"]
    assert am > eu
    p0 = {**P, "q": 0.0}
    assert abs(O.binomial(*p0.values(), 801, True, True, "lr")["price"] - O.bs(*p0.values(), True)["price"]) < 1e-4


def test_mc_confidence_interval_and_determinism():
    exact = bsp()["price"]
    a = O.mc(*P.values(), True, "european", 400_000, 1, True, True, 0.0, 5, 1)
    b = O.mc(*P.values(), True, "european", 400_000, 1, True, True, 0.0, 5, 0)
    assert a["price"] == b["price"]                       # thread count does not change the answer
    assert abs(a["price"] - exact) < 4 * a["stderr"]


def test_variance_reduction_helps():
    plain = O.mc(*P.values(), True, "asian", 100_000, 24, False, False)
    cv = O.mc(*P.values(), True, "asian", 100_000, 24, True, True)
    assert cv["stderr"] < plain["stderr"] / 10
    assert abs(cv["price"] - plain["price"]) < 4 * plain["stderr"]


def test_barrier_closed_form_vs_monte_carlo():
    H, n = 130.0, 500
    mc = O.mc(*P.values(), True, "barrier_uo", 400_000, n, True, True, H, 9)
    bgk = O.up_and_out_call(P["S"], P["K"], H * math.exp(0.5826 * P["vol"] * math.sqrt(P["T"] / n)), P["T"], P["r"], P["q"], P["vol"])
    assert abs(mc["price"] - bgk) < 4 * mc["stderr"] + 0.01
    assert O.up_and_out_call(P["S"], P["K"], H, P["T"], P["r"], P["q"], P["vol"]) < bsp()["price"]


def test_lsm_close_to_tree():
    tree = O.binomial(*P.values(), 1001, False, True, "lr")["price"]
    lsm = O.lsm_american(*P.values(), False, 50, 200_000, 3)
    assert abs(lsm["price"] - tree) < 4 * lsm["stderr"] + 0.04
