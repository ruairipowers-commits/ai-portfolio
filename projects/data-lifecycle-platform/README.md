# data-lifecycle-platform

**A data marketplace that runs the whole life of a dataset — find it, catalogue it, judge it, license it, load it,
pay for it, retire it, or help a company sell its own — on four layers kept deliberately apart: an ontology (what
things mean), a knowledge graph (what exists and how it connects), a semantic layer (governed metrics in SQL) and a
context layer (the small, entitled, cited packet a model is allowed to see).**

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers ·
> Write-up: [{{SITE_URL}}/blog/data-lifecycle-platform/]({{SITE_URL}}/blog/data-lifecycle-platform/) ·
> Governance: [this project's mapping](docs/governance.md)

## What it does

- **Managed catalog.** Vendors and datasets with full create/edit/delete, operator-defined custom fields (text,
  number, date, enum, URL, yes/no — validated, optionally bound to a vocabulary concept) and links back to each
  vendor's site, docs and marketplace listings. Every extracted fact keeps its source URL.
- **AI cataloguing.** Point it at a vendor page, a dataset card, a data dictionary or an OpenAPI spec. Structured
  sources are parsed by code; pages go to the model, and every value must quote the source. Fields are mapped to
  concepts (ticker, CIK, implied vol…). Licence text a vendor writes is kept as a *claim* for legal — it never sets
  the licence tag. Nothing is published until a named reviewer approves it.
- **Find data.** Plain-English needs ("data that would help us position for rising rates") become a search plan over
  the vocabulary. Economic factors expand through the graph to the sectors they move and the data categories that
  observe them. Results show what your firm can do with each dataset today and what it overlaps with; marketplace
  listings not yet in the catalog come back as discoveries.
- **Assess and compare.** Coverage of the S&P 500, history, freshness, nulls, concepts, licence verdict, price and
  overlap with what you hold — computed in SQL and the graph — side by side for up to four datasets. The model writes
  the memo and alpha-use hypotheses, each labelled untested with a way to test it; one (IV–HV spread) is actually run.
- **Buyers, contracts, entitlements.** Firms register free data or subscribe to paid data. Paid data needs a timed
  contract (term, notice, price, seats, permitted use, AI processing yes/no) signed off by a named approver.
  Entitlements follow from active contracts and the licence rules, and they govern downloads, feeds and what any
  model may see.
- **Spend, ROI, migration, retirement.** Spend and usage per firm and dataset from the semantic layer, cost per query,
  budget headroom, renewal deadlines, candidates to retire or migrate. Retirement is impact-checked against the graph
  (metrics, assets, reports, teams) and blocked until a substitute is mapped.
- **Monetize your data.** A company uploads a sample and a description. Code profiles it, blocks it if it holds
  personal data (nothing goes to a model), places it in the vocabulary, measures uniqueness against the catalog and
  prices it from comparable listings; the model writes the advice; the operator approves any listing.
- **Marketplaces and feeds.** One adapter interface: Hugging Face Hub live; Snowflake Marketplace, AWS Data Exchange
  and Databricks Marketplace tested on recorded responses. File and Hub feeds run; S3/SFTP/Snowflake share are adapters.
- **Everywhere you'd want it.** Streamlit app, CLI (`dlp`), REST API with per-firm tokens, a read-only MCP server
  for other agents, and Dagster assets for scheduling.

## Data

| Dataset | Source | Licence | Role |
|---|---|---|---|
| `gauss314/options-IV-SP500` | Hugging Face | Apache-2.0 | Primary: implied vol by moneyness, HV 20–200d, call/put volume and OI, VIX |
| `jwigginton/index-constituents-sp500` | Hugging Face | none declared | Reference: companies, GICS sectors, CIK. Its missing licence is the legal-review test case |
| 20 S&P 500 listings | Hugging Face search, 4 Oct 2026 | as tagged | The marketplace snapshot for discovery |
| 5 vendors, 3 buyer firms, contracts, usage, one data owner, factor sensitivities | synthetic | — | Everything a firm holds internally. All fictional; websites on example.com |

**Offline by default.** This sandbox can't reach the Hub, so tests, CI and the hosted demo run on a fixture with the
same columns (generated values for 26 symbols × 120 trading days; real names, sectors and CIKs for 45 constituents).
`dlp fetch` pulls the real slices (needs network and `pip install -e ".[hub]"`); it checks the real columns against
the fixture's and stops with the real list if they differ. Numbers below are from the fixture.

## Quickstart

```bash
pip install -e ".[ui,dev,api,mcp,orchestration]"
dlp all                   # seed → dbt build + 22 tests → SHACL → graph → 19-case eval gate (offline, ~10 s)
dlp ui                    # the app
dlp ask "What is the ATM implied volatility and IV-HV spread for AAPL and JPM?" --customer cust-harbor
dlp search "data that would help us position for rising rates" --customer cust-alder
pytest -q                 # 43 tests
```

Real data: `pip install -e ".[hub]" && dlp fetch && dlp build`. A real model: add pricing to `config/models.yaml`,
point `dlp-candidate` at it, `dlp eval --alias dlp-candidate --baseline dlp-primary`, then `dlp promote dlp-primary <model>`.
The mock provider is a deterministic stand-in so CI is free; it is not an LLM.

## Results (offline run, fixture data, mock model)

| Measure | Result |
|---|---|
| `dlp all` end to end | 10.1 s (build 6.3 s) |
| Data tests (dbt) | 22 of 22 pass |
| Knowledge graph | 1,125 instance triples, SHACL conforms (10 vendors, 10 datasets, 50 fields, 45 companies, 12 metrics, 18 data assets) |
| Eval gate (19 cases) | accuracy 1.0 · schema-valid 1.0 · grounding 1.0 · must-escalate recall 1.0 · simulated cost $0.016 |
| Context packet for a two-symbol, two-metric question | 212 tokens (cap 4,000) |
| Harbor's card panel, last 90 days | $11,096 spend, 14 queries → $792.56 per query (flagged) vs Northlight $9.54 |
| IV–HV spread test | correlation 0.39 over 2,860 observations — **on generated data; meaningless until `dlp fetch`** |
| Unit, layer-boundary, control, API/MCP, UI and end-to-end tests | 43 pass |

## The four layers

| Layer | Holds | Never holds |
|---|---|---|
| Ontology (`ontology/`) | classes and properties (OWL), the vocabulary (SKOS), SHACL shapes | vendors, companies, numbers |
| Knowledge graph (Oxigraph) | instances built from the catalog and warehouse, validated by SHACL | metric values |
| Semantic layer (`semantic/`, dbt + MetricFlow) | models, tests, metrics bound to concept IRIs | meaning, entitlements |
| Context layer (`context.py`) | one packet per question: entitled metrics + graph facts, ≤ 4k tokens | anything the firm may not send to AI |

Tests check each boundary (`tests/test_layers.py`). Diagrams and decisions: [docs/architecture.md](docs/architecture.md).

## Governance console

Every visit, model call, catalog write, approval, feed run and build is reported to the portfolio's
[governance console]({{SITE_URL}}/blog/governance-console/) — counts, hashes and flags only, never questions,
sources or answers. The console can switch the platform off; every model call then refuses with the reason. Set
`GOVERNANCE_URL` (and `GOVERNANCE_INGEST_TOKEN`); without it events go to `~/.ai-portfolio/governance/events.jsonl`.
`GOVERNANCE_TELEMETRY=off` disables it; `GOVERNANCE_FAIL_CLOSED=1` blocks runs when the console can't be reached.

## Requirements

**Functional**

| ID | Requirement |
|---|---|
| FR-1 | CRUD for vendors and datasets with custom fields and links to vendor sites, docs and listings |
| FR-2 | AI cataloguing from pages, cards, dictionaries and API specs, quoted, concept-mapped, human-approved |
| FR-3 | Search by concept, identifier, sector, economic factor, licence, delivery and price, with overlap |
| FR-4 | Profile and compare datasets; memo with alpha-use hypotheses from computed facts |
| FR-5 | Register free data or subscribe with a contract; licence rules per use |
| FR-6 | Entitlement-checked downloads and feeds; Dagster build of dbt → SHACL → graph |
| FR-7 | Spend, usage and ROI per firm and dataset; renewal and budget alerts |
| FR-8 | Impact analysis, substitutes, approved retirement with an archive record |
| FR-9 | Monetization assessment for data owners; operator-approved listing |

**Non-functional**

| ID | Requirement | Target | Status |
|---|---|---|---|
| NFR-1 | Offline, deterministic end to end | < 5 min | ✅ 10 s |
| NFR-2 | Every number from SQL, logged | 100% | ✅ grounding 1.0; SQL in run log |
| NFR-3 | Tenant isolation | no cross-firm rows | ✅ tested (store, API, feeds) |
| NFR-4 | Context packet small and entitled | ≤ 4k tokens | ✅ |
| NFR-5 | Graph only holds SHACL-valid data; ontology versioned | 0 violations to load | ✅ |
| NFR-6 | Cost per AI action; same code on AWS | < $0.05 | ✅ cap enforced / [AWS guide](docs/aws-native.md) |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Run a data marketplace: catalogue vendors and datasets, help buyers find, judge, license and pay for data, help owners decide whether to sell. Advisory AI; every write approved by a person. |
| **Not for** | Legal sign-off on licences, investment signals (alpha ideas are untested hypotheses), pricing commitments. |
| **Risk tier** | Medium — see [governance mapping](docs/governance.md) |
| **Owner** | Marketplace operator (business) · data platform (technical) · legal (licence decisions) |
| **Known limits** | Factor sensitivities are synthetic assumptions. Injection and PII screening are pattern-based. Three marketplace adapters and S3/SFTP feeds have not been run against real services. The mock model is not an LLM. |

## Layout

```
ontology/      dlp.ttl (classes, properties) · vocabulary.ttl (concepts, categories, sectors, factors) · shapes.ttl (SHACL)
semantic/      dbt project: staging → marts, 22 tests, semantic.yml (MetricFlow metrics → concept IRIs)
data/seed/     catalog.yaml (vendors, datasets, firms, contracts), vendor pages, dictionaries, owner samples
data/reference Hub snapshot, constituents fixture, recorded marketplace responses
src/dlp/       store · catalog · licensing · commerce · ontology · graph · semantic · context · search · assess
               lifecycle · monetize · marketplaces · ai (the one door to a model) · guardrails · mock · llm
               evals · api · mcp_server · orchestration (Dagster) · cli · ui · telemetry · demo
prompts/       five versioned prompts
evals/         golden_set.yaml (19 cases)
infra/aws/     Terraform starter: S3, Glue/Athena, Neptune, RDS, ECR, scoped task role, budget
```

## Configuration

| What | Where | Key |
|---|---|---|
| Switch model | `config/models.yaml` | `aliases.dlp-primary` (via `promote`) |
| Spend caps | `config/settings.yaml` | `cost.max_usd_per_run`, `cost.max_usd_per_action` |
| Context packet size | `config/settings.yaml` | `layers.context_max_tokens` |
| Licence rules | `config/settings.yaml` | `licensing.*` |
| Renewal alert window | `config/settings.yaml` | `contracts.renewal_alert_days` |
| Retirement threshold | `config/settings.yaml` | `lifecycle.retire_if_cost_per_query_above` |
| New concept or synonym | `ontology/vocabulary.ttl` | `skos:altLabel` |
| New metric | `semantic/models/marts/semantic.yml` | `metrics` with `meta.ontology_iri` |
| Custom fields | app → Manage catalog, or `POST /custom-fields` | — |

## Commands

| Command | Purpose |
|---|---|
| `dlp ui` | Streamlit app: pick a persona and a workflow → Run → result, four-layer trace, human step, eval, audit |
| `dlp all` / `dlp build` | full offline build (+ eval gate) |
| `dlp fetch` | real Hugging Face slices |
| `dlp search "<need>" --customer <id>` | AI data search |
| `dlp ask "<question>" --customer <id>` | answer through the context layer |
| `dlp extract <file> --url <source>` | draft catalog records; `dlp approvals`, `dlp approve <id> --reviewer <name>` |
| `dlp assess <id> [<id> …]` | memo, or a side-by-side comparison |
| `dlp licence --customer <id>` | licence verdict matrix |
| `dlp register` / `dlp subscribe` | acquire data |
| `dlp roi --customer <id>` · `dlp retire <id> [--substitute <id>]` | spend, ROI, retirement |
| `dlp monetize <company> <description.md> <sample.csv>` | data-owner assessment |
| `dlp marketplace "<query>" [--name huggingface --live]` | search marketplaces |
| `dlp metric atm_iv,put_call_ratio --by option_day__gics_sector --sql` | governed metrics and their SQL |
| `dlp graph [--dataset <id>] [--sparql "<q>"]` · `dlp ontology check|diff` | inspect the layers |
| `dlp eval` · `dlp promote` · `dlp models-check` · `dlp cost-report` | model lifecycle and cost |
| `dlp api` · `dlp api-token <customer|operator>` · `dlp mcp` | REST API, tokens, MCP server |
| `make dagster` | Dagster UI over the same assets |

## License

Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you reuse it (see
[NOTICE](NOTICE)). The Hugging Face datasets keep their own licences; vendors, firms, contracts and usage are synthetic.

## License

Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you reuse it (see [NOTICE](NOTICE)).
