# altdata-triage

**Governed AI workflow that triages alternative-data vendor samples.**
dbt computes the facts, an LLM drafts the memo, deterministic policy has the last word, and a human decides.

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers ·
> Write-up: [{{BLOG_TITLE}}]({{SITE_URL}}/blog/altdata-triage/) · Governance: [standard]({{SITE_URL}}/blog/governance/) / [this project's mapping](docs/governance.md)

![python](https://img.shields.io/badge/python-3.11-blue) ![dbt](https://img.shields.io/badge/dbt-duckdb-orange) ![runs offline](https://img.shields.io/badge/runs-offline%20by%20default-green)

## What it does

A data-sourcing team receives samples from alt-data vendors faster than analysts can evaluate them.
This project loads each sample, scores it with dbt (history, ticker mapping to the security master,
nulls, gaps, staleness, core-universe coverage), then has an LLM write a short triage memo —
**PURSUE / PARK / REJECT / ESCALATE** — with every cited number checked against the source.

Five synthetic vendors exercise each path, including one whose questionnaire contains a
prompt-injection attempt and one whose license forbids derived use of PII-bearing data.

## Quickstart (5 minutes, no API keys)

```bash
git clone <this repo> && cd altdata-triage
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,dev]"

altdata-triage ui             # browser app: input → Run → output (http://localhost:8501)

# or from the command line:
altdata-triage all            # generate data → ingest → dbt build (+tests) → triage
cat output/triage_summary.md  # results;  memos in output/memos/
altdata-triage eval           # golden-set eval gate
pytest -q                     # 25 tests incl. end-to-end and the app
```

Expected summary:

| Vendor | Final | Why |
|---|---|---|
| CardPulse (v01) | PURSUE | 7.7y point-in-time history, 94% mapped, fresh |
| FootfallIQ (v02) | PARK | 3y history, 62% mapped, 6 weeks stale |
| AppSignal (v03) | REJECT | PII present, license forbids derived use |
| WebCrawl Labs (v04) | ESCALATE | model drafted PARK; policy escalated on injection attempt |
| ShipTrack (v05) | PARK | backfilled history — look-ahead bias risk |

### The app

![Alt-data triage app: an injected note on CardPulse is escalated by policy](docs/img/app.png)

`altdata-triage ui` opens a three-part page: **Input** (the five sample vendors by default; edit a
vendor's untrusted notes to try an injection or PII; **view, edit, download or reset each vendor's
`sample.csv` and questionnaire** — filter by ticker/date, edit cells, add or delete rows, or use one-click
"add a future-dated row" / "blank the latest week"; or upload your own sample), **Run**
(ingest → dbt build → triage, stopping if any data test fails) and **Output** (recommendation counts,
model draft vs final after policy, each memo with a human-review form, the dbt scorecard, the eval gate,
and every model call with its cost). Runs on the offline mock unless you pick a configured model.

### Use a real model

```bash
pip install -e ".[anthropic]"            # or [openai], [aws] for Bedrock
cp .env.example .env                     # add ANTHROPIC_API_KEY
# config/models.yaml: fill pricing for claude-sonnet, set triage-candidate: claude-sonnet
altdata-triage eval --alias triage-candidate --baseline triage-primary
altdata-triage promote triage-primary claude-sonnet
altdata-triage triage
```

The mock provider is a deterministic heuristic stand-in so CI is free and results reproducible;
it is not an LLM. Swap it out as above to see real model behaviour.

## Governance console

Every visit, triage run, review and eval is reported to the portfolio's [governance console]({{SITE_URL}}/blog/governance-console/): who ran it, the model, tokens, cost, records in and out, the outcome and safety flags
(never prompts, questions or document text — only counts and hashes). The console can switch the workflow off; the triage run then refuses with the reason. Point `GOVERNANCE_URL` at the console (events are posted with `GOVERNANCE_INGEST_TOKEN`); without it, events go to a local spool file (`~/.ai-portfolio/governance/events.jsonl`) that a console on the same machine imports. `GOVERNANCE_TELEMETRY=off` disables telemetry; `GOVERNANCE_FAIL_CLOSED=1` blocks runs when the console can't be reached.

## Requirements

**Functional**

| ID | Requirement |
|---|---|
| FR-1 | Ingest any number of vendor folders (panel CSV + questionnaire) into a warehouse. |
| FR-2 | Compute per-vendor coverage, quality and freshness metrics and a transparent 0–100 rule score. |
| FR-3 | Produce a structured memo per vendor with recommendation, strengths, risks, cited evidence, next steps. |
| FR-4 | Record a named human reviewer's decision against each AI recommendation. |
| FR-5 | Report spend by month, model and prod/eval. |

**Non-functional**

| ID | Requirement | Target |
|---|---|---|
| NFR-1 Reproducibility | Same inputs + model → same scorecard; offline mode fully deterministic | ✅ |
| NFR-2 Cost | < $0.10 per vendor with a mid-tier model; hard stop at run budget | configurable |
| NFR-3 Latency | Batch job; < 1 min per vendor | ✅ |
| NFR-4 Portability | Runs on a laptop with no cloud; same code on AWS | ✅ / [AWS guide](docs/aws-native.md) |
| NFR-5 Auditability | Every model call and decision queryable in SQL | ✅ |
| NFR-6 Safety | Compliance cases cannot be auto-approved regardless of model output | ✅ |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Prioritise analyst diligence on new alt-data vendors. Advisory only. |
| **Not for** | Final purchase decisions, legal/licensing sign-off, investment signals. |
| **Risk tier** | Medium — see [governance mapping](docs/governance.md) |
| **Owner** | Data sourcing lead (business) · Data engineering (technical) |
| **Known limits** | Rule score weights are judgment calls; questionnaire answers are self-reported by vendors; regex PII/injection screening catches common patterns, not all. |

## Architecture

See [docs/architecture.md](docs/architecture.md) for diagrams and design decisions.

```
config/        settings.yaml (budgets, policy, thresholds) · models.yaml (registry + aliases)
prompts/       versioned system prompts
dbt/           staging → intermediate → marts, tests, security-master seed
src/altdata_triage/
  workflow.py  the governed triage steps
  guardrails.py injection scan, PII redaction, schema + citation checks, policy
  llm.py       providers (mock, Anthropic, OpenAI, Bedrock), budgets, retries, fallback
  evals.py     golden-set eval + no-regression gate
  store.py     ingestion + audit tables
evals/         golden_set.yaml
infra/aws/     Terraform starter for the AWS-native path
```

## Configuration

| What | Where | Key |
|---|---|---|
| Switch model | `config/models.yaml` | `aliases.triage-primary` (via `promote`) |
| Spend caps | `config/settings.yaml` | `cost.max_usd_per_run`, `cost.max_input_tokens_per_call` |
| Monthly alert | `config/settings.yaml` | `cost.monthly_alert_usd` |
| Eval thresholds | `config/settings.yaml` | `eval.*` |
| Business rules | `config/settings.yaml` | `policy.*` |
| Score weights | `dbt/models/marts/vendor_scorecard.sql` | `rule_score` expression |
| Prompt | `prompts/triage_memo.v1.md` | new file per version; update `llm.prompt_file` |

## Commands

| Command | Purpose |
|---|---|
| `altdata-triage ui` | Streamlit app: default vendors (or your upload / edited notes) → Run → summary, memos, review, eval, audit |
| `altdata-triage all` | data → ingest → transform → triage |
| `altdata-triage triage [--vendor v01] [--alias X]` | memos (blocked unless dbt tests passed) |
| `altdata-triage review v02 PURSUE --reviewer you --note "..."` | record human decision |
| `altdata-triage eval [--alias X] [--baseline Y]` | eval gate, non-zero exit on fail/regression |
| `altdata-triage promote <alias> <model>` | move alias only if eval passed on current prompt |
| `altdata-triage models-check` | approval, pricing, deprecation warnings |
| `altdata-triage cost-report` | tokens and $ by month / model / prod vs eval |
| `make docs` | dbt lineage site |

## License

MIT. All vendor names and data are synthetic.
