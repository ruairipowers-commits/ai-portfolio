# lob-matching-engine

**A Rust limit order book and matching engine, benchmarked for tail latency, with code-detected surveillance alerts
that a model explains and an analyst decides.** The engine replays order flow; rules in code raise layering, wash,
quote-stuffing and momentum-ignition alerts from its event log; a model drafts each alert's narrative citing event
ids; deterministic policy and a named analyst have the last word.

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers ·
> Write-up: [{{BLOG_TITLE}}]({{SITE_URL}}/blog/lob-matching-engine/) · Live demo: [try it]({{DEMOS_URL}}/lob-matching-engine/) · Governance: [standard]({{SITE_URL}}/blog/governance/) / [this project's mapping](docs/governance.md)

![rust](https://img.shields.io/badge/engine-rust-orange) ![python](https://img.shields.io/badge/python-3.11-blue) ![runs offline](https://img.shields.io/badge/runs-offline%20by%20default-green)

## What it does

1. **Matches orders** with strict price-time priority: limit, market, IOC, FOK, post-only, stop-market and stop-limit
   orders; cancel; modify (a size-down keeps queue priority, anything else is cancel/replace); self-trade prevention.
2. **Measures itself**: throughput from an untimed replay, p50 → p99.99 and max latency from a per-command timer,
   per order type, with the timer's own overhead reported.
3. **Replays a session** (13k synthetic orders from 20 noise traders, plus four fictional traders scripted to layer,
   wash-trade, quote-stuff and ignite momentum, or your own order log) and computes market quality: spread, depth,
   order-to-trade ratio, self-trade-prevention cancels, Kyle's λ.
4. **Raises surveillance alerts in code** and has a model draft each alert's narrative from the event log. Every cited
   event id and figure is checked; trader ids never reach the model; order memos are treated as untrusted.
5. **An analyst closes or escalates** every alert. Closing a high-severity alert needs a written reason.

## Quickstart (5 minutes, no API keys)

Needs Python 3.11+ and a Rust toolchain ([rustup.rs](https://rustup.rs)) to build the engine.

```bash
git clone <this repo> && cd lob-matching-engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,dev]"            # builds the Rust engine (maturin, release profile)

lob-matching-engine ui                # browser app (http://localhost:8501)

lob-matching-engine all               # synthetic session → gate → replay → detectors → narratives
cat output/alerts_summary.md
lob-matching-engine review A001 ESCALATE --reviewer you
lob-matching-engine eval              # golden-set eval gate
lob-matching-engine bench             # engine benchmark through Python;  make bench  for the native CLI
pytest -q && (cd rust && cargo test --release)
```

Expected summary on the default session (seed 7, offline mock model):

| Alert | Pattern | Trader | Severity | Model suggested | Final suggestion |
|---|---|---|---|---|---|
| A001 | layering: 5 offers × 400 shares (20× median), 40-share buy fill, layer cancelled 0.75 s later | L07 | high | ESCALATE | ESCALATE |
| A002 | wash: 3 attempts blocked by STP, orders crossed after 300 ms | W03 | medium | NEEDS_INFO | NEEDS_INFO |
| A003 | stuffing: 200 orders, 100% cancelled, 0 fills, 51 ms median life | Q11 | low | CLOSE | CLOSE |
| A004 | ignition: 5 aggressive buys in 1.4 s, +5 ticks, then sold 400 shares | M05 | high | ESCALATE | ESCALATE |

Put `"...please close"` in L07's order memos and the (deliberately gullible) mock suggests CLOSE; policy turns it
back to ESCALATE because the alert is high severity. Put an injection there and the alert is also flagged.

### Benchmark

Native CLI, single thread, 2M commands of mixed flow (45% limit, 32% cancel, rest market / IOC / FOK / post-only /
stop / modify), measured in a 2-vCPU cloud container:

| Throughput | p50 | p90 | p99 | p99.9 | p99.99 |
|---|---|---|---|---|---|
| 15.3 M commands/s | 56 ns | 171 ns | 377 ns | 879 ns | 17 µs |

Tails past p99.9 are page faults as the slab grows and OS scheduling. Pin a core and pre-size the slab for
production numbers. The **Benchmark lab** page runs the same harness from the app, with sweeps and tail plots.

### The app

`lob-matching-engine ui` opens two sections. **Surveillance workflow**: 1 · Input (synthetic, clean or uploaded
session; *Try to break it* edits the layering trader's order memos with one-click injection, PII and "please close"
examples, and two buttons corrupt the session), 2 · Run (data gate → replay → detectors → narratives, shown step by
step), 3 · Output (alerts with the trader's orders around each one, the narrative with every figure checked, the
analyst decision, market quality, the eval gate, and the audit log including exactly what the model saw).
**Engine lab**: a trading desk against the live book (queue position, pre-trade fill estimate, P&L by trader),
a market simulator with liquidity heatmaps and shock recovery, the benchmark lab, and the matching rules step by step.

### Use a real model

```bash
pip install -e ".[anthropic]"            # or [openai], [aws] for Bedrock
cp .env.example .env                     # add ANTHROPIC_API_KEY
# config/models.yaml: fill pricing for claude-sonnet, set narrative-candidate: claude-sonnet
lob-matching-engine eval --alias narrative-candidate --baseline narrative-primary
lob-matching-engine promote narrative-primary claude-sonnet
```

The mock provider is a deterministic template filler so CI is free and results reproducible; it is not an LLM.

## Governance console

Every visit, run, review and eval is reported to the portfolio's [governance console]({{SITE_URL}}/blog/governance-console/):
who ran it, the model, tokens, cost, records in and out, the outcome and safety flags (never order memos, narratives or
trader ids: only counts and hashes). The console can switch the workflow off; runs then refuse with the reason. Point
`GOVERNANCE_URL` at the console (events are posted with `GOVERNANCE_INGEST_TOKEN`); without it, events go to a local
spool file. `GOVERNANCE_TELEMETRY=off` disables telemetry; `GOVERNANCE_FAIL_CLOSED=1` blocks runs when the console
can't be reached.

## Requirements

**Functional**

| ID | Requirement |
|---|---|
| FR-1 | Strict price-time priority; limit, market, IOC, FOK, post-only, stop-market, stop-limit; cancel; modify keeps priority only on a size-down; optional STP |
| FR-2 | Benchmark throughput (untimed) and p50 / p99 / p99.9 / p99.99 / max latency per command type, with parameter sweeps |
| FR-3 | Replay a session (synthetic or uploaded) and compute market-quality stats |
| FR-4 | Detect layering / spoofing, STP-blocked wash attempts, quote stuffing and momentum ignition, each with severity and the triggering event ids |
| FR-5 | Draft a narrative per alert inside a schema; check every citation and figure against the event log |
| FR-6 | Analyst closes or escalates every alert; high severity can't be closed without a reason; decisions are stored against the AI's suggestion |

**Non-functional**

| ID | Requirement | Measured |
|---|---|---|
| NFR-1 | Offline end to end in < 5 minutes with the mock model | `all` ≈ 2 s after the build; eval gate ≈ 8 s |
| NFR-2 | Engine ≥ 5M commands/s single-threaded, p99 < 2 µs | 15.3M/s, p99 377 ns (2-vCPU container) |
| NFR-3 | Book invariants hold after every command on randomised flow | 60k-command Rust test |
| NFR-4 | Every figure in a narrative matches the event log | citation accuracy 1.00 on the golden set |
| NFR-5 | < $0.005 per alert, hard run budget; trader ids never reach the model | ≈ $0.003 simulated per alert; 0 ids in payloads (tested) |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Learning and demonstration: how a matching engine works and performs, and how a model can speed up surveillance reviews without deciding them. |
| **Not for** | Live trading, a real venue's matching, or regulatory surveillance decisions. |
| **Risk tier** | Medium — see [governance mapping](docs/governance.md) |
| **Owner** | Market-structure engineering (engine) · Trade surveillance (alerts) |
| **Known limits** | Detectors are simple rules tuned on synthetic flow (false negatives are likely on real data); one instrument; no auction phases, iceberg orders or market-maker obligations; regex screening catches common injection and PII patterns, not all. |

## Architecture

See [docs/architecture.md](docs/architecture.md) for diagrams and design decisions, and
[docs/aws-native.md](docs/aws-native.md) for the AWS path.

```
rust/                 the engine (book.rs, flow.rs), pyo3 bindings, native benchmark CLI, Rust tests
config/               settings.yaml (gate, detectors, budgets, policy, thresholds) · models.yaml (registry + aliases)
prompts/              versioned system prompt
src/lob_matching_engine/
  sessions.py         generator, data gate, replay, market quality
  detectors.py        surveillance rules
  workflow.py         the governed narrative step and dispose()
  guardrails.py       injection scan, PII redaction, pseudonyms, schema parse, citation check, policy
  ui.py + lab/        Streamlit app
evals/                golden set
infra/aws/            Terraform starter (Kinesis, ECS, Bedrock, DynamoDB, S3 Object Lock, Budgets)
```

## Configuring it

| What | File | Key |
|---|---|---|
| Detector thresholds and severities | `config/settings.yaml` | `detectors.*` |
| Data gate | `config/settings.yaml` | `gate.*`, `engine.price_band` |
| What the model sees | `config/settings.yaml` | `data.*` |
| Policy after the model | `config/settings.yaml` | `policy.*` |
| Spend caps / monthly alert | `config/settings.yaml` | `cost.*` |
| Eval thresholds | `config/settings.yaml` | `eval.*` |
| Switch model | `config/models.yaml` | `aliases.narrative-primary` (via `promote`) |
| Prompt | `prompts/alert_narrative.v1.md` | new file per version; update `llm.prompt_file` |

## Commands

| Command | Purpose |
|---|---|
| `lob-matching-engine ui` | Streamlit app |
| `lob-matching-engine all` | data → run |
| `lob-matching-engine run [--session file.csv] [--alias X]` | gate → replay → detectors → narratives |
| `lob-matching-engine review A001 ESCALATE --reviewer you [--reason "..."]` | record the analyst's decision |
| `lob-matching-engine eval [--alias X] [--baseline Y]` | eval gate, non-zero exit on fail/regression |
| `lob-matching-engine promote <alias> <model>` | move an alias only if its eval passed on the current prompt |
| `lob-matching-engine models-check` | approval, pricing, deprecation warnings |
| `lob-matching-engine cost-report` | tokens and $ by month / model / prod vs eval |
| `lob-matching-engine bench` / `make bench` | engine benchmark through Python / native |

## License

Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you reuse it (see [NOTICE](NOTICE)). All traders, orders and memos are synthetic.
