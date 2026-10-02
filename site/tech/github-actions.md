---
title: GitHub Actions
category: Infrastructure & delivery
vendor: GitHub
docs: https://docs.github.com/en/actions
aliases: [GitHub Actions]
summary: CI/CD built into GitHub — YAML workflows that run on pushes, PRs and schedules.
---

# GitHub Actions

GitHub Actions runs build, test and deploy workflows directly from a GitHub repository, triggered by pushes, pull
requests, schedules or manual runs.

## What it is

A workflow is a YAML file in `.github/workflows/`. It names the events that trigger it, then lists jobs; each job runs
on a runner (a GitHub-hosted VM or your own machine) and is a sequence of steps — shell commands or reusable "actions"
published by GitHub and the community, such as `actions/checkout` or `actions/setup-python`.

Because it lives next to the code, the CI definition is versioned and reviewed like everything else. Results show up
on the pull request, and branch protection can require a green run before merge.

Self-hosted runners let a job execute inside your own network — useful when a deploy step needs to reach a machine that
is not on the public internet.

## Typical use cases

- Running unit tests and linters on every pull request.
- Building and publishing container images or Python packages.
- Building a static documentation site and publishing it to GitHub Pages.
- Scheduled jobs (nightly data checks, dependency updates).
- Gated deployment: deploy only after tests pass on the main branch.

## In AI work

CI is where an AI project's quality gates become non-negotiable. The useful pattern is to run the whole pipeline
offline against a mock model on every change: schema validation of model output, data-quality tests, and a small
evaluation set with a pass threshold. If the eval or a guardrail test regresses, the merge is blocked — the same
discipline you would apply to a pricing library.

Real model calls generally stay out of default CI (cost, flakiness, secrets); when they are needed, they belong in a
separately triggered workflow with keys held in repository secrets.

## In this portfolio

- CI for the portfolio is GitHub Actions.
- The blog is built with [Material for MkDocs](mkdocs-material.md) and published to GitHub Pages.
- Example: [Alt-data vendor triage](../blog/posts/altdata-triage.md) has GitHub Actions CI alongside its 14 dbt tests
  and offline mock model.

## Pros and cons

| Pros | Cons |
|---|---|
| No separate CI server; config lives in the repo | Ties your delivery pipeline to GitHub |
| Large marketplace of reusable actions | Third-party actions are a supply-chain risk — pin them to a commit SHA |
| Self-hosted runners for private networks | YAML workflows get hard to debug as they grow |
| Results integrate with PRs and branch protection | Hosted-runner minutes and storage are metered on private repos |

## Basic usage

A minimal workflow that runs Python tests on every push and pull request:

```yaml
name: ci
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest -q
```

## Documentation

[GitHub Actions documentation](https://docs.github.com/en/actions) — official, from GitHub.
