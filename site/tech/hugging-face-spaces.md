---
title: Hugging Face Spaces
category: Infrastructure & delivery
vendor: Hugging Face
docs: https://huggingface.co/docs/hub/spaces
aliases: [Hugging Face Spaces]
summary: Hosted demo apps on the Hugging Face Hub — push a repo, get a running app and a URL.
---

# Hugging Face Spaces

Hugging Face Spaces hosts small web apps on the Hugging Face Hub: you push a Git repository and it builds and runs the
app at a public (or private) URL.

## What it is

A Space is a Git repository on the Hub with a `README.md` whose YAML header tells Hugging Face how to run it. The
common choices are a Gradio app or a Docker container; with the Docker option you supply a Dockerfile and can run
almost anything that listens on a port, including Streamlit or FastAPI.

Spaces start on a free CPU tier and can be moved to paid hardware, including GPUs. Secrets (such as model API keys)
are set in the Space settings and arrive as environment variables. Free Spaces go to sleep when idle and restart on
the next visit.

## Typical use cases

- Sharing a model or AI demo with people who won't install anything.
- Hosting a portfolio or conference demo without running servers.
- Internal prototypes in a private Space or organization.
- Pairing a demo with a model or dataset already on the Hub.
- Quick A/B demos of two prompts or models side by side.

## In AI work

Spaces is built for the "show, don't tell" stage of AI work: a reviewer clicks a link and uses the thing. For a
financial firm it is a place for demos on synthetic or public data — not for client data or anything entitled. The
useful habit is to make the demo run on a mock model by default, so a public link never spends tokens or exposes a
key, and to treat real-model runs as an opt-in configured through Space secrets.

## In this portfolio

- The projects can be deployed to Hugging Face Spaces as an alternative to the home server.
- That covers the Streamlit apps for projects such as [Alt-data vendor triage](../blog/posts/altdata-triage.md) and
  [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md).

- The primary demos run in [Docker](docker.md) on a home server; Spaces is the fallback.

## Pros and cons

| Pros | Cons |
|---|---|
| Push a repo, get a URL — no servers to run | Free Spaces sleep when idle; first visit waits for a cold start |
| Docker option runs most web stacks | Limited free CPU and memory; heavier apps need paid hardware |
| Secrets management built in | Not a fit for confidential data or regulated workloads |
| Natural home next to Hub models and datasets | Less control over networking, logging and uptime than your own host |

## Basic usage

The `README.md` header for a Docker Space that serves an app on port 8501:

```yaml
---
title: Vendor Triage Demo
sdk: docker
app_port: 8501
---
```

Commit it with a Dockerfile and push to the Space's Git remote; the Space builds and starts automatically.

## Documentation

[Hugging Face Spaces documentation](https://huggingface.co/docs/hub/spaces) — official, from Hugging Face.
