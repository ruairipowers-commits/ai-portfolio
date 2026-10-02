---
title: Apache Airflow
category: Orchestration & agents
vendor: Apache Software Foundation
docs: https://airflow.apache.org/docs/
aliases: [Apache Airflow, Airflow]
summary: "Workflow orchestrator: schedules and monitors pipelines defined as Python DAGs."
---

# Apache Airflow

Apache Airflow schedules, runs and monitors data pipelines that you define in Python as directed acyclic graphs (DAGs).

## What it is

Airflow is an open-source project of the Apache Software Foundation. A DAG is a Python file that declares tasks and their dependencies plus a schedule; the scheduler decides what should run, executors run the tasks, and a web UI shows every run, its logs and its state. Retries, timeouts, backfills and alerting on failure are built in.

Airflow orchestrates; it isn't meant to process data itself. Tasks typically call out to the systems that do the work — run dbt, query a warehouse, call an API — and Airflow records whether each step succeeded and when. The TaskFlow API lets you write tasks as decorated Python functions and pass small results between them.

It is a multi-component system (scheduler, metadata database, web server, workers), so running it yourself takes some operations effort. Managed options exist; on AWS it is Amazon MWAA.

## Typical use cases

- Nightly and intraday batch pipelines with dependencies.
- Running dbt builds on a schedule and alerting on test failures.
- File and vendor-feed ingestion with retries.
- Time-boxed monitoring jobs (for example, every few minutes in a close window).
- Backfilling historical data after a logic change.

## In AI work

Airflow is a good home for AI steps that run on a schedule rather than on request: a DAG computes the facts with SQL, checks them, and only then calls a model to explain or summarize, with each step logged and retryable. Keeping the LLM call as one task among several means a model outage fails one task visibly instead of silently corrupting a pipeline, and scheduled evals or re-embedding jobs fit the same pattern.

## In this portfolio

- [EOD heartbeat](../blog/posts/eod-heartbeat.md): an Airflow DAG runs every 5 minutes from 17:00 to 21:00 ET; [dbt](dbt.md)-postgres models find end-of-day breaks and an LLM explains each one with citations from [pgvector](pgvector.md). The AWS path runs it on MWAA.

## Pros and cons

| Pros | Cons |
|---|---|
| Pipelines are Python code under version control | Several components to run and upgrade |
| Retries, backfills, SLAs and a run-history UI built in | Scheduler latency makes it a poor fit for real-time work |
| Large set of provider integrations | Passing data between tasks is limited; use external storage |
| Managed on AWS (MWAA) and elsewhere | Local development and testing take setup |

## Basic usage

A minimal DAG with two dependent tasks using the TaskFlow API (Airflow 3 import shown; Airflow 2 uses `from airflow.decorators import dag, task`):

```python
from datetime import datetime

from airflow.sdk import dag, task


@dag(schedule="*/5 17-20 * * 1-5", start_date=datetime(2026, 1, 1), catchup=False)
def eod_check():
    @task
    def find_breaks() -> int:
        return 3  # e.g. run dbt and count failing rows

    @task
    def report(n: int) -> None:
        print(f"{n} breaks found")

    report(find_breaks())


eod_check()
```

## Documentation

[Apache Airflow documentation](https://airflow.apache.org/docs/) — official, from the Apache Software Foundation.
