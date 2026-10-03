---
title: Jupyter and Google Colab
category: Machine learning & data science
vendor: Project Jupyter; Colab by Google
docs: https://docs.jupyter.org/en/latest/
aliases: [Jupyter, Google Colab, Colab]
summary: Notebooks that mix code, output, charts and notes — run locally with Jupyter or hosted in Colab.
---

# Jupyter and Google Colab

Jupyter notebooks mix code, results, charts and written notes in one document; Google Colab runs the same notebooks in the browser with nothing to install.

## What it is

Project Jupyter is an open-source project that defines the notebook format (`.ipynb`) and the tools to run it. JupyterLab is the main interface: a browser-based editor where a notebook is a list of cells, each either code or Markdown. Code cells run against a kernel — usually Python — and their output, including tables and charts, is saved in the notebook next to the code.

Google Colab is a hosted notebook service from Google. It opens `.ipynb` files, runs them on a Google-managed machine with common libraries preinstalled, and offers GPUs on some tiers. It needs only a Google account and a browser.

Colab can open a notebook straight from a public GitHub repo, which makes it a simple read-only viewer: a notebook at `https://colab.research.google.com/github/<owner>/<repo>/blob/<branch>/<path>.ipynb` opens in Colab, and each visitor runs their own copy. They can change and rerun cells, but the original in GitHub never changes unless they save a copy elsewhere.

Notebooks are good for exploration and teaching, and weaker as production code: cells can run out of order, hidden state builds up, and JSON diffs are hard to review.

## Typical use cases

- Exploratory data analysis and charts.
- Training and comparing models step by step.
- Course work and tutorials.
- Sharing an analysis with its results and reasoning in one file.
- Running GPU work without local hardware (Colab).

## In AI work

A notebook keeps the data checks, model runs and evaluation output together with the explanation of each decision, which suits model development and review. Once an approach settles, the code that matters usually moves into a package with tests, and the notebook stays as the record of how the model was chosen.

## In this portfolio

- [Loan default prediction (MIT capstone)](../classes/posts/loan-default-capstone.md): the capstone notebook opens read-only in Google Colab from its GitHub repo, so a reader can rerun the analysis without installing anything.
- [MIT Applied AI and Data Science](../classes/posts/applied-ai-data-science.md): the course's weekly notebooks — NumPy and pandas, statistics with SciPy, clustering and PCA, regression and classification, trees and forests, time series, deep learning and recommendation systems — all ran in Jupyter and Colab.

## Pros and cons

| Pros | Cons |
|---|---|
| Code, output and notes in one shareable file | Out-of-order execution and hidden state |
| Fast feedback for exploration and charts | `.ipynb` JSON is awkward to diff and review |
| Colab needs no install and offers GPUs | Colab sessions time out and storage is temporary |
| Colab opens public GitHub notebooks directly | Not a substitute for tested, packaged code |

## Basic usage

Run JupyterLab locally:

```bash
pip install jupyterlab
jupyter lab
```

Or open a notebook from a public GitHub repo in Colab with this URL pattern:

```text
https://colab.research.google.com/github/<owner>/<repo>/blob/<branch>/<path>.ipynb
```

## Documentation

[Jupyter documentation](https://docs.jupyter.org/en/latest/) — official, from Project Jupyter.

[Colab FAQ](https://research.google.com/colaboratory/faq.html) — official, from Google.
