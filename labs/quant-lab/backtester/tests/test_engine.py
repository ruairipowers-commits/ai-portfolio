import numpy as np
import pandas as pd
import pytest

from qlbt import Backtest, ExecConfig, LeakyStrategy, MACross, resample, run_kernel, synthetic_ticks
from qlbt.data import resample_pandas


@pytest.fixture(scope="module")
def ticks():
    return synthetic_ticks(days=8, ticks_per_day=3000, seed=3)


@pytest.mark.parametrize("cfg", [
    ExecConfig(),
    ExecConfig(latency_ms=250, slip_bps=1.0, impact_bps_at_1pct=25),
    ExecConfig(bar="1min", latency_ms=90_000),          # latency longer than a bar
    ExecConfig(bar="15min", size=3_000, comm_bps=1.0),
])
@pytest.mark.parametrize("long_only", [False, True])
def test_python_engine_matches_cpp_kernel(ticks, cfg, long_only):
    r = Backtest(ticks, MACross(5, 20, long_only), cfg).run()
    k = run_kernel(ticks, 5, 20, cfg, long_only)
    assert len(r.bars) == len(k["equity"])
    np.testing.assert_allclose(r.bars.equity.values, k["equity"], rtol=0, atol=1e-6)
    np.testing.assert_allclose(r.bars.gross_equity.values, k["gross_equity"], rtol=0, atol=1e-6)
    assert len(r.fills) == k["fills"]


def test_fills_never_precede_decisions(ticks):
    r = Backtest(ticks, MACross(5, 20), ExecConfig(latency_ms=500)).run()
    assert (r.fills.ts >= r.fills.decision_ts + pd.Timedelta(milliseconds=500)).all()


def test_lookahead_guard(ticks):
    r = Backtest(ticks.iloc[:5000], LeakyStrategy(), ExecConfig()).run()
    assert r.errors and r.fills.empty


def test_same_bar_close_is_flagged_as_biased(ticks):
    r = Backtest(ticks, MACross(5, 20), ExecConfig(fill_mode="same_bar_close")).run()
    assert (r.fills.otype == "close (biased)").all()


def test_cpp_resample_matches_pandas(ticks):
    a, b = resample(ticks, "5min"), resample_pandas(ticks, "5min")
    assert len(a) == len(b)
    for c in ["open", "high", "low", "close", "volume", "ticks"]:
        np.testing.assert_allclose(a[c].values, b[c].values, rtol=1e-12)


def test_costs_reduce_pnl(ticks):
    free = Backtest(ticks, MACross(5, 20), ExecConfig().scaled_costs(0)).run()
    paid = Backtest(ticks, MACross(5, 20), ExecConfig().scaled_costs(3)).run()
    assert paid.bars.equity.iloc[-1] < free.bars.equity.iloc[-1]
