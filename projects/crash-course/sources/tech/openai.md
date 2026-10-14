---
title: OpenAI API
category: Model providers
vendor: OpenAI
docs: https://developers.openai.com/api/docs
aliases: [OpenAI]
summary: OpenAI's API for its GPT models — Responses API, tool calling, structured outputs.
---

# OpenAI API

The OpenAI API is OpenAI's HTTP interface to its GPT models, with official SDKs including Python and JavaScript.

## What it is

The main entry point for new work is the Responses API: you send input (text, images, prior turns, tool definitions) to a named model and get back a response, with `output_text` as the convenient plain-text view. The platform also covers tool and function calling, structured outputs (responses constrained to a JSON Schema you supply), embeddings, and other modalities.

Authentication is an API key, usually read from the `OPENAI_API_KEY` environment variable. OpenAI models are also offered through some cloud platforms; [Amazon Bedrock](bedrock.md), for example, lists OpenAI models and an OpenAI-compatible Chat Completions API.

## Typical use cases

- Summarizing and drafting from structured inputs.
- Extracting entities and fields into JSON.
- Tool-calling agents that look up data before answering.
- Embeddings for semantic search.
- Classification and routing of incoming text.

## In AI work

Most firms end up with more than one model provider, for cost, capability or resilience. The practical pattern is to keep provider SDK calls behind one interface: an alias such as `memo-drafter` maps to a provider and model ID in config, every call is logged with tokens and cost, and the output is validated the same way regardless of who produced it. Structured outputs reduce parsing failures, but you still validate on your side — a valid shape is not a correct answer.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md): OpenAI is one of the providers behind the model registry, selected by alias alongside a mock, [Anthropic](anthropic.md) and [Bedrock](bedrock.md). The default is the offline mock; [Pydantic](pydantic.md) validates the output.

## Pros and cons

| Pros | Cons |
|---|---|
| Broad model range and modalities | Hosted API: data leaves your network |
| Structured outputs against a JSON Schema | Model names and defaults change; pin and re-test |
| Mature SDKs and wide third-party support | Per-token cost needs monitoring at volume |
| Embeddings and generation from one provider | Rate limits and quotas need handling in batch jobs |

## Basic usage

Install with `pip install openai`, set `OPENAI_API_KEY`, then:

```python
from openai import OpenAI

client = OpenAI()

response = client.responses.create(
    model="gpt-6-astra",
    input="Summarize this vendor note in three bullets: ...",
)

print(response.output_text)
```

## Documentation

[OpenAI API documentation](https://developers.openai.com/api/docs) — official, from OpenAI. See also the [developer quickstart](https://developers.openai.com/api/docs/quickstart).
