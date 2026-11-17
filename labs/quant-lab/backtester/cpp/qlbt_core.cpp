// qlbt_core — C++ hot paths for the event-driven backtester.
//
//  * resample_ticks: tick quotes -> time bars (OHLC of mid, volume, spread, tick count)
//  * run_ma_cross:   tick-level simulation of an SMA-crossover strategy with the *same*
//                    event semantics, latency, cost and slippage model as the Python engine
//                    (qlbt.engine). Used to cross-validate the Python engine and to make
//                    parameter sweeps / walk-forward fast.
//  * sweep_ma_cross: the above over a (fast, slow) grid, multithreaded with std::thread.
//
// Event semantics (identical in Python):
//   bar k covers [k*bar, (k+1)*bar). When the first tick of a later bucket arrives, the bar is
//   closed at its last mid, equity is marked, the strategy decides a target, and an order is
//   (re)placed with activation time = bar_end + latency. Pending orders fill on the first tick
//   whose timestamp >= activation, crossing the spread, plus slippage + square-root impact.
//   A new decision replaces any pending order. Nothing ever sees a tick after the decision time.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <thread>
#include <vector>

namespace py = pybind11;
using i64 = std::int64_t;

struct CostParams {
    double size = 100;          // shares per unit signal
    bool long_only = false;
    i64 bar_ns = 300'000'000'000LL;
    i64 latency_ns = 0;
    double comm_per_share = 0.0;
    double comm_bps = 0.0;
    double min_comm = 0.0;
    double slip_bps = 0.0;
    double impact_bps_at_1pct = 0.0;  // impact (bps) for an order of 1% of ADV, scales with sqrt
    double adv = 1e6;
    double init_cash = 1e6;
};

struct SimOut {
    std::vector<i64> bar_end;
    std::vector<double> close, equity, gross_equity, position;
    int n_fills = 0;
    double traded_shares = 0, traded_notional = 0, commission = 0, spread_cost = 0, impact_cost = 0, delay_cost = 0;
};

static inline i64 floordiv_i64(i64 a, i64 b) { return (a >= 0) ? a / b : -((-a + b - 1) / b); }

static SimOut run_ma(const i64* ts, const double* bid, const double* ask, size_t n, int fast, int slow,
                     const CostParams& p, bool keep_series) {
    SimOut o;
    if (n == 0) return o;
    if (fast <= 0 || slow <= 0) throw std::invalid_argument("windows must be positive");
    std::vector<double> closes;
    closes.reserve(n / 8 + 16);
    double pos = 0, cash = p.init_cash;
    double ppos = 0, pcash = p.init_cash;  // paper (frictionless, fills at bar close mid)
    bool has_pending = false;
    double pend_qty = 0, pend_arrival = 0;
    i64 pend_active = 0;
    double target = 0;
    bool has_target = false;
    i64 bucket = floordiv_i64(ts[0], p.bar_ns);
    double last_mid = 0.5 * (bid[0] + ask[0]);

    auto close_bar = [&](i64 bar_end) {
        double c = last_mid;
        closes.push_back(c);
        double eq = cash + pos * c;
        double geq = pcash + ppos * c;
        if (keep_series) {
            o.bar_end.push_back(bar_end);
            o.close.push_back(c);
            o.equity.push_back(eq);
            o.gross_equity.push_back(geq);
            o.position.push_back(pos);
        } else {
            o.equity.push_back(eq);
            o.gross_equity.push_back(geq);
        }
        size_t k = closes.size();
        if ((int)k >= slow && (int)k >= fast) {
            double fs = 0, ss = 0;
            for (size_t j = k - fast; j < k; ++j) fs += closes[j];
            for (size_t j = k - slow; j < k; ++j) ss += closes[j];
            double f = fs / fast, s = ss / slow, tol = 1e-12 * std::fabs(s);  // near-ties = no signal
            if (f > s + tol) { target = p.size; has_target = true; }
            else if (f < s - tol) { target = p.long_only ? 0.0 : -p.size; has_target = true; }
        }
        if (has_target) {
            // paper portfolio trades instantly at the close mid
            pcash -= (target - ppos) * c;
            ppos = target;
            double q = target - pos;
            if (q != 0) {
                // keep a working order that already has the right size (don't reset its clock)
                if (!(has_pending && pend_qty == q)) {
                    has_pending = true;
                    pend_qty = q;
                    pend_active = bar_end + p.latency_ns;
                    pend_arrival = c;
                }
            } else {
                has_pending = false;
            }
        }
    };

    for (size_t i = 0; i < n; ++i) {
        i64 b = floordiv_i64(ts[i], p.bar_ns);
        if (b != bucket) {
            close_bar((bucket + 1) * p.bar_ns);
            bucket = b;
        }
        if (has_pending && ts[i] >= pend_active) {
            double sgn = pend_qty > 0 ? 1.0 : -1.0;
            double q = std::fabs(pend_qty);
            double quote = sgn > 0 ? ask[i] : bid[i];
            double mid = 0.5 * (bid[i] + ask[i]);
            double impact_bps = (p.adv > 0 && p.impact_bps_at_1pct > 0) ? p.impact_bps_at_1pct * std::sqrt(100.0 * q / p.adv) : 0.0;
            double px = quote * (1.0 + sgn * (p.slip_bps + impact_bps) / 1e4);
            double comm = std::max(p.min_comm, q * p.comm_per_share + px * q * p.comm_bps / 1e4);
            cash -= sgn * q * px + comm;
            pos += sgn * q;
            o.n_fills++;
            o.traded_shares += q;
            o.traded_notional += q * px;
            o.commission += comm;
            o.spread_cost += q * std::fabs(quote - mid);
            o.impact_cost += q * std::fabs(px - quote);
            o.delay_cost += sgn * q * (mid - pend_arrival);
            has_pending = false;
        }
        last_mid = 0.5 * (bid[i] + ask[i]);
    }
    close_bar((bucket + 1) * p.bar_ns);
    return o;
}

struct Metrics {
    double total_return, sharpe, max_dd, turnover, cost_bps;
    int fills;
    double gross_sharpe;
};

static Metrics metrics(const SimOut& o, double bars_per_year, double init_cash) {
    auto stats = [&](const std::vector<double>& e, double& sharpe, double& mdd) {
        double s = 0, s2 = 0;
        int m = 0;
        double peak = e.empty() ? 0 : e[0];
        mdd = 0;
        for (size_t i = 1; i < e.size(); ++i) {
            double r = e[i] / e[i - 1] - 1.0;
            s += r; s2 += r * r; ++m;
            peak = std::max(peak, e[i]);
            mdd = std::min(mdd, e[i] / peak - 1.0);
        }
        double mu = m ? s / m : 0, var = m > 1 ? (s2 - m * mu * mu) / (m - 1) : 0;
        sharpe = var > 0 ? mu / std::sqrt(var) * std::sqrt(bars_per_year) : 0;
    };
    Metrics r{};
    double gmdd;
    stats(o.equity, r.sharpe, r.max_dd);
    stats(o.gross_equity, r.gross_sharpe, gmdd);
    r.total_return = o.equity.empty() ? 0 : o.equity.back() / init_cash - 1.0;
    r.turnover = o.traded_notional / init_cash;
    double costs = o.commission + o.spread_cost + o.impact_cost;
    r.cost_bps = o.traded_notional > 0 ? costs / o.traded_notional * 1e4 : 0;
    r.fills = o.n_fills;
    return r;
}

static CostParams parse_params(const py::dict& d) {
    CostParams p;
    auto f = [&](const char* k, double& v) { if (d.contains(k)) v = d[k].cast<double>(); };
    f("size", p.size);
    f("comm_per_share", p.comm_per_share);
    f("comm_bps", p.comm_bps);
    f("min_comm", p.min_comm);
    f("slip_bps", p.slip_bps);
    f("impact_bps_at_1pct", p.impact_bps_at_1pct);
    f("adv", p.adv);
    f("init_cash", p.init_cash);
    if (d.contains("long_only")) p.long_only = d["long_only"].cast<bool>();
    if (d.contains("bar_ns")) p.bar_ns = d["bar_ns"].cast<i64>();
    if (d.contains("latency_ns")) p.latency_ns = d["latency_ns"].cast<i64>();
    if (p.bar_ns <= 0) throw std::invalid_argument("bar_ns must be positive");
    return p;
}

using arr_i = py::array_t<i64, py::array::c_style | py::array::forcecast>;
using arr_d = py::array_t<double, py::array::c_style | py::array::forcecast>;

static void check_len(const arr_i& ts, const arr_d& b, const arr_d& a) {
    if (ts.size() != b.size() || ts.size() != a.size()) throw std::invalid_argument("ts/bid/ask length mismatch");
}

py::dict py_run(arr_i ts, arr_d bid, arr_d ask, int fast, int slow, py::dict params) {
    check_len(ts, bid, ask);
    CostParams p = parse_params(params);
    SimOut o;
    {
        py::gil_scoped_release rel;
        o = run_ma(ts.data(), bid.data(), ask.data(), ts.size(), fast, slow, p, true);
    }
    py::dict r;
    r["bar_end"] = py::array_t<i64>(o.bar_end.size(), o.bar_end.data());
    r["close"] = py::array_t<double>(o.close.size(), o.close.data());
    r["equity"] = py::array_t<double>(o.equity.size(), o.equity.data());
    r["gross_equity"] = py::array_t<double>(o.gross_equity.size(), o.gross_equity.data());
    r["position"] = py::array_t<double>(o.position.size(), o.position.data());
    r["fills"] = o.n_fills;
    r["traded_shares"] = o.traded_shares;
    r["traded_notional"] = o.traded_notional;
    r["commission"] = o.commission;
    r["spread_cost"] = o.spread_cost;
    r["impact_cost"] = o.impact_cost;
    r["delay_cost"] = o.delay_cost;
    return r;
}

py::dict py_sweep(arr_i ts, arr_d bid, arr_d ask, std::vector<int> fasts, std::vector<int> slows, py::dict params,
                  double bars_per_year, int threads) {
    check_len(ts, bid, ask);
    CostParams p = parse_params(params);
    size_t nf = fasts.size(), ns = slows.size(), N = nf * ns;
    std::vector<Metrics> out(N);
    std::vector<char> valid(N, 0);
    const i64* t = ts.data();
    const double* b = bid.data();
    const double* a = ask.data();
    size_t n = ts.size();
    {
        py::gil_scoped_release rel;
        unsigned hw = std::max(1u, std::thread::hardware_concurrency());
        unsigned nt = threads > 0 ? (unsigned)threads : hw;
        nt = std::min<unsigned>(nt, (unsigned)std::max<size_t>(N, 1));
        std::atomic<size_t> next{0};
        auto work = [&]() {
            for (;;) {
                size_t k = next.fetch_add(1);
                if (k >= N) break;
                int f = fasts[k / ns], s = slows[k % ns];
                if (f >= s) continue;  // only fast < slow is meaningful
                SimOut o = run_ma(t, b, a, n, f, s, p, false);
                out[k] = metrics(o, bars_per_year, p.init_cash);
                valid[k] = 1;
            }
        };
        std::vector<std::thread> pool;
        for (unsigned i = 0; i < nt; ++i) pool.emplace_back(work);
        for (auto& th : pool) th.join();
    }
    auto mk = [&](auto getter) {
        py::array_t<double> m({(py::ssize_t)nf, (py::ssize_t)ns});
        auto r = m.mutable_unchecked<2>();
        for (size_t i = 0; i < nf; ++i)
            for (size_t j = 0; j < ns; ++j) r(i, j) = valid[i * ns + j] ? getter(out[i * ns + j]) : NAN;
        return m;
    };
    py::dict d;
    d["sharpe"] = mk([](const Metrics& m) { return m.sharpe; });
    d["gross_sharpe"] = mk([](const Metrics& m) { return m.gross_sharpe; });
    d["total_return"] = mk([](const Metrics& m) { return m.total_return; });
    d["max_dd"] = mk([](const Metrics& m) { return m.max_dd; });
    d["turnover"] = mk([](const Metrics& m) { return m.turnover; });
    d["cost_bps"] = mk([](const Metrics& m) { return m.cost_bps; });
    d["fills"] = mk([](const Metrics& m) { return (double)m.fills; });
    return d;
}

py::dict py_resample(arr_i ts, arr_d bid, arr_d ask, arr_d vol, i64 bar_ns) {
    check_len(ts, bid, ask);
    if (vol.size() != ts.size()) throw std::invalid_argument("vol length mismatch");
    if (bar_ns <= 0) throw std::invalid_argument("bar_ns must be positive");
    std::vector<i64> start;
    std::vector<double> o, h, l, c, v, spr, vwap;
    std::vector<i64> cnt;
    size_t n = ts.size();
    const i64* t = ts.data();
    const double* b = bid.data();
    const double* a = ask.data();
    const double* vv = vol.data();
    {
        py::gil_scoped_release rel;
        i64 cur = INT64_MIN;
        double pv = 0, sp = 0;
        for (size_t i = 0; i < n; ++i) {
            double m = 0.5 * (b[i] + a[i]);
            i64 k = floordiv_i64(t[i], bar_ns);
            if (k != cur) {
                if (cur != INT64_MIN) {
                    spr.back() = sp / cnt.back();
                    vwap.back() = v.back() > 0 ? pv / v.back() : c.back();
                }
                cur = k;
                start.push_back(k * bar_ns);
                o.push_back(m); h.push_back(m); l.push_back(m); c.push_back(m);
                v.push_back(0); cnt.push_back(0); spr.push_back(0); vwap.push_back(0);
                pv = 0; sp = 0;
            }
            h.back() = std::max(h.back(), m);
            l.back() = std::min(l.back(), m);
            c.back() = m;
            v.back() += vv[i];
            pv += vv[i] * m;
            sp += a[i] - b[i];
            cnt.back() += 1;
        }
        if (!cnt.empty()) {
            spr.back() = sp / cnt.back();
            vwap.back() = v.back() > 0 ? pv / v.back() : c.back();
        }
    }
    py::dict d;
    d["ts"] = py::array_t<i64>(start.size(), start.data());
    d["open"] = py::array_t<double>(o.size(), o.data());
    d["high"] = py::array_t<double>(h.size(), h.data());
    d["low"] = py::array_t<double>(l.size(), l.data());
    d["close"] = py::array_t<double>(c.size(), c.data());
    d["volume"] = py::array_t<double>(v.size(), v.data());
    d["vwap"] = py::array_t<double>(vwap.size(), vwap.data());
    d["avg_spread"] = py::array_t<double>(spr.size(), spr.data());
    d["ticks"] = py::array_t<i64>(cnt.size(), cnt.data());
    return d;
}

PYBIND11_MODULE(qlbt_core, m) {
    m.doc() = "C++ kernels for the qlbt event-driven backtester";
    m.def("run_ma_cross", &py_run, py::arg("ts"), py::arg("bid"), py::arg("ask"), py::arg("fast"), py::arg("slow"),
          py::arg("params"));
    m.def("sweep_ma_cross", &py_sweep, py::arg("ts"), py::arg("bid"), py::arg("ask"), py::arg("fasts"), py::arg("slows"),
          py::arg("params"), py::arg("bars_per_year"), py::arg("threads") = 0);
    m.def("resample_ticks", &py_resample, py::arg("ts"), py::arg("bid"), py::arg("ask"), py::arg("volume"),
          py::arg("bar_ns"));
    m.attr("hardware_threads") = std::thread::hardware_concurrency();
}
