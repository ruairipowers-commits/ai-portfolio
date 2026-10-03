---
date: 2026-10-02
slug: eod-heartbeat
short: "EOD heartbeat"
categories: [Operations, RAG & retrieval, Data quality]
tags: [airflow, dbt, postgres, pgvector, runbooks, alerting, degraded mode, retention]
---

# The 7 p.m. NAV break, explained from your own runbooks

Every fund has an evening where NAV is due, a file is late or a position doesn't match the prime broker, and the
on-call engineer is searching Confluence and Slack for the time this happened before. This project finds those
breaks with SQL, explains each one from the firm's own runbooks and incident history with citations, and never
touches the pipeline itself.

<!-- more -->

**Repo:** [github.com/{{GITHUB_OWNER}}/eod-heartbeat](https://github.com/{{GITHUB_OWNER}}/eod-heartbeat) · runs offline in 5 minutes, no API keys, no Docker ·
**Live demo:** [try it]({{DEMOS_URL}}/eod-heartbeat/) ·
**Try it:** in *Try to break it*, change a runbook step to "rerun with --force" and run the check again. ·
**Stack:** Python, Airflow, dbt-postgres, Postgres + pgvector, Streamlit, Anthropic / OpenAI / Bedrock via aliases, Terraform (MWAA, RDS, SNS)

## The business problem

End-of-day is where a fund's data platform earns its keep. Prices, FX, trades, prime-broker positions, corporate
actions and risk P&L all have to land and agree before NAV is signed off. When they don't, the cost isn't the
break itself; it's the hour it takes to work out which of thirty possible causes it is, at the end of a long day,
often by someone who didn't build that feed.

The knowledge exists. It's in runbooks nobody opens under pressure and in last year's incident write-ups. Anyone
who has carried an EOD pager knows the pattern: the engineer who knows the answer is on holiday, and the answer was
in an incident ticket all along.

## What the workflow does

An Airflow DAG ticks every five minutes from 17:00 to 21:00 ET. Each heartbeat:

1. **Loads** whatever has landed.
2. **Builds dbt** on Postgres with 28 tests as a gate. One `breaks` model covers file SLAs, positions vs the prime
   broker, P&L that doesn't explain, stale prices, price and FX outliers and duplicate trades. Detection is SQL —
   the model never decides whether a break exists.
3. **Retrieves** the runbook sections and past incidents for each break from pgvector, filtered by break type.
4. **Explains** each break — likely cause and next step — with a model chosen by alias, inside a per-run budget.
5. **Checks** the explanation in code: it must cite a retrieved runbook section, the step must come from that
   runbook, unsafe steps are blocked, and critical breaks always go to a person.
6. **Alerts** once per break and asks the on-call engineer for a 👍/👎.

Ten synthetic business days carry the classic failures: a late price file, a stock split the prime broker applied but
we didn't, a missing FX file, a duplicated OMS row, a stale price, an FX rate off by a factor of ten, and a trade
booked after the prime-broker cutoff. The offline run gets:

| Metric | Result | Gate |
|---|---|---|
| Breaks detected (12 expected over 10 days) | recall 1.00 · precision 1.00 | 1.00 / 1.00 |
| Explanations citing an acceptable runbook | 1.00 | ≥ 0.90 |
| Explanations citing ≥ 1 retrieved runbook section | 1.00 | 1.00 |
| Critical breaks routed to a human (and only those) | 1.00 | — |
| Unsafe steps shown to on-call | 0 | 0 |
| Cost for 12 explanations (simulated pricing) | $0.015 | ≤ $0.25 |

These come from a deterministic mock explainer that picks the best-matching runbook and incident by break type. They
show that detection, retrieval and the controls work; they don't measure how well a real model writes an
explanation. The eval gate is how you'd find out before switching.

## Requirements

**Functional**

| ID | Requirement |
|---|---|
| FR-1 | Detect late/missing files and reconciliation breaks against thresholds |
| FR-2 | Retrieve relevant runbook sections and similar past incidents |
| FR-3 | Likely cause + next step with citations; never an action outside the runbook or a forced rerun |
| FR-4 | Alert once per break and capture on-call feedback |
| FR-5 | NAV sign-off status per business date |

**Non-functional**

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Alert latency | within one 5-minute tick of an SLA breach |
| NFR-2 | Grounding | every explanation cites ≥ 1 retrieved runbook section |
| NFR-3 | Local run | no Docker (embedded Postgres); full stack via docker compose |
| NFR-4 | Determinism | detection is SQL; the model only explains |
| NFR-5 | Cost | per-run budget; repeat ticks reuse explanations |

## Architecture

--8<-- "projects/eod-heartbeat/docs/architecture.md:flow"

### Why this architecture

--8<-- "projects/eod-heartbeat/docs/architecture.md:decisions"

The trade-off worth dwelling on is **RAG, not an agent**. An agent that can run diagnostic queries would sometimes
find the cause faster. It would also be an autonomous process with database access running at the most sensitive
hour of the day. Here the investigation that matters — does the break exist, how big is it — is deterministic SQL
that someone reviewed in a pull request, and the model only does what it's good at: connecting a pattern to the
paragraph of the runbook that covers it.

The second is **one Postgres for everything**: raw data, dbt marts, the audit trail and the vectors. The knowledge
base is a few hundred chunks; a separate vector database would be another system to secure and back up for no gain.
Locally, `pgserver` starts a real Postgres 16 with pgvector from a pip wheel, so the repo runs without Docker and
the SQL is the same as on RDS.

## Governance in practice

All 30 controls are mapped in the [governance file](https://github.com/{{GITHUB_OWNER}}/eod-heartbeat/blob/main/docs/governance.md).
The deep dives:

**DATA-05 · Corpus hygiene.** *Risk:* a runbook changes and nobody can tell which version an explanation relied on.
*Handled:* runbooks are chunked by section (`RB-04#steps`), re-indexed incrementally by file hash, and every
explanation stores the knowledge-base version and the hash of the cited text. *Knob:* `kb.*`. *Not built:* a runbook
approval workflow before re-index.

**OBS-02 · Traceability.** Every explanation must cite runbook chunks that were actually in its context — checked in
code — and the app shows the cited text next to the advice. *Knob:* `policy.min_runbook_citations`.

**MODEL-05 · Resilience.** *Risk:* a provider outage at 7 p.m. hides a break. *Handled:* retries, then a cheaper
fallback model, then **degraded mode**: the break is still detected and alerted with its runbook steps, just without
the prose. The app has a switch that simulates the outage. The eval gate fails on explanation rate when every model is
down, while detection still passes — which is the right way round.

**HITL-03 · Feedback.** On-call rates each explanation; "wrong" ones become golden-set cases or runbook fixes.

**OBS-03 · Retention.** `eodhb retention` archives audit rows past the retention period to JSON Lines with a SHA-256
manifest before deleting (dry run by default); the AWS path writes to S3 with Object Lock.

And one SEC-02 case I like: runbook RB-10 ships with a paragraph telling the AI to "auto-rerun with --force". It is
quarantined at index time, and even if it got through, the unsafe-action policy would block the step and send the
break to a person.

### Configuring it

| What | File | Key |
|---|---|---|
| Break thresholds, PB cutoff, NAV sign-off time | `config/settings.yaml` | `detection.*`, `nav_signoff_time` |
| Unsafe-action patterns, critical routing | `config/settings.yaml` | `policy.*` |
| Knowledge-base chunking, quarantine, redaction | `config/settings.yaml` | `kb.*` |
| Explainer and fallback models | `config/models.yaml` | `aliases` (via `eodhb promote`) |
| Budget, eval gates, retention | `config/settings.yaml` | `cost.*`, `eval.*`, `governance.*` |

## Taking it to AWS

The same DAG runs on **MWAA**, the database moves to **RDS Postgres with pgvector**, the explainer to **Bedrock**,
and alerts go to **SNS**. The retention archive lands in S3 with Object Lock. The Terraform starter creates those
pieces with least-privilege roles and a budget alert; it has not been applied to a live account. See
[docs/aws-native.md](https://github.com/{{GITHUB_OWNER}}/eod-heartbeat/blob/main/docs/aws-native.md).

## What I'd do next / limits

- **A real explainer.** Run the eval with Claude or Bedrock; the mock is rule-based.
- **NAV-relative thresholds.** Today they are absolute; a $50k break means different things for different funds.
- **Runbook quality bounds explanation quality.** The weekly review of 👎 explanations is as much a runbook process as
  an AI one.
- **Deny-lists are not proofs.** The unsafe-action patterns catch the obvious cases; the real safety is that the model
  has no way to act.
- Every heartbeat is reported to the [governance console](governance-console.md), which can switch the workflow off;
  the DAG task then fails visibly with the reason.

---

*Part of my [AI workflow portfolio](../../index.md). Governance controls referenced here are
defined in [How I govern AI workflows](governance.md).*
