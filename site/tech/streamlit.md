---
title: Streamlit
category: Apps & APIs
vendor: Snowflake Inc.
docs: https://docs.streamlit.io/
aliases: [Streamlit]
summary: Python framework for turning a data script into an interactive web app.
---

# Streamlit

Streamlit turns a Python script into an interactive web app, with no HTML or JavaScript.

## What it is

Streamlit is an open-source Python framework maintained by Snowflake. You call functions such as `st.write`, `st.dataframe`, `st.slider` and `st.button` in an ordinary script, and run it with `streamlit run app.py`; a local server starts and the app opens in the browser.

The execution model is simple and worth understanding before you build anything large: whenever a user interacts with a widget, Streamlit reruns the whole script from top to bottom. Expensive work is kept out of that loop with caching (`@st.cache_data`, `@st.cache_resource`), and values that must persist between reruns live in `st.session_state`. Widget callbacks run before the rest of the script.

It is built for internal tools and demos rather than high-traffic, highly customized web front ends.

## Typical use cases

- Internal data apps over a model, query or report.
- Demo front ends for a pipeline, so reviewers can run it without a terminal.
- Human review screens: show the model's output, collect an approve or reject.
- Lightweight dashboards for an operations team.
- Prototypes that may later move to a dedicated front end.

## In AI work

Most AI pipelines need a place where a person sees the input, the model output and the evidence side by side and makes a decision. Streamlit is a quick way to build that screen in the same language as the pipeline. It also suits adversarial testing: an input box where a reviewer edits untrusted text and reruns the pipeline makes failure cases visible to non-engineers. Apps can be tested headless with `streamlit.testing`.

## In this portfolio

- Four projects ship a Streamlit app laid out as input → run → output: [Alt-data vendor triage](../blog/posts/altdata-triage.md), [EOD heartbeat](../blog/posts/eod-heartbeat.md), [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md) and [Research Q&A](../blog/posts/research-qa-rag.md).
- The live demos run in [Docker](docker.md) containers on a home server, or on [Hugging Face Spaces](hugging-face-spaces.md).

## Pros and cons

| Pros | Cons |
|---|---|
| A working app from a short Python script | Full-script reruns need caching discipline as apps grow |
| No front-end skills needed | Limited control over layout and look |
| Easy for data teams to maintain | Not designed for many concurrent public users |
| Headless testing built in | Multi-step state handling gets awkward in complex flows |

## Basic usage

Save as `app.py` and run `streamlit run app.py`:

```python
import streamlit as st

st.title("Hello")
x = st.slider("Pick a number", 0, 100)
st.write(f"You selected: {x}")

st.text_input("Your name", key="name")
st.write(f"Hello, {st.session_state.name}")
```

## Documentation

[Streamlit documentation](https://docs.streamlit.io/) — official, from Snowflake Inc. See also [Basic concepts](https://docs.streamlit.io/get-started/fundamentals/main-concepts) for the rerun model.
