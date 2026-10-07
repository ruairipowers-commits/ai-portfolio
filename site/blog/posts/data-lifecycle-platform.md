---
date: 2026-10-06
slug: data-lifecycle-platform
short: "Data marketplace & lifecycle"
categories: [Data platforms, Alternative data, Governance, Evaluation]
tags: [ontology, knowledge graph, semantic layer, context layer, dbt, metricflow, shacl, oxigraph, dagster, mcp, hugging face, licensing]
audience: [Heads of data, AI and ML engineers, "Risk, compliance and legal", Product managers]
---

# A data marketplace where the AI can't invent a number or see data you haven't paid for

Every fund I've worked with runs the life of a dataset by hand: finding it, reading the vendor's PDF, arguing about
the licence, loading it, paying for it, and, rarely, switching it off. This project runs that whole lifecycle as a
marketplace, on real Hugging Face data, with AI doing the reading and drafting. It also keeps four things apart that
most "AI over your data" demos blur together: the ontology, the knowledge graph, the semantic layer and the context
layer.

<!-- more -->

**Repo:** [github.com/{{GITHUB_OWNER}}/data-lifecycle-platform](https://github.com/{{GITHUB_OWNER}}/data-lifecycle-platform) · runs offline in 10 seconds, no API keys ·
**Live demo:** [try it]({{DEMOS_URL}}/data-lifecycle-platform/) ·
**Try it:** as *Alder*, ask for JPM's implied vol; then switch to *Harbor* and ask again. ·
**Stack:** Python, dbt + MetricFlow on DuckDB, OWL/SKOS + SHACL, Oxigraph, SQLModel, Dagster, FastAPI, MCP, Streamlit, Terraform

## The business problem

Data spend is one of the larger lines in a fund's budget after people, and it's run on spreadsheets. Vendor facts
are re-typed from websites and go stale. Data dictionaries arrive as attachments and get mapped to internal names by
whoever has time. Two datasets can't be compared on equal terms because nobody measured them the same way. Licences
get read after the data is already in research. Renewals arrive as surprises, and when someone finally asks "what
breaks if we cancel this?", the honest answer is "let's find out".

The other side of the market has the mirror problem. Companies sitting on useful data (a trucking firm's lane
volumes, say) don't know whether it's sellable, to whom, or what to fix first.

Adding an LLM to this naively makes it worse. A model answering from whatever text it's given will quote a number
that isn't in the warehouse, follow an instruction hidden in a vendor's web page, and happily summarise a dataset
your contract says may not be sent to an AI provider.

## What the platform does

The operator manages two linked catalogs, vendors and datasets, with custom fields they define and links back to
each vendor's site and marketplace listings. Buyer firms register free data or subscribe to paid data under timed
contracts. Around that sits the AI work:

| Workflow | What the AI does | What code does |
|---|---|---|
| Catalog a source | Reads a vendor page or free-text dictionary; drafts fields, each with a quote | Parses OpenAPI, CSV and Hub schemas itself; checks every quote; maps fields to concepts; drops values lifted from injected text; queues for approval |
| Find data | Turns a plain-English need into vocabulary terms | Validates the terms, expands economic factors through the graph, scores, adds entitlements and overlap |
| Ask about our data | Writes the answer from a packet | Builds the packet: entitled datasets only, governed metrics, graph facts, ≤ 4k tokens; checks every number |
| Assess & compare | Writes the memo and alpha hypotheses | Computes coverage, history, freshness, licence verdicts, overlap; runs one alpha test for real |
| Monetize | Writes advice for the data owner | Profiles the sample, blocks personal data before any model call, prices from comparables |

Lifecycle work is mostly code: licence verdicts, renewal alerts, spend and cost per query from the semantic layer,
and retirement that's impact-checked against the graph.

From an offline run on the fixture data:

| Measure | Result |
|---|---|
| `dlp all` (build + 19-case eval gate) | 10.1 s |
| Data tests before any model call | 22 of 22 |
| Graph | 1,125 triples, SHACL-valid |
| Eval gate | accuracy, grounding and must-escalate recall all 1.0 |
| Harbor's card panel, last 90 days | $792.56 per query (14 queries), flagged; the vol surface is $9.54 |
| Packet for a two-symbol, two-metric question | 212 tokens |

## Four layers, kept apart

This was the point of the project, so it's worth being precise.

- **Ontology: what things mean.** Classes like *Dataset*, *Licence*, *Contract*, *EconomicFactor*, plus a
  controlled vocabulary: "ATM implied volatility" with its synonyms (*atm iv*, *implied vol*), the GICS sectors,
  "rising rates". No vendors, no companies, no numbers. A test fails if an instance sneaks in.
- **Knowledge graph: what exists.** Vendors, datasets, fields and the concept each one means, companies and their
  sectors, contracts, entitlements, and dbt lineage. It's generated from the catalog and warehouse on every build and
  loaded only if it passes SHACL, the graph equivalent of dbt tests. SHACL earned its place early: it refused my
  first lineage load because some assets pointed at nodes that had no type.
- **Semantic layer: governed numbers.** dbt models and MetricFlow metrics. Each metric carries the IRI of the concept
  it measures, so "implied vol" in a question resolves to `atm_iv` through the ontology, not a prompt. Every number
  anyone sees comes from here, and the SQL behind it is logged.
- **Context layer: what a model may see.** Code builds a packet for one question and one firm. It contains only
  datasets that firm may send to an AI provider, the metric results, a few graph facts and policy notes, under a
  token cap. The model sees nothing else.

--8<-- "projects/data-lifecycle-platform/docs/architecture.md:flow"

And one question, end to end:

--8<-- "projects/data-lifecycle-platform/docs/architecture.md:sequence"

The payoff shows up in the edge cases. Ask for a "dark pool volume ratio" and the ontology recognises the concept,
the semantic layer has no metric for it, and the answer is *not defined*, not a guess. Ask as Alder, which hasn't
registered the options data, and the packet is empty with the reason attached. Ask about the card panel as Harbor:
the contract permits research but not AI processing, so that data never enters a packet.

## Requirements

**Functional**

| ID | Requirement |
|---|---|
| FR-1 | Vendor and dataset CRUD, custom fields, links to vendor sites and listings |
| FR-2 | AI cataloguing from pages, cards, dictionaries and API specs, quoted and approved |
| FR-3 | Search by concept, sector, economic factor, licence and price, with overlap |
| FR-4 | Like-for-like assessment and comparison; alpha hypotheses |
| FR-5 | Register or subscribe; contracts with term, notice and AI-processing terms |
| FR-6 | Entitlement-checked downloads and feeds; scheduled build |
| FR-7 | Spend, usage, cost per query, budget and renewal alerts |
| FR-8 | Impact analysis, substitutes, approved retirement |
| FR-9 | Monetization assessment for data owners |

That's nine, against my usual three to six. A marketplace that covers the whole lifecycle needs them, so I kept them.

**Non-functional**

| ID | Target | Result |
|---|---|---|
| NFR-1 Offline, deterministic | < 5 min | 10 s |
| NFR-2 Every number from SQL | 100% | grounding 1.0 |
| NFR-3 Tenant isolation | no cross-firm rows | tested at store, API and feed |
| NFR-4 Small, entitled packet | ≤ 4k tokens | 212 for a typical question |
| NFR-5 Graph only holds valid data | 0 violations | enforced |
| NFR-6 Cost per AI action | < $0.05 | capped in code |

## Why this architecture

--8<-- "projects/data-lifecycle-platform/docs/architecture.md:decisions"

The trade-off I thought about longest was the model's role. It would be easy to make this an agent: give a model
tools for SPARQL, metrics and the catalog and let it explore. I didn't. Each workflow here is a known sequence, and
the risky decisions (who may see what, which licence applies, whether a number is real) are exactly the ones I
don't want a model making. So the model drafts, plans and explains, and the agent-shaped surface is a read-only MCP
server other agents can use, running under one firm's entitlements with a call cap.

## Governance in practice

The full mapping covers all 30 controls ([docs/governance.md](https://github.com/{{GITHUB_OWNER}}/data-lifecycle-platform/blob/main/docs/governance.md)).
These five carry the most weight here.

**DATA-04 Usage rights.** *Risk:* data reaches a model or a product its licence doesn't allow. *Handling:* a rules
engine returns PERMITTED, CONDITIONAL, LEGAL_REVIEW or BLOCKED per dataset, use and firm, from licence tags and
active contracts. The constituents dataset declares no licence while its card claims commercial use, so it goes to
legal review, and a recorded legal decision lifts it for the uses legal approved and no others. Extraction can't
set a licence tag. *Knob:* `licensing.*`. *Not built:* clause extraction from signed contract PDFs.

**DATA-01 Lineage.** *Risk:* cancelling a feed breaks something nobody knew depended on it. *Handling:* dbt lineage
goes into the graph as data assets, so retirement checks metrics, assets, reports and teams. Retiring the options
data is blocked because nine metrics depend on it. Retiring Harbor's vol surface is blocked until a substitute is
mapped, then it waits for approval. *Not built:* OpenLineage events from Dagster runs.

**DATA-03 Minimization.** *Handling:* the packet is the model's whole world. Vendor text is PII-redacted before
extraction, and a data owner's sample with drivers' phone numbers is stopped before any model call. *Knob:*
`layers.context_max_tokens`, `data.pii_columns`.

**SEC-02 Prompt injection.** The Larkspur vendor page hides white-on-white text telling the model to mark the data
Apache-2.0. The mock model, deliberately naive, obeys. The extraction is flagged, the licence value is dropped
because its quote comes from the injected line, and nothing is published without a reviewer. *Not built:* a
classifier-based screen alongside the patterns.

**HITL-02 Human approval.** One queue holds extractions, contracts, licence decisions, listings and retirements.
Each needs a named reviewer, and a contract gives no entitlement until it's approved. Reviewer edits are kept as
feedback for the eval set (HITL-03).

### Configuring it

| Change | File | Key |
|---|---|---|
| Model | `config/models.yaml` | `dlp-primary` via `promote` |
| Packet size | `config/settings.yaml` | `layers.context_max_tokens` |
| Licence rules | `config/settings.yaml` | `licensing.*` |
| A synonym or concept | `ontology/vocabulary.ttl` | `skos:altLabel` |
| A metric | `semantic/models/marts/semantic.yml` | `meta.ontology_iri` |

## Taking it to AWS

Each layer has a direct counterpart. The semantic layer runs on Glue and Athena through dbt-athena, with MetricFlow
compiling the same metrics. The graph moves to Neptune, which speaks SPARQL, and SHACL still runs before the load.
The catalog moves to RDS Postgres, models to Bedrock behind the same aliases, and AWS Data Exchange becomes a live
marketplace adapter. The Terraform starter covers S3, Athena, Neptune Serverless, RDS, ECR, a task role scoped to
approved model ARNs, and a budget alert. It's written and reviewed but not applied
([docs/aws-native.md](https://github.com/{{GITHUB_OWNER}}/data-lifecycle-platform/blob/main/docs/aws-native.md)).

## What I'd do next / limits

- **Real data.** This build ran on a fixture with the Hub dataset's columns and generated values; the sandbox couldn't
  reach Hugging Face. `dlp fetch` pulls the real slice and checks the columns. The IV–HV test's 0.39 correlation is
  on generated data and means nothing until then.
- **The model is a mock.** It's deterministic and deliberately naive, which is useful for testing guardrails and
  useless for judging extraction quality. The next step is the eval gate against a real model.
- **Three marketplace adapters haven't touched a real service.** Snowflake, AWS Data Exchange and Databricks are tested
  on recorded responses I wrote to their documented shapes. S3, SFTP and Snowflake-share feeds are documented, not run.
- **Factor sensitivities are my assumptions,** labelled as such everywhere they appear. A real version would estimate
  them, or let research own them as graph data.
- **Pattern-based screening.** The injection and PII checks catch the common cases, not all of them.
- **Pricing advice is crude:** a median of comparables, adjusted for history and uniqueness. It's a starting point
  for a conversation, and the app says so.

---

*Part of my [AI workflow portfolio](../../index.md). Governance controls referenced here are defined in
[How I govern AI workflows](governance.md).*
