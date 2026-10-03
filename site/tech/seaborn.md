---
title: Matplotlib and seaborn
category: Machine learning & data science
vendor: open-source projects (NumFOCUS-sponsored)
docs: https://seaborn.pydata.org/
aliases: [seaborn, Matplotlib, matplotlib]
summary: Python plotting — Matplotlib for full control, seaborn for statistical charts from DataFrames.
---

# Matplotlib and seaborn

Matplotlib is Python's base plotting library; seaborn sits on top of it and makes common statistical charts from a DataFrame in one call.

## What it is

Matplotlib is an open-source plotting library, sponsored by NumFOCUS, that draws static charts — line, bar, scatter, histogram, heatmap and many more — and saves them as PNG, SVG or PDF. It gives control over every element of a figure (axes, ticks, labels, colors, layout), which also makes it verbose for everyday charts.

seaborn is an open-source library built on Matplotlib for statistical graphics. It takes a pandas DataFrame and column names and handles grouping, color by category, and statistical summaries itself: `histplot`, `boxplot`, `countplot`, `heatmap` and `pairplot` each produce a finished chart in a line or two. Because a seaborn chart is a Matplotlib figure, you can still adjust it with Matplotlib calls.

Both produce static images. For interactive charts in a browser, Plotly or a JavaScript library is the usual choice.

## Typical use cases

- Distributions of each feature during exploratory analysis.
- Correlation heatmaps.
- Comparing a feature across classes (box plots, grouped histograms).
- Confusion matrices and feature-importance bar charts after training.
- Charts for reports and slides.

## In AI work

Charts are how most data problems are found before a model is trained: skewed distributions, outliers, missing values and correlated features show up faster in a plot than in a table. After training, a confusion matrix and a feature-importance chart explain a model's behavior to people who will not read the code.

## In this portfolio

- [Loan default prediction (MIT capstone)](../classes/posts/loan-default-capstone.md): seaborn and Matplotlib draw the feature distributions, a correlation heatmap, confusion matrices for each model, a plotted decision tree and the random forest's feature importances. The models are in [scikit-learn](scikit-learn.md).

## Pros and cons

| Pros | Cons |
|---|---|
| seaborn makes statistical charts from a DataFrame in one call | Static images; no built-in interactivity |
| Matplotlib can control every detail of a figure | Matplotlib's API is verbose and has two styles |
| Output to PNG, SVG and PDF for reports | Fine-tuning a seaborn chart still means learning Matplotlib |
| Works in notebooks, scripts and CI | Large scatter plots get slow |

## Basic usage

Plot a histogram by group and save it as a PNG:

```python
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

rng = np.random.default_rng(0)
df = pd.DataFrame({
    "loan_amount": rng.lognormal(mean=9.8, sigma=0.4, size=500),
    "defaulted": rng.choice(["no", "yes"], size=500, p=[0.8, 0.2]),
})

ax = sns.histplot(data=df, x="loan_amount", hue="defaulted", bins=30, kde=True)
ax.set_title("Loan amount by outcome")
plt.tight_layout()
plt.savefig("loan_amount.png", dpi=150)
```

## Documentation

[seaborn documentation](https://seaborn.pydata.org/) — official, from the seaborn project.

[Matplotlib documentation](https://matplotlib.org/stable/) — official, from the Matplotlib project.
