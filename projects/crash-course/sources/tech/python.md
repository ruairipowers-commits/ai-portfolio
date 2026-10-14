---
title: Python
category: Languages
vendor: Python Software Foundation
docs: https://docs.python.org/3/
aliases: [Python]
summary: General-purpose language and the default for data, ML and LLM application code.
---

# Python

Python is the language most data and AI work is written in, and the default for every project in this portfolio except one MCP server.

## What it is

Python is an open-source, general-purpose programming language maintained by the Python Software Foundation and its core developers. It is interpreted, dynamically typed (with optional type hints that tools such as mypy and Pydantic can check or enforce), and ships with a large standard library — `sqlite3`, `json`, `pathlib`, `datetime` and more are there before you install anything.

Its strength for a data team is less the language itself than the ecosystem around it: pandas, Polars, DuckDB, dbt, Airflow, FastAPI, Streamlit and every major model provider SDK are Python-first. Most new data and AI libraries publish a Python package before anything else.

The trade-off is runtime speed and packaging. Pure-Python loops are slow, so heavy lifting is pushed down into SQL engines or compiled libraries, and dependency management needs discipline (pinned versions, virtual environments, a lock file or constraints).

## Typical use cases

- Data pipelines and glue code between systems.
- Analytics and research notebooks.
- Web APIs and internal tools (FastAPI, Streamlit).
- Orchestration code (Airflow DAGs are Python files).
- Test suites and CI scripts.
- Calling model provider APIs and validating their output.

## In AI work

Almost every LLM SDK, agent framework (LangGraph, for example) and evaluation tool is Python-first, so Python is where prompts, model calls, retrieval, output validation and evals tend to live. A pattern that works well: let SQL or dbt compute the numbers, use Python to assemble context, call the model through one adapter, and validate the response with a typed schema before anything downstream reads it.

## In this portfolio

- Every project is a Python package installed with `pip install -e ".[dev]"`, with a CLI, a Streamlit app and pytest tests — see [Alt-data vendor triage](../blog/posts/altdata-triage.md) and [Research Q&A](../blog/posts/research-qa-rag.md).
- The [EOD heartbeat](../blog/posts/eod-heartbeat.md) Airflow DAG and the [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md) (LangGraph) are Python; that agent's MCP tool server is the one piece in [TypeScript](typescript.md).
- The [governance console](../blog/posts/governance-console.md) is a Python FastAPI service.

## Pros and cons

| Pros | Cons |
|---|---|
| Largest data/ML/LLM library ecosystem | Slow for CPU-bound pure-Python code |
| Readable; easy for analysts and engineers to share code | Packaging and environment management take discipline |
| Optional type hints catch a class of bugs early | Dynamic typing lets errors reach runtime without tests |
| Batteries included (`sqlite3`, `json`, `csv`, `logging`) | Concurrency model (GIL, async) has sharp edges |

## Basic usage

A small script that reads a CSV with the standard library and totals a column:

```python
import csv
from collections import defaultdict

totals = defaultdict(float)
with open("trades.csv", newline="") as f:
    for row in csv.DictReader(f):
        totals[row["desk"]] += float(row["notional"])

for desk, notional in sorted(totals.items()):
    print(f"{desk}: {notional:,.0f}")
```

## Documentation

[Python documentation](https://docs.python.org/3/) — official, from the Python Software Foundation.
