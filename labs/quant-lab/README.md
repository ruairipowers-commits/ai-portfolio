# Quant Lab — three trading-systems projects with interactive Streamlit front ends

| Project | Core | What the app lets you do |
|---|---|---|
| **1. Limit order book & matching engine** | Rust (pyo3) | Trade against a live book, simulate agent order flow with liquidity shocks, benchmark throughput and p99/p99.9 latency, step through the matching rules |
| **2. Event-driven backtester** | Python engine + C++ kernels (pybind11) | Backtest tick data with latency, spread, square-root impact and commissions; cost/latency sensitivity; multithreaded sweeps and walk-forward; a lookahead-bias lab |
| **3. Options pricing & Greeks engine** | C++ (pybind11, `std::thread`) | Price with Black-Scholes, three binomial trees and Monte Carlo; Greek surfaces; convergence and speed studies; exotics and American options; multi-leg strategy risk |

Each app has several pages and goes beyond input → run → output: there's state you trade against, scenarios to step through, grids, sweeps, cross-checks and diagnostics.

---

## Quick start

```bash
# prerequisites: Python ≥ 3.9, a C++17 compiler, Rust (https://rustup.rs)
./build.sh                       # installs Python deps, builds all three native engines, runs tests

streamlit run lob_engine/app/app.py
streamlit run backtester/app/app.py
streamlit run options_engine/app/app.py
```

Manual builds:

```bash
pip install -r requirements.txt
(cd lob_engine && maturin build --release && pip install --force-reinstall target/wheels/*.whl)
pip install -e backtester
pip install ./options_engine
pytest -q lob_engine/tests backtester/tests options_engine/tests
(cd lob_engine && cargo test --release && cargo run --release --bin lob-bench -- 5_000_000 50_000)
```

---

## 1 · Limit order book & matching engine (`lob_engine/`)

**Engine (`src/book.rs`)**
- Strict **price-time priority**. Order types: limit, market, IOC, FOK, post-only, stop-market, stop-limit. Cancel, and modify (a size-down keeps queue priority; a re-price or size-up is cancel/replace). Optional self-trade prevention.
- **Dense price ladder**: one level per tick in a fixed band, so finding a level is an array index.
- Each level is an **intrusive doubly-linked FIFO in a slab with a free list**, so add, cancel and fill are O(1) and allocation-free in steady state.
- Cached best bid/ask, rescanned only when the best level empties. Stops live in ordered maps and are released after each print, so stop cascades work.
- `check_invariants()` (aggregates, FIFO order, cached best prices, uncrossed book) is exercised by a 60k-command randomised test.

**Benchmark (`src/flow.rs`)**: commands are pre-generated so RNG isn't timed. The same stream is replayed twice on fresh books: an untimed loop for throughput and a per-command timed loop for the latency distribution, with timer overhead measured and reported.

Measured in this 2-vCPU cloud sandbox (single thread, 2M commands, realistic mix):

| throughput | p50 | p90 | p99 | p99.9 |
|---|---|---|---|---|
| **~16 M ops/s** | 68 ns | 214 ns | 451 ns | 1.1 µs |

**App pages**
- **Trading desk**: order ticket with a pre-trade fill estimate (avg price, slippage vs mid in bps); DOM ladder showing your own resting quantity; cumulative depth chart; **queue inspector** (your position in the FIFO and shares ahead of you); editable open orders (modify or cancel); stop orders; trade tape; **P&L by trader** marked to mid; event log; noise-flow bursts that can hit your orders.
- **Market simulator**: tune the flow mix, sizes, placement and imbalance; inject a sweep. Liquidity heatmap with quotes and trades, book replay scrubber, **shock recovery** metrics, **order-flow imbalance → price impact (Kyle's λ)** regression, spread and trade-size distributions, why orders leave the book. Load the final book into the desk.
- **Benchmark lab**: flow presets, percentiles up to p99.99 and max, log-x histogram, **CCDF tail plot comparing runs**, latency by command type, run history, and **parameter sweeps** (book depth, placement width, cancel share, market share).
- **Matching rules, step by step**: 7 guided scenarios (priority, IOC vs FOK, post-only, modify priority, stop cascade, STP, thin-book market order), each auto-verified.

---

## 2 · Event-driven backtester (`backtester/`)

**Engine (`qlbt/engine.py`)**: the DataHandler, Strategy, Portfolio and ExecutionHandler communicate only through `TICK / BAR / ORDER / FILL` events on a time-ordered heap.

How it avoids lookahead:
- A bar is published only after a tick from the next bucket arrives, so strategies never see a forming bar.
- Strategies get a read-only `History` of completed bars, and `bars.at(i)` for an unclosed bar raises `LookaheadError`.
- Orders activate at decision time + latency and fill on the first tick at or after that time, at bid/ask, plus slippage and **square-root impact** (`impact = c · √(order / 1% ADV)`), plus per-share/bps commission with a minimum ticket. Passive limit orders are also supported; they convert to market after a timeout.
- A frictionless "paper" portfolio runs alongside, so every result decomposes **gross → spread → impact → commission → latency → net**.

**C++ kernels (`cpp/qlbt_core.cpp`)**: tick→bar resampling, and a tick-level MA-crossover simulator implementing **the same event semantics and cost model**, swept over parameter grids with `std::thread`. The Python engine and the kernel agree to the cent: 144/144 randomised configurations match, including latency longer than a bar (a pytest checks this). That cross-check is what makes the fast sweeps trustworthy.

**Synthetic data**: U-shaped intraday activity, persistent drift regimes, vol regimes, jumps, overnight gaps, and a stochastic spread on a 1-cent grid that widens at the open and close. CSV upload is supported (quotes or trades).

**App pages**
- **Market data**: generator or CSV upload, candles, intraday activity, spread and return distributions (kurtosis), C++ vs pandas resample timing.
- **Strategy backtest**: MA crossover, Bollinger reversion, Donchian breakout, vol-target momentum, or **your own `on_bar(ctx)` code**; market or passive limit execution. Net vs frictionless equity, position, drawdown, weekly return heatmap; **fills on the tape** with decision→fill lines; **cost waterfall**; shortfall and cost-vs-size charts; round trips (hit rate, payoff ratio, holding time); fill blotter export; event counts and a **live Python-vs-C++ cross-check**.
- **Cost & latency sensitivity**: a 72-backtest Sharpe grid (cost multiplier × latency), break-even cost multiplier, and **capacity** (cost bps and Sharpe vs order size as % of ADV).
- **Sweep & walk-forward**: multithreaded grid heatmaps (net/gross Sharpe, return, DD, turnover, cost), a **selection-bias check** (expected best-of-N Sharpe under zero edge), thread scaling, and rolling or anchored **walk-forward** with stitched OOS equity vs the hindsight-optimised curve and IS→OOS degradation.
- **Lookahead-bias lab**: the honest engine vs fill-at-signal-close, a forgotten `.shift(1)`, a centred rolling window, and next-bar peeking, shown side by side (Sharpe inflation table). A deliberately leaky strategy is stopped by the guard.

---

## 3 · Options pricing & Greeks engine (`options_engine/`)

**Engine (`cpp/optlib.cpp`)**
- **Black-Scholes-Merton** with dividends: price, Δ, Γ, vega, Θ, ρ (scalar and vectorised). Implied vol uses Newton with a bisection safeguard.
- **Binomial**: CRR, Jarrow-Rudd and **Leisen-Reimer**; European/American; Greeks from tree nodes; early-exercise boundary.
- **Monte Carlo, multithreaded**: European, arithmetic Asian, discretely monitored up-and-out barrier; **antithetic** and **control variates** (terminal stock / vanilla / geometric Asian). Paths are generated in fixed blocks seeded by block id, so **results are bit-identical for any thread count**, and the same seed gives common random numbers for bump-and-revalue Greeks.
- **Longstaff-Schwartz** American MC, with the European value as a lower bound on continuation (prevents premature exercise from noisy regressions).
- Closed-form anchors: discrete **geometric Asian** and continuous **up-and-out call** (Reiner-Rubinstein), plus the Broadie-Glasserman-Kou discrete-monitoring correction.

Empirical convergence (ATM 1y call): CRR **O(1/n)** (order 1.00, odd/even sawtooth), Leisen-Reimer **O(1/n²)** (order 1.98, error 9e-8 at 2,000 steps in ~2 ms), MC stderr order 0.50. Antithetic + control variate gives a ~23× variance reduction (~40× efficiency gain). On the Asian, the geometric control gives a >1,000× variance reduction.

**App pages**
- **Pricer & Greeks**: every method side by side with error vs BS and timing (BS ≈ 0.5 µs per call, tens of ns per option vectorised); MC Greeks by CRN bump-and-revalue; American mode with tree + LSM and the early-exercise premium; put-call parity; **IV solver** with a smile round-trip.
- **Greeks explorer**: 3D surfaces / heatmaps of price and Greeks vs spot × expiry or spot × vol, including **vanna, volga, charm, speed**, with slices by expiry and vol.
- **Convergence & speed lab**: tree price/error vs steps with fitted orders; MC estimate with 95% bands vs paths; variance-reduction and efficiency table; an **accuracy-vs-wall-time frontier** across all methods; **thread scaling** with a determinism check.
- **Exotics & American**: Asian (plain vs antithetic vs geometric control), barrier (monitoring frequency vs continuous and BGK-corrected closed forms; price vs barrier curve), American put (tree vs LSM, exercise boundary over sample paths, premium vs rates).
- **Strategy builder & risk**: 9 presets or custom legs (editable table), payoff and value-through-time curves with a vol shift, position Greeks, breakevens, P(profit), a **full-revaluation P&L heatmap** (spot × days), a scenario grid (spot × vol) and **full reval vs Δ and Δ-Γ approximations**.

---

## Repository layout

```
lob_engine/      Cargo.toml · pyproject.toml · src/{book,flow,python,lib}.rs · src/bin/bench.rs · tests/ · app/
backtester/      setup.py · cpp/qlbt_core.cpp · qlbt/{engine,data,strategies,metrics,walkforward}.py · tests/ · app/
options_engine/  setup.py · cpp/optlib.cpp · tests/ · app/
```

## Notes
- Performance numbers above came from a 2-vCPU cloud container. Expect better on a desktop CPU; for stable tails, pin a core and disable frequency scaling.
- Everything is synthetic or user-supplied data, for learning and demonstration. Not investment advice.

## Credit
Designed and built by **Ruairi Powers**, with his AI assistant **Claude** (Anthropic). Open source under the MIT licence; if you reuse or adapt this work, please credit both.
