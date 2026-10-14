---
title: FastAPI
category: Apps & APIs
vendor: Sebastián Ramírez and contributors (open source)
docs: https://fastapi.tiangolo.com/
aliases: [FastAPI]
summary: Python web framework for typed HTTP APIs, with validation and OpenAPI docs built in.
---

# FastAPI

FastAPI is a Python web framework for building HTTP APIs where the type hints on your functions define validation and the API documentation.

## What it is

You write ordinary Python functions and decorate them with a route (`@app.get`, `@app.post`). Parameter types and [Pydantic](pydantic.md) models declare what a request must contain; FastAPI validates incoming data against them, returns a clear error when it does not match, and serializes the response. From the same declarations it generates an OpenAPI schema and serves interactive docs at `/docs` and `/redoc`.

Handlers can be plain `def` or `async def`. It runs on an ASGI server, and the `fastapi` command line starts a development server with reload.

It is a framework for APIs first. It can render HTML with templates, but it has no built-in admin, ORM or front-end layer; you bring those.

## Typical use cases

- Internal REST APIs in front of a model, database or batch job.
- Wrapping a Python analytics or ML function as a service other teams can call.
- Webhook receivers and small integration services.
- Back ends for dashboards, including server-rendered HTML.
- Typed contracts between services, published as OpenAPI.

## In AI work

FastAPI is a common way to put an LLM pipeline behind a stable interface: request and response models fix the contract, so callers get a validated answer shape rather than raw model text. It is also a convenient place to enforce controls before anything reaches the model — authentication, entitlement checks, input size limits, logging of every request and response for audit.

## In this portfolio

- [Research Q&A](../blog/posts/research-qa-rag.md): a FastAPI service answers questions over parsed research PDFs, with the entitlement filter applied in SQL, alongside a [Streamlit](streamlit.md) app.
- [Governance console](../blog/posts/governance-console.md): FastAPI serves server-rendered HTML with [Chart.js](chartjs.md) dashboards over an event store, plus the kill switch.

## Pros and cons

| Pros | Cons |
|---|---|
| Validation and OpenAPI docs come from type hints | Async vs sync handlers need care to avoid blocking |
| Little boilerplate for a working API | No batteries-included admin, auth or ORM |
| Pydantic models double as API contracts | Server-rendered UI is possible but basic |
| Easy to test with an in-process client | Large apps need your own structure and conventions |

## Basic usage

Save as `main.py` and run `fastapi dev main.py`; interactive docs appear at `http://127.0.0.1:8000/docs`:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}
```

## Documentation

[FastAPI documentation](https://fastapi.tiangolo.com/) — official, from the FastAPI project.
