---
title: Ollama
category: Model providers
vendor: Ollama
docs: https://docs.ollama.com/
aliases: [Ollama]
summary: Run open-weight language models locally behind a simple CLI and HTTP API.
---

# Ollama

Ollama downloads and runs open-weight language models on your own machine and serves them through a simple command
line and local HTTP API.

## What it is

Ollama wraps model download, quantized weights and an inference runtime into one install. `ollama pull` fetches a
model from its library, `ollama run` opens a chat in the terminal, and a background server exposes an HTTP API on
`localhost:11434` for generation, chat and embeddings.

It runs on CPU and uses a GPU when one is available. Models are referenced by name and tag, and a `Modelfile` lets you
pin a system prompt and parameters as a named variant. The API also has an OpenAI-compatible endpoint, so many existing
clients can point at it with a base-URL change.

## Typical use cases

- Local development and testing against a real model with no API key or per-token cost.
- Workloads where data must not leave the machine or network.
- Generating embeddings for a small search index.
- Comparing open models on your own prompts before choosing one.
- Offline demos.

## In AI work

For a firm that is cautious about sending research or client data to a third-party API, a local model is the obvious
first step: nothing leaves the box. The trade-off is quality and speed — small open models on modest hardware are
well behind frontier hosted models on harder reasoning tasks, so they suit narrower jobs such as classification,
summarization of short text, query rewriting and embeddings.

Because Ollama speaks an OpenAI-compatible API, it slots into a model registry as one more provider alias, which makes
side-by-side evaluation against hosted models straightforward.

## In this portfolio

- **Planned:** a blog search/chat assistant that uses Ollama to run local open models on the home server.
- The existing projects default to an offline mock model; see [Alt-data vendor triage](../blog/posts/altdata-triage.md)
  for the model registry pattern a local provider would plug into.

## Pros and cons

| Pros | Cons |
|---|---|
| Data stays on your hardware | Open local models trail frontier hosted models on hard tasks |
| No per-token cost once hardware is paid for | Speed depends heavily on GPU and memory |
| One-command install and model pull | You own uptime, patching and capacity |
| OpenAI-compatible API eases integration | Model licences vary — check each one for commercial use |

## Basic usage

Pull a model and call the local API:

```bash
ollama pull llama3.2
curl http://localhost:11434/api/generate -d '{
  "model": "llama3.2",
  "prompt": "Summarize: settlement failed due to missing SSI.",
  "stream": false
}'
```

## Documentation

[Ollama documentation](https://docs.ollama.com/) — official, from Ollama. Source:
[github.com/ollama/ollama](https://github.com/ollama/ollama).
