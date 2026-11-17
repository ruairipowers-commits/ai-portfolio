// optlib — options pricing & Greeks engine.
//
//  Analytic : Black-Scholes-Merton price + Greeks (scalar and vectorised), implied vol,
//             discrete geometric Asian, continuous up-and-out call (Reiner-Rubinstein).
//  Lattice  : CRR and Leisen-Reimer binomial trees, European/American, tree Greeks,
//             early-exercise boundary.
//  Monte Carlo (multithreaded, std::thread):
//             European / arithmetic Asian / discretely monitored up-and-out barrier with
//             antithetic variates and control variates; Longstaff-Schwartz for American options.
//             Paths are generated in fixed-size blocks seeded by (seed, block id), so results are
//             bit-identical for any thread count, and re-running with the same seed gives
//             common random numbers for bump-and-revalue Greeks.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace py = pybind11;
using u64 = std::uint64_t;
static constexpr double SQRT2 = 1.4142135623730951;
static constexpr double INV_SQRT_2PI = 0.3989422804014327;

static inline double ncdf(double x) { return 0.5 * std::erfc(-x / SQRT2); }
static inline double npdf(double x) { return INV_SQRT_2PI * std::exp(-0.5 * x * x); }

// ============================================================================ Black-Scholes
struct Greeks {
    double price, delta, gamma, vega, theta, rho;
};

static Greeks bs(double S, double K, double T, double r, double q, double v, bool call) {
    if (T <= 0 || v <= 0) {
        double intr = call ? std::max(S - K, 0.0) : std::max(K - S, 0.0);
        double d = call ? (S > K ? 1.0 : 0.0) : (S < K ? -1.0 : 0.0);
        return {intr, d, 0, 0, 0, 0};
    }
    double sq = std::sqrt(T), vs = v * sq;
    double d1 = (std::log(S / K) + (r - q + 0.5 * v * v) * T) / vs, d2 = d1 - vs;
    double dq = std::exp(-q * T), dr = std::exp(-r * T);
    double pdf = npdf(d1);
    Greeks g{};
    if (call) {
        g.price = S * dq * ncdf(d1) - K * dr * ncdf(d2);
        g.delta = dq * ncdf(d1);
        g.theta = -S * dq * pdf * v / (2 * sq) - r * K * dr * ncdf(d2) + q * S * dq * ncdf(d1);
        g.rho = K * T * dr * ncdf(d2);
    } else {
        g.price = K * dr * ncdf(-d2) - S * dq * ncdf(-d1);
        g.delta = -dq * ncdf(-d1);
        g.theta = -S * dq * pdf * v / (2 * sq) + r * K * dr * ncdf(-d2) - q * S * dq * ncdf(-d1);
        g.rho = -K * T * dr * ncdf(-d2);
    }
    g.gamma = dq * pdf / (S * vs);
    g.vega = S * dq * pdf * sq;
    return g;
}

static double implied_vol(double price, double S, double K, double T, double r, double q, bool call) {
    double lo = 1e-6, hi = 5.0;
    double intr = call ? std::max(S * std::exp(-q * T) - K * std::exp(-r * T), 0.0)
                       : std::max(K * std::exp(-r * T) - S * std::exp(-q * T), 0.0);
    if (price <= intr + 1e-12 || price >= bs(S, K, T, r, q, hi, call).price) return NAN;
    double v = 0.2;
    for (int i = 0; i < 100; ++i) {
        Greeks g = bs(S, K, T, r, q, v, call);
        double diff = g.price - price;
        if (std::fabs(diff) < 1e-12) return v;
        if (diff > 0) hi = v; else lo = v;
        double nv = g.vega > 1e-10 ? v - diff / g.vega : 0.5 * (lo + hi);
        v = (nv > lo && nv < hi) ? nv : 0.5 * (lo + hi);  // Newton, safeguarded by bisection
    }
    return v;
}

// Discretely monitored geometric-average Asian call/put (fixings at T/n, 2T/n, ..., T).
static double geo_asian(double S, double K, double T, double r, double q, double v, int n, bool call) {
    double mu = std::log(S) + (r - q - 0.5 * v * v) * T * (n + 1.0) / (2.0 * n);
    double s2 = v * v * T * (n + 1.0) * (2.0 * n + 1.0) / (6.0 * n * n);
    double s = std::sqrt(s2);
    double d1 = (mu - std::log(K) + s2) / s, d2 = d1 - s;
    double fwdG = std::exp(mu + 0.5 * s2), dr = std::exp(-r * T);
    return call ? dr * (fwdG * ncdf(d1) - K * ncdf(d2)) : dr * (K * ncdf(-d2) - fwdG * ncdf(-d1));
}

// Continuously monitored up-and-out call, K < H, no rebate (Reiner & Rubinstein / Haug A - B + C - D).
static double uo_call(double S, double K, double H, double T, double r, double q, double v) {
    if (S >= H) return 0.0;
    if (K >= H) return 0.0;
    double b = r - q, vs = v * std::sqrt(T);
    double mu = (b - 0.5 * v * v) / (v * v);
    double x1 = std::log(S / K) / vs + (1 + mu) * vs;
    double x2 = std::log(S / H) / vs + (1 + mu) * vs;
    double y1 = std::log(H * H / (S * K)) / vs + (1 + mu) * vs;
    double y2 = std::log(H / S) / vs + (1 + mu) * vs;
    double e1 = S * std::exp((b - r) * T), e2 = K * std::exp(-r * T);
    double hs1 = std::pow(H / S, 2 * (mu + 1)), hs2 = std::pow(H / S, 2 * mu);
    double A = e1 * ncdf(x1) - e2 * ncdf(x1 - vs);
    double B = e1 * ncdf(x2) - e2 * ncdf(x2 - vs);
    double C = e1 * hs1 * ncdf(-y1) - e2 * hs2 * ncdf(-y1 + vs);
    double D = e1 * hs1 * ncdf(-y2) - e2 * hs2 * ncdf(-y2 + vs);
    return std::max(A - B + C - D, 0.0);
}

// ============================================================================ binomial trees
struct TreeOut {
    double price, delta, gamma, theta;
    std::vector<double> bt, bS;  // early-exercise boundary (time, stock price)
};

static double pp_inversion(double z, int n) {  // Peizer-Pratt method 2
    double t = z / (n + 1.0 / 3.0 + 0.1 / (n + 1.0));
    double s = std::sqrt(0.25 - 0.25 * std::exp(-t * t * (n + 1.0 / 6.0)));
    return z >= 0 ? 0.5 + s : 0.5 - s;
}

static TreeOut binomial(double S, double K, double T, double r, double q, double v, int n, bool call, bool american,
                        const std::string& method, bool boundary) {
    if (n < 2) throw std::invalid_argument("steps must be >= 2");
    double dt = T / n, growth = std::exp((r - q) * dt), disc = std::exp(-r * dt);
    double u, d, p;
    if (method == "lr") {
        if (n % 2 == 0) n += 1;  // LR needs odd steps
        dt = T / n; growth = std::exp((r - q) * dt); disc = std::exp(-r * dt);
        double vs = v * std::sqrt(T);
        double d1 = (std::log(S / K) + (r - q + 0.5 * v * v) * T) / vs, d2 = d1 - vs;
        p = pp_inversion(d2, n);
        double pp = pp_inversion(d1, n);
        u = growth * pp / p;
        d = (growth - p * u) / (1 - p);
    } else if (method == "jr") {  // Jarrow-Rudd (equal probability)
        u = std::exp((r - q - 0.5 * v * v) * dt + v * std::sqrt(dt));
        d = std::exp((r - q - 0.5 * v * v) * dt - v * std::sqrt(dt));
        p = (growth - d) / (u - d);
    } else {  // CRR
        u = std::exp(v * std::sqrt(dt));
        d = 1 / u;
        p = (growth - d) / (u - d);
    }
    if (!(p > 0 && p < 1)) throw std::invalid_argument("arbitrage in tree (p outside (0,1)); increase steps");
    std::vector<double> V(n + 1), St(n + 1);
    for (int j = 0; j <= n; ++j) {
        St[j] = S * std::exp(j * std::log(u) + (n - j) * std::log(d));
        V[j] = call ? std::max(St[j] - K, 0.0) : std::max(K - St[j], 0.0);
    }
    TreeOut o{};
    double v1[2] = {0, 0}, v2[3] = {0, 0, 0}, s1[2] = {0, 0}, s2[3] = {0, 0, 0};
    for (int i = n - 1; i >= 0; --i) {
        double bnd = NAN;
        double sj = S * std::pow(d, i), ud = u / d;
        for (int j = 0; j <= i; ++j, sj *= ud) {
            double cont = disc * (p * V[j + 1] + (1 - p) * V[j]);
            double ex = call ? sj - K : K - sj;
            if (american && ex > cont && ex > 0) {
                V[j] = ex;
                if (boundary) bnd = call ? (std::isnan(bnd) ? sj : std::min(bnd, sj)) : (std::isnan(bnd) ? sj : std::max(bnd, sj));
            } else {
                V[j] = cont;
            }
            if (i == 2) { v2[j] = V[j]; s2[j] = sj; }
            if (i == 1) { v1[j] = V[j]; s1[j] = sj; }
        }
        if (boundary && american) { o.bt.push_back(i * dt); o.bS.push_back(bnd); }
    }
    o.price = V[0];
    o.delta = (v1[1] - v1[0]) / (s1[1] - s1[0]);
    double dU = (v2[2] - v2[1]) / (s2[2] - s2[1]), dD = (v2[1] - v2[0]) / (s2[1] - s2[0]);
    o.gamma = (dU - dD) / (0.5 * (s2[2] - s2[0]));
    o.theta = (v2[1] - o.price) / (2 * dt);
    std::reverse(o.bt.begin(), o.bt.end());
    std::reverse(o.bS.begin(), o.bS.end());
    return o;
}

// ============================================================================ Monte Carlo
struct Xoshiro {
    u64 s[4];
    static u64 splitmix(u64& x) {
        u64 z = (x += 0x9E3779B97F4A7C15ULL);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
        return z ^ (z >> 31);
    }
    explicit Xoshiro(u64 seed) { for (auto& v : s) v = splitmix(seed); }
    static inline u64 rotl(u64 x, int k) { return (x << k) | (x >> (64 - k)); }
    inline u64 next() {
        u64 r = rotl(s[1] * 5, 7) * 9, t = s[1] << 17;
        s[2] ^= s[0]; s[3] ^= s[1]; s[1] ^= s[2]; s[0] ^= s[3]; s[2] ^= t; s[3] = rotl(s[3], 45);
        return r;
    }
    inline double uni() { return ((next() >> 11) + 0.5) * (1.0 / 9007199254740992.0); }
    bool has = false;
    double spare = 0;
    inline double normal() {  // Marsaglia polar
        if (has) { has = false; return spare; }
        double a, b, s2;
        do { a = 2 * uni() - 1; b = 2 * uni() - 1; s2 = a * a + b * b; } while (s2 >= 1 || s2 == 0);
        double m = std::sqrt(-2 * std::log(s2) / s2);
        spare = b * m; has = true;
        return a * m;
    }
};

enum class Payoff { European, Asian, BarrierUO };

struct MCConfig {
    double S, K, T, r, q, v, H = 0;
    bool call = true;
    Payoff payoff = Payoff::European;
    int steps = 1;
    long paths = 100000;
    bool antithetic = false, control = false;
    u64 seed = 42;
    int threads = 0;
};

struct Acc { double n = 0, y = 0, yy = 0, x = 0, xx = 0, xy = 0; };

static constexpr long BLOCK = 8192;

template <class F>
static void parallel_blocks(long nblocks, int threads, F&& fn) {
    unsigned hw = std::max(1u, std::thread::hardware_concurrency());
    unsigned nt = threads > 0 ? (unsigned)threads : hw;
    nt = (unsigned)std::max<long>(1, std::min<long>(nt, nblocks));
    std::atomic<long> next{0};
    auto work = [&]() { for (long b; (b = next.fetch_add(1)) < nblocks;) fn(b); };
    std::vector<std::thread> pool;
    for (unsigned i = 1; i < nt; ++i) pool.emplace_back(work);
    work();
    for (auto& t : pool) t.join();
}

struct MCOut { double price, stderr_, plain_stderr, beta, control_mean; long samples; double secs; int threads; };

static MCOut mc_price(const MCConfig& c) {
    auto t0 = std::chrono::steady_clock::now();
    int steps = c.payoff == Payoff::European ? 1 : std::max(1, c.steps);
    double dt = c.T / steps, drift = (c.r - c.q - 0.5 * c.v * c.v) * dt, vol = c.v * std::sqrt(dt);
    double disc = std::exp(-c.r * c.T);
    long n_samples = c.antithetic ? (c.paths + 1) / 2 : c.paths;
    long nblocks = (n_samples + BLOCK - 1) / BLOCK;
    std::vector<Acc> acc(nblocks);
    // control variates with known means:
    //   European -> discounted terminal stock (mean S e^{-qT}); Barrier -> vanilla payoff (BS price);
    //   Asian -> geometric-average payoff (closed form).
    double cmean = c.payoff == Payoff::Asian      ? geo_asian(c.S, c.K, c.T, c.r, c.q, c.v, steps, c.call)
                   : c.payoff == Payoff::European ? c.S * std::exp(-c.q * c.T)
                                                  : bs(c.S, c.K, c.T, c.r, c.q, c.v, c.call).price;
    double logS0 = std::log(c.S), logH = c.H > 0 ? std::log(c.H) : INFINITY;
    auto payoff_of = [&](const double* z, double sign, double& ctrl) {
        double ls = logS0, sum = 0, lsum = 0;
        bool alive = true;
        for (int k = 0; k < steps; ++k) {
            ls += drift + vol * sign * z[k];
            if (c.payoff == Payoff::Asian) { sum += std::exp(ls); lsum += ls; }
            else if (c.payoff == Payoff::BarrierUO && ls >= logH) alive = false;
        }
        double ST = std::exp(ls);
        double van = c.call ? std::max(ST - c.K, 0.0) : std::max(c.K - ST, 0.0);
        if (c.payoff == Payoff::Asian) {
            double A = sum / steps, G = std::exp(lsum / steps);
            ctrl = disc * (c.call ? std::max(G - c.K, 0.0) : std::max(c.K - G, 0.0));
            return disc * (c.call ? std::max(A - c.K, 0.0) : std::max(c.K - A, 0.0));
        }
        if (c.payoff == Payoff::BarrierUO) { ctrl = disc * van; return alive ? disc * van : 0.0; }
        ctrl = disc * ST;
        return disc * van;
    };
    parallel_blocks(nblocks, c.threads, [&](long b) {
        Xoshiro rng(c.seed * 0x100000001B3ULL + (u64)b * 0x9E3779B97F4A7C15ULL + 1);
        long lo = b * BLOCK, hi = std::min(n_samples, lo + BLOCK);
        std::vector<double> z(steps);
        Acc a;
        for (long i = lo; i < hi; ++i) {
            for (int k = 0; k < steps; ++k) z[k] = rng.normal();
            double x1, y = payoff_of(z.data(), 1.0, x1), x = x1;
            if (c.antithetic) {
                double x2, y2 = payoff_of(z.data(), -1.0, x2);
                y = 0.5 * (y + y2); x = 0.5 * (x1 + x2);
            }
            a.n += 1; a.y += y; a.yy += y * y; a.x += x; a.xx += x * x; a.xy += x * y;
        }
        acc[b] = a;
    });
    Acc t;
    for (auto& a : acc) { t.n += a.n; t.y += a.y; t.yy += a.yy; t.x += a.x; t.xx += a.xx; t.xy += a.xy; }
    double n = t.n, my = t.y / n, mx = t.x / n;
    double vy = (t.yy - n * my * my) / (n - 1), vx = (t.xx - n * mx * mx) / (n - 1), cxy = (t.xy - n * mx * my) / (n - 1);
    MCOut o{};
    o.plain_stderr = std::sqrt(std::max(vy, 0.0) / n);
    if (c.control && vx > 0) {
        double beta = cxy / vx;
        o.beta = beta;
        o.price = my - beta * (mx - cmean);
        double vcv = vy - 2 * beta * cxy + beta * beta * vx;
        o.stderr_ = std::sqrt(std::max(vcv, 0.0) / n);
    } else {
        o.price = my;
        o.stderr_ = o.plain_stderr;
    }
    o.control_mean = cmean;
    o.samples = (long)n;
    o.secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    unsigned hw = std::max(1u, std::thread::hardware_concurrency());
    o.threads = c.threads > 0 ? c.threads : (int)hw;
    return o;
}

// Longstaff-Schwartz least-squares Monte Carlo for American options (basis 1, x, x^2, x = S/K).
struct LSMOut { double price, stderr_, european, secs; std::vector<double> bt, bS; };

static LSMOut lsm(double S, double K, double T, double r, double q, double v, bool call, int steps, long paths, u64 seed,
                  int threads) {
    auto t0 = std::chrono::steady_clock::now();
    double dt = T / steps, drift = (r - q - 0.5 * v * v) * dt, vol = v * std::sqrt(dt), disc = std::exp(-r * dt);
    long N = paths;
    std::vector<double> P((size_t)N * steps);  // P[i*steps + k] = S at step k+1
    long nblocks = (N + BLOCK - 1) / BLOCK;
    parallel_blocks(nblocks, threads, [&](long b) {
        Xoshiro rng(seed * 0x100000001B3ULL + (u64)b * 0x9E3779B97F4A7C15ULL + 7);
        long lo = b * BLOCK, hi = std::min(N, lo + BLOCK);
        for (long i = lo; i < hi; i += 2) {  // antithetic pairs
            double l1 = std::log(S), l2 = l1;
            for (int k = 0; k < steps; ++k) {
                double z = rng.normal();
                l1 += drift + vol * z; l2 += drift - vol * z;
                P[(size_t)i * steps + k] = std::exp(l1);
                if (i + 1 < hi) P[(size_t)(i + 1) * steps + k] = std::exp(l2);
            }
        }
    });
    auto intr = [&](double s) { return call ? std::max(s - K, 0.0) : std::max(K - s, 0.0); };
    std::vector<double> cf(N);
    std::vector<int> tau(N, steps);
    double euro = 0;
    for (long i = 0; i < N; ++i) { cf[i] = intr(P[(size_t)i * steps + steps - 1]); euro += cf[i]; }
    euro = euro / N * std::exp(-r * T);
    LSMOut o{};
    for (int k = steps - 1; k >= 1; --k) {
        double m[3][3] = {{0}}, rhs[3] = {0};
        for (long i = 0; i < N; ++i) {
            double s = P[(size_t)i * steps + k - 1];
            if (intr(s) <= 0) continue;
            double x = s / K, bx[3] = {1, x, x * x};
            double y = cf[i] * std::pow(disc, tau[i] - k);
            for (int a = 0; a < 3; ++a) { rhs[a] += bx[a] * y; for (int bb = 0; bb < 3; ++bb) m[a][bb] += bx[a] * bx[bb]; }
        }
        // solve 3x3 by Gaussian elimination with partial pivoting
        double A[3][4];
        for (int a = 0; a < 3; ++a) { for (int bb = 0; bb < 3; ++bb) A[a][bb] = m[a][bb]; A[a][3] = rhs[a]; }
        bool ok = m[0][0] > 3;
        for (int col = 0; col < 3 && ok; ++col) {
            int piv = col;
            for (int rr = col + 1; rr < 3; ++rr) if (std::fabs(A[rr][col]) > std::fabs(A[piv][col])) piv = rr;
            if (std::fabs(A[piv][col]) < 1e-14) { ok = false; break; }
            for (int cc = 0; cc < 4; ++cc) std::swap(A[col][cc], A[piv][cc]);
            for (int rr = 0; rr < 3; ++rr) if (rr != col) {
                double f = A[rr][col] / A[col][col];
                for (int cc = col; cc < 4; ++cc) A[rr][cc] -= f * A[col][cc];
            }
        }
        double beta[3] = {0, 0, 0};
        if (ok) for (int a = 0; a < 3; ++a) beta[a] = A[a][3] / A[a][a];
        double bnd = NAN;
        for (long i = 0; i < N && ok; ++i) {
            double s = P[(size_t)i * steps + k - 1], ex = intr(s);
            if (ex <= 0) continue;
            double x = s / K, cont = beta[0] + beta[1] * x + beta[2] * x * x;
            // Continuation is worth at least the European option on the remaining life: using that
            // lower bound stops noisy regressions from triggering premature exercise.
            if (ex > cont) cont = std::max(cont, bs(s, K, T - k * dt, r, q, v, call).price);
            if (ex > cont) {
                cf[i] = ex; tau[i] = k;
                bnd = call ? (std::isnan(bnd) ? s : std::min(bnd, s)) : (std::isnan(bnd) ? s : std::max(bnd, s));
            }
        }
        o.bt.push_back(k * dt); o.bS.push_back(bnd);
    }
    double sum = 0, sum2 = 0;
    for (long i = 0; i < N; ++i) { double pv = cf[i] * std::pow(disc, tau[i]); sum += pv; sum2 += pv * pv; }
    double mean = sum / N;
    o.price = std::max(mean, intr(S));
    o.stderr_ = std::sqrt(std::max(sum2 / N - mean * mean, 0.0) / N);
    o.european = euro;
    std::reverse(o.bt.begin(), o.bt.end()); std::reverse(o.bS.begin(), o.bS.end());
    o.secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    return o;
}

// sample paths for plotting
static py::array_t<double> sample_paths(double S, double T, double r, double q, double v, int steps, int n, u64 seed) {
    py::array_t<double> out({n, steps + 1});
    auto a = out.mutable_unchecked<2>();
    Xoshiro rng(seed);
    double dt = T / steps, drift = (r - q - 0.5 * v * v) * dt, vol = v * std::sqrt(dt);
    for (int i = 0; i < n; ++i) {
        double l = std::log(S);
        a(i, 0) = S;
        for (int k = 1; k <= steps; ++k) { l += drift + vol * rng.normal(); a(i, k) = std::exp(l); }
    }
    return out;
}

// ============================================================================ bindings
static py::dict greeks_dict(const Greeks& g) {
    py::dict d;
    d["price"] = g.price; d["delta"] = g.delta; d["gamma"] = g.gamma;
    d["vega"] = g.vega / 100.0;    // per 1 vol point
    d["theta"] = g.theta / 365.0;  // per calendar day
    d["rho"] = g.rho / 100.0;      // per 1% rate
    return d;
}

static Payoff parse_payoff(const std::string& s) {
    if (s == "european") return Payoff::European;
    if (s == "asian") return Payoff::Asian;
    if (s == "barrier_uo") return Payoff::BarrierUO;
    throw std::invalid_argument("payoff must be european | asian | barrier_uo");
}

PYBIND11_MODULE(_optlib, m) {
    m.doc() = "Options pricing & Greeks: Black-Scholes, binomial trees, multithreaded Monte Carlo";

    m.def("bs", [](double S, double K, double T, double r, double q, double v, bool call) {
        return greeks_dict(bs(S, K, T, r, q, v, call));
    }, py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"), py::arg("q"), py::arg("vol"), py::arg("call") = true);

    m.def("bs_vec", [](py::array_t<double, py::array::forcecast> S, py::array_t<double, py::array::forcecast> K,
                       py::array_t<double, py::array::forcecast> T, double r, double q,
                       py::array_t<double, py::array::forcecast> v, py::array_t<bool, py::array::forcecast> call) {
        auto b = py::module_::import("numpy").attr("broadcast_arrays")(S, K, T, v, call);
        auto Sa = b.cast<py::tuple>()[0].cast<py::array_t<double, py::array::forcecast | py::array::c_style>>();
        auto Ka = b.cast<py::tuple>()[1].cast<py::array_t<double, py::array::forcecast | py::array::c_style>>();
        auto Ta = b.cast<py::tuple>()[2].cast<py::array_t<double, py::array::forcecast | py::array::c_style>>();
        auto Va = b.cast<py::tuple>()[3].cast<py::array_t<double, py::array::forcecast | py::array::c_style>>();
        auto Ca = b.cast<py::tuple>()[4].cast<py::array_t<bool, py::array::forcecast | py::array::c_style>>();
        size_t n = Sa.size();
        std::vector<py::ssize_t> shape(Sa.shape(), Sa.shape() + Sa.ndim());
        py::array_t<double> P(shape), D(shape), G(shape), V(shape), Th(shape), R(shape);
        const double *s = Sa.data(), *k = Ka.data(), *t = Ta.data(), *vv = Va.data();
        const bool* c = Ca.data();
        double *p = P.mutable_data(), *d = D.mutable_data(), *g = G.mutable_data(), *ve = V.mutable_data(),
               *th = Th.mutable_data(), *rh = R.mutable_data();
        {
            py::gil_scoped_release rel;
            for (size_t i = 0; i < n; ++i) {
                Greeks x = bs(s[i], k[i], t[i], r, q, vv[i], c[i]);
                p[i] = x.price; d[i] = x.delta; g[i] = x.gamma; ve[i] = x.vega / 100; th[i] = x.theta / 365; rh[i] = x.rho / 100;
            }
        }
        py::dict out;
        out["price"] = P; out["delta"] = D; out["gamma"] = G; out["vega"] = V; out["theta"] = Th; out["rho"] = R;
        return out;
    }, py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"), py::arg("q"), py::arg("vol"), py::arg("call"));

    m.def("implied_vol", &implied_vol, py::arg("price"), py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"),
          py::arg("q"), py::arg("call") = true);
    m.def("geometric_asian", &geo_asian, py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"), py::arg("q"),
          py::arg("vol"), py::arg("fixings"), py::arg("call") = true);
    m.def("up_and_out_call", &uo_call, py::arg("S"), py::arg("K"), py::arg("H"), py::arg("T"), py::arg("r"), py::arg("q"),
          py::arg("vol"));

    m.def("binomial", [](double S, double K, double T, double r, double q, double v, int steps, bool call, bool american,
                         const std::string& method, bool boundary) {
        TreeOut o;
        {
            py::gil_scoped_release rel;
            o = binomial(S, K, T, r, q, v, steps, call, american, method, boundary);
        }
        py::dict d;
        d["price"] = o.price; d["delta"] = o.delta; d["gamma"] = o.gamma; d["theta"] = o.theta / 365.0;
        d["boundary_t"] = o.bt; d["boundary_S"] = o.bS;
        return d;
    }, py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"), py::arg("q"), py::arg("vol"), py::arg("steps") = 500,
       py::arg("call") = true, py::arg("american") = false, py::arg("method") = "crr", py::arg("boundary") = false);

    m.def("mc", [](double S, double K, double T, double r, double q, double v, bool call, const std::string& payoff,
                   long paths, int steps, bool antithetic, bool control, double barrier, u64 seed, int threads) {
        MCConfig c{S, K, T, r, q, v, barrier, call, parse_payoff(payoff), steps, paths, antithetic, control, seed, threads};
        if (c.payoff == Payoff::BarrierUO && barrier <= 0) throw std::invalid_argument("barrier must be > 0");
        if (paths < 2) throw std::invalid_argument("paths must be >= 2");
        MCOut o;
        {
            py::gil_scoped_release rel;
            o = mc_price(c);
        }
        py::dict d;
        d["price"] = o.price; d["stderr"] = o.stderr_; d["plain_stderr"] = o.plain_stderr; d["beta"] = o.beta;
        d["control_mean"] = o.control_mean; d["samples"] = o.samples; d["seconds"] = o.secs; d["threads"] = o.threads;
        d["ci95"] = py::make_tuple(o.price - 1.96 * o.stderr_, o.price + 1.96 * o.stderr_);
        return d;
    }, py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"), py::arg("q"), py::arg("vol"), py::arg("call") = true,
       py::arg("payoff") = "european", py::arg("paths") = 200000, py::arg("steps") = 1, py::arg("antithetic") = false,
       py::arg("control") = false, py::arg("barrier") = 0.0, py::arg("seed") = 42, py::arg("threads") = 0);

    m.def("lsm_american", [](double S, double K, double T, double r, double q, double v, bool call, int steps, long paths,
                             u64 seed, int threads) {
        LSMOut o;
        {
            py::gil_scoped_release rel;
            o = lsm(S, K, T, r, q, v, call, steps, paths, seed, threads);
        }
        py::dict d;
        d["price"] = o.price; d["stderr"] = o.stderr_; d["european"] = o.european; d["seconds"] = o.secs;
        d["boundary_t"] = o.bt; d["boundary_S"] = o.bS;
        return d;
    }, py::arg("S"), py::arg("K"), py::arg("T"), py::arg("r"), py::arg("q"), py::arg("vol"), py::arg("call") = false,
       py::arg("steps") = 50, py::arg("paths") = 100000, py::arg("seed") = 42, py::arg("threads") = 0);

    m.def("sample_paths", &sample_paths, py::arg("S"), py::arg("T"), py::arg("r"), py::arg("q"), py::arg("vol"),
          py::arg("steps"), py::arg("n"), py::arg("seed") = 1);
    m.attr("hardware_threads") = std::thread::hardware_concurrency();
}
