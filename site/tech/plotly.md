---
title: Plotly
category: Apps & APIs
vendor: Plotly
docs: https://plotly.com/python/
aliases: [Plotly]
summary: Interactive charting library for Python and JavaScript, with hover, zoom and maps built in.
---

# Plotly

Plotly draws interactive charts — bars, lines, scatter, maps — from Python, rendered in the browser.

## What it is

Plotly's open-source graphing library has a high-level API (`plotly.express`) that turns a DataFrame into a chart
in one call, and a lower-level one (`graph_objects`) for full control. Charts are interactive by default (hover,
zoom, legend toggles) and embed in Streamlit, notebooks or static HTML.

## Typical use cases

- Dashboards in Streamlit or Dash.
- Exploratory charts in notebooks.
- Maps of points (`scatter_geo`) without a map-tile key.

## In AI work

Hover tooltips let a reader check the exact value behind any bar, which matters when a model's summary quotes the
same numbers.

## In this portfolio

- [Launch tracker](../personal/posts/launch-tracker.md): launches per year by outcome and by country, success rate
  by rocket, booster reuse, measured delays, launches by industry with a projection band, objects per altitude
  shell, and a map of launch sites.

## Pros and cons

| Pros | Cons |
|---|---|
| Interactive with no extra work | Heavier pages than static images |
| Express API is quick from a DataFrame | Fine layout control means `graph_objects` |
| Maps without a tile key | World outlines load from Plotly's CDN |

## Basic usage

```python
import plotly.express as px
fig = px.bar(df, x="year", y="launches", color="outcome")
fig.show()
```

## Documentation

[Plotly Python documentation](https://plotly.com/python/) — official.
