---
title: Anthropic Claude API
category: Model providers
vendor: Anthropic
docs: https://platform.claude.com/docs/en/home
aliases: [Anthropic, Claude]
summary: Anthropic's API for the Claude models — messages, tool use, structured outputs.
---

# Anthropic Claude API

The Claude API is Anthropic's HTTP interface to its Claude family of language models, with official SDKs for Python, TypeScript and other languages.

## What it is

The core is the Messages API: you send a list of messages (and optionally a system prompt and tool definitions) and get back the model's response as content blocks. Anthropic offers several Claude models at different points on the capability, speed and cost curve, so the same code can use a larger model for hard reasoning and a smaller one for high-volume work.

Documented features include tool use (the model returns a structured request to call a function you defined), vision and file inputs, structured outputs, extended thinking and web search. Anthropic also offers managed agents for longer-running tasks. Claude models are available directly from Anthropic and through cloud platforms including [Amazon Bedrock](bedrock.md), Google Cloud and Microsoft Foundry, which matters when a firm's data policy requires staying inside an existing cloud account.

## Typical use cases

- Drafting and summarizing documents from structured inputs.
- Extracting fields from unstructured text into a fixed schema.
- Agents that call tools to look up data and propose actions.
- Question answering over retrieved documents, with citations.
- Code generation and review.

## In AI work

For a regulated firm the questions are less about the model and more about the path: where the data goes, which model version answered, what it cost, and whether the output was checked. Calling Claude through a thin internal wrapper — a registry that maps an approved alias to a provider and model ID, logs tokens and cost, and validates the output — keeps those answers in one place and lets you switch between direct API and Bedrock without touching business logic.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md): Anthropic is one of the providers behind the model registry, selected by alias alongside a mock, [OpenAI](openai.md) and [Bedrock](bedrock.md). The default is the offline mock; [Pydantic](pydantic.md) validates whatever comes back.

## Pros and cons

| Pros | Cons |
|---|---|
| Well-documented tool use, long inputs and structured outputs | Hosted API: data leaves your network unless you use a cloud route |
| Range of models to trade cost against capability | Model IDs and versions change; pin and re-test |
| Also available through Bedrock, Google Cloud and Microsoft Foundry | Per-token cost needs monitoring at volume |
| Official SDKs in many languages | Rate limits need handling in batch workloads |

## Basic usage

Install with `pip install anthropic`, set `ANTHROPIC_API_KEY`, then:

```python
import anthropic

client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=1000,
    messages=[{"role": "user", "content": "Summarize this vendor note in three bullets: ..."}],
)

for block in message.content:
    if block.type == "text":
        print(block.text)
```

## Documentation

[Claude API documentation](https://platform.claude.com/docs/en/home) — official, from Anthropic (docs.claude.com redirects here). See also the [quickstart](https://platform.claude.com/docs/en/get-started).
