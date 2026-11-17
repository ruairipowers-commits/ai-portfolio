# Architecture — event-backtester

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    subgraph In["Inputs"]
        T[Tick quotes<br/>synthetic or CSV]
        S[Strategy + params<br/>+ variants tried]
        N[Research notes<br/>untrusted]
    end
    G{{Data gate<br/>DATA-02}}
    subgraph Engine["Event-driven engine (Python)"]
        Q[Time-ordered queue<br/>TICK · BAR · ORDER · FILL]
        H[History of closed bars<br/>LookaheadError]
        X[Execution<br/>latency · spread · √impact · commission]
    end
    K[C++ kernel<br/>same semantics<br/>parity check · sweeps]
    C[Promotion checks<br/>significance · OOS · 2× costs · lookahead]
    subgraph AI["Governed memo"]
        L[Model via alias<br/>MODEL-01 · COST-01]
        V[Schema + figure check<br/>SEC-04 · OBS-02]
        P[Presentation rules<br/>net headline · disclosures]
        R[Policy<br/>failed check ⇒ not promotable]
    end
    PM[PM decision<br/>HITL-02]
    A[(SQLite audit<br/>OBS-01)]
    T --> G --> Q
    S --> Q
    Q --> H --> X --> Q
    X --> C
    T --> K
    C --> L
    N --> L
    L --> V --> P --> R --> PM
    L -.-> A
    R -.-> A
    PM -.-> A
```
<!-- --8<-- [end:flow] -->

## One run, end to end

<!-- --8<-- [start:sequence] -->
```mermaid
sequenceDiagram
    participant U as Researcher / PM
    participant W as Workflow
    participant E as Engine
    participant K as C++ kernel
    participant M as Model (alias)
    participant A as Audit (SQLite)
    U->>W: dataset, strategy, notes, variants tried
    W->>W: data gate (crossed quotes, time order, gaps, spreads)
    W->>E: full run, 2× cost run, in-sample and out-of-sample runs
    E-->>W: bars, fills, costs, lookahead errors
    W->>K: same strategy (MA) on the same ticks
    K-->>W: equity per bar (must match to the cent)
    W->>W: six promotion checks
    W->>M: metrics + checks + delimited notes
    M-->>W: JSON memo
    W->>W: schema, figures vs run, net headline, disclosures, policy
    W->>A: call log, memo, blockers
    U->>W: APPROVE / REJECT (approve refused if blocked)
    W->>A: decision (agrees with the memo?)
```
<!-- --8<-- [end:sequence] -->

## Design decisions

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives |
|---|---|---|---|
| Engine style | Event-driven, one event queue, ticks streamed one at a time | Makes lookahead structurally impossible and models latency and fills honestly | Vectorised pandas (fast, easy to leak the future); backtrader / zipline |
| Lookahead guard | Bars published only after the next bucket's first tick; read-only `History`; `LookaheadError` | A leak fails loudly instead of inflating results | Code review and hope |
| Speed | C++ kernel (pybind11, `std::thread`) for the MA strategy's sweeps and walk-forward | Grids of hundreds of tick-level backtests in seconds | Numba; vectorbt; a full C++ engine (less readable) |
| Trusting the kernel | Same semantics implemented twice, compared to the cent on 144 configurations and on every run | A fast engine that drifts from the reference is worse than a slow one | Trust the fast path |
| Promotion gate | Six checks in code: lookahead, fills, selection-adjusted t, out-of-sample Sharpe, degradation, 2× cost Sharpe | The decision's inputs must not depend on a model | Model judges the backtest (unauditable) |
| Selection bias | t-stat minus √(2 ln N) for N declared variants | Cheap, explainable haircut for best-of-N | Deflated Sharpe ratio (Bailey & López de Prado); combinatorial purged CV |
| Model's job | Draft the memo inside a schema; every figure and the headline checked | Saves write-up time without letting prose move numbers | No model; model-written conclusions |
| Who decides | A named PM; approve refused when anything is blocked | Capital allocation is a human decision | Auto-promote on a passing gate |
| Data format / store | Parquet ticks; SQLite audit | Columnar, compressed ticks; zero-infra audit | DuckDB / Arrow datasets; Postgres |
<!-- --8<-- [end:decisions] -->

## Code map

```
cpp/core.cpp            C++ kernels: resample, MA-cross simulator, multithreaded sweeps → event_backtester._core
src/event_backtester/
  engine.py             event queue, History guard, execution, portfolio
  data.py               synthetic ticks, CSV loader, resampling
  strategies.py         MA cross, Donchian, Bollinger, vol-target momentum, leaky (for the demo), custom code
  gates.py              data gate and promotion checks
  workflow.py           checks → memo → validate → figure + presentation checks → policy → audit; decide()
  guardrails.py         injection scan, redaction, schema parse, figure check, presentation rules, policy
  walkforward.py        kernel sweeps and walk-forward;  metrics.py  performance, round trips, cost waterfall
  llm.py / mock_model.py   registry, budgets, fallback; deterministic gullible mock
  evals.py · store.py · telemetry.py · ui.py (+ lab/ pages)
```
