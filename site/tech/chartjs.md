---
title: Chart.js
category: Apps & APIs
vendor: Chart.js contributors (open source)
docs: https://www.chartjs.org/docs/latest/getting-started/
aliases: [Chart.js]
summary: JavaScript charting library that draws on an HTML canvas from a small config object.
---

# Chart.js

Chart.js is a JavaScript library that draws common charts — bar, line, pie and others — onto an HTML `<canvas>` from a configuration object.

## What it is

Chart.js is an open-source project. You add a `<canvas>` element to a page, load the library (from npm or a CDN), and create a `new Chart(...)` with a chart type, the data (labels and datasets) and options such as axes, legends and tooltips. It handles layout, scaling, hover tooltips and animation.

Because it is plain JavaScript with no framework requirement, it fits well into server-rendered pages: the server writes the HTML and the data, and a few lines of script draw the chart in the browser. Rendering to canvas means charts are images in the page rather than DOM elements, which keeps them light but less accessible to screen readers unless you add text alternatives.

## Typical use cases

- Operational dashboards on server-rendered HTML.
- Small charts in internal tools without adopting a front-end framework.
- Time series of counts, costs or latencies.
- Share-of-total and status breakdowns.
- Embedding charts in static reports.

## In AI work

Governance of AI systems produces a lot of numbers worth watching: model calls per day, cost per model, validation failures, human overrides, escalations. Those belong on a dashboard the risk or operations team actually opens. Chart.js lets you build that view with a few lines of script on top of whatever API holds the event log, without a separate BI tool or a JavaScript build pipeline.

## In this portfolio

- [Governance console](../blog/posts/governance-console.md): [FastAPI](fastapi.md) serves server-rendered HTML, and Chart.js draws the dashboards over the [SQLite](sqlite.md) or [Postgres](postgres.md) event store.

## Pros and cons

| Pros | Cons |
|---|---|
| Few lines of code for a usable chart | Canvas output needs extra work for accessibility |
| No framework or build step required | Less flexible than lower-level libraries for custom visuals |
| Works with server-rendered pages | Very large datasets need decimation or aggregation first |
| Sensible defaults for tooltips and legends | Interactive cross-filtering is up to you |

## Basic usage

A bar chart in a plain HTML page, loading the library from a CDN:

```html
<div>
  <canvas id="myChart"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  const ctx = document.getElementById("myChart");
  new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["Mon", "Tue", "Wed", "Thu", "Fri"],
      datasets: [{ label: "Model calls", data: [120, 190, 30, 50, 20], borderWidth: 1 }]
    },
    options: { scales: { y: { beginAtZero: true } } }
  });
</script>
```

## Documentation

[Chart.js documentation](https://www.chartjs.org/docs/latest/getting-started/) — official, from the Chart.js project.
