---
title: Prefect
category: Orchestration & agents
vendor: Prefect Technologies
docs: https://docs.prefect.io/
aliases: [Prefect]
summary: Python-native workflow orchestrator — decorate functions as flows and tasks, then schedule and watch them.
---

# Prefect

Prefect turns ordinary Python functions into scheduled, retried, observable workflows.

## What it is

Prefect is an open-source orchestrator from Prefect Technologies. You mark functions with `@flow` and `@task`; Prefect
adds retries, caching, logging, run history and a UI, and `serve()` runs them on intervals or cron schedules from a
single process. Larger setups add work pools and workers; Prefect Cloud is the hosted option.

## Typical use cases

- Scheduled data refreshes and API pulls.
- Python pipelines that need retries and a run history without a heavy platform.
- Event- or schedule-triggered reports.

## In AI work

A flow is a natural boundary for an AI step: retries for flaky providers, a record of every run, and a schedule that
can be paused when governance switches the workflow off.

## In this portfolio

- [Launch tracker](../personal/posts/launch-tracker.md): an hourly refresh of launch data (within Launch Library 2's
  15-requests-an-hour limit) followed by a "what changed" summary, and a Monday digest. The same functions run from
  the CLI and from the demo's plain loop, so nothing depends on Prefect being installed.
  [Dagster](dagster.md) and [Airflow](airflow.md) are used elsewhere for comparison.

## Pros and cons

| Pros | Cons |
|---|---|
| Plain Python; very little ceremony | Less asset/lineage modelling than Dagster |
| `serve()` gives schedules without extra infrastructure | Scaling out means work pools and workers |
| Retries, caching and a UI built in | The 2.x → 3.x changes mean older examples mislead |

## Basic usage

```python
from prefect import flow, task, serve

@task(retries=2, retry_delay_seconds=300)
def refresh():
    ...

@flow(log_prints=True)
def refresh_launches():
    print(refresh())

serve(refresh_launches.to_deployment(name="hourly", interval=3600))
```

## Documentation

[Prefect documentation](https://docs.prefect.io/) — official, from Prefect Technologies.
