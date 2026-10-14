---
title: Pydantic
category: Apps & APIs
vendor: Pydantic Services Inc.
docs: https://pydantic.dev/docs/validation/latest/get-started/
aliases: [Pydantic]
summary: Python data validation from type hints — the usual guard on structured LLM output.
---

# Pydantic

Pydantic validates Python data against classes defined with type hints, and tells you precisely what failed when it does not match.

## What it is

You declare a model as a class inheriting from `BaseModel`, with a type for each field. Creating an instance from a dict or JSON validates and, where allowed, converts the data (a string `"1"` to an integer, a timestamp string to a `datetime`). If anything is missing or wrong, it raises a `ValidationError` listing each failing field. Models serialize back out with `model_dump()` and can generate a JSON Schema of themselves.

Pydantic's core validation logic is written in Rust, which keeps it fast enough to validate every request or record. It supports strict and lax modes, custom validators and serializers, and standard library types such as dataclasses and TypedDicts. Many libraries build on it, including [FastAPI](fastapi.md).

## Typical use cases

- Validating API request and response bodies.
- Parsing configuration files and environment settings.
- Checking records from a vendor feed before they enter a pipeline.
- Defining a typed contract between services.
- Publishing a JSON Schema that other tools or models can follow.

## In AI work

A model returns text; the code downstream needs a fixed shape. Pydantic is the usual gate between the two: define the expected output as a model, give the model provider its JSON Schema, then validate what comes back. Anything that fails validation is rejected or retried, never passed on. Because validation is deterministic, it is easy to test with a mock model and to log as a control. Field constraints (enums, ranges, required fields) also catch a class of hallucinations — an invented category, a score of 11 out of 10 — before they reach a person.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md): Pydantic validates each LLM-drafted vendor memo before deterministic policy overrides apply.

## Pros and cons

| Pros | Cons |
|---|---|
| Schemas come straight from type hints | Lax-mode coercion can hide bad input unless you choose strict |
| Clear, field-level error messages | Major-version migrations have required code changes |
| Fast core, fine for high volumes | Valid shape does not mean correct content |
| JSON Schema output for models and APIs | Complex validators can become business logic in disguise |

## Basic usage

Validate a model's JSON output and reject it if the shape is wrong:

```python
from typing import Literal
from pydantic import BaseModel, Field, ValidationError

class VendorMemo(BaseModel):
    vendor: str
    recommendation: Literal["proceed", "hold", "reject"]
    score: int = Field(ge=0, le=10)

raw = '{"vendor": "Acme Data", "recommendation": "proceed", "score": 7}'
memo = VendorMemo.model_validate_json(raw)
print(memo.model_dump())

try:
    VendorMemo.model_validate_json('{"vendor": "X", "recommendation": "buy", "score": 11}')
except ValidationError as e:
    print(e)
```

## Documentation

[Pydantic documentation](https://pydantic.dev/docs/validation/latest/get-started/) — official, from Pydantic Services Inc.
