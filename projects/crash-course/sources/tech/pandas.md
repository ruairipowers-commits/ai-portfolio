---
title: pandas
category: Machine learning & data science
vendor: NumFOCUS-sponsored open-source project
docs: https://pandas.pydata.org/docs/
aliases: [pandas]
summary: Python library for tabular data — load, clean, reshape and summarize DataFrames in memory.
---

# pandas

pandas is the standard Python library for working with tables of data in memory.

## What it is

pandas is an open-source Python library, fiscally sponsored by NumFOCUS, built around two types: the `DataFrame` (a table with labelled columns and an index) and the `Series` (one column). It reads and writes CSV, Excel, Parquet, JSON and SQL, and covers most of what an analyst does to a table: filter, join, group and aggregate, pivot, handle missing values, and work with dates and time series.

Operations are vectorized over whole columns and run in compiled code, so idiomatic pandas is fast even though it is called from Python. Row-by-row loops are where it gets slow.

The whole dataset lives in memory on one machine. For data larger than RAM, or for heavy SQL-style aggregation, DuckDB or Polars are often a better fit, and both exchange data with pandas directly.

## Typical use cases

- Exploratory data analysis: shape, types, summary statistics, missing values.
- Cleaning: imputing missing values, capping outliers, fixing types.
- Feature preparation before a scikit-learn model.
- Joining and reshaping vendor or reference files.
- Quick reports and pivots in a notebook.

## In AI work

Most model work starts with a DataFrame. pandas is where a dataset is profiled, cleaned and turned into features before training, and where predictions and evaluation results are collected afterwards for comparison. Keeping each cleaning step as explicit code (rather than edits in a spreadsheet) makes the preparation repeatable and reviewable.

## In this portfolio

- [Loan default prediction (MIT capstone)](../classes/posts/loan-default-capstone.md): pandas handles EDA on the HMEQ home-equity loan data (5,960 loans), caps outliers with the IQR rule, and imputes missing values with the median, mode or zero before modelling in [scikit-learn](scikit-learn.md).
- [MIT Applied AI and Data Science](../classes/posts/applied-ai-data-science.md): the course's weekly notebooks open with NumPy and pandas, and use them throughout.

## Pros and cons

| Pros | Cons |
|---|---|
| The common format for Python data and ML libraries | Whole dataset must fit in memory |
| Broad I/O: CSV, Excel, Parquet, JSON, SQL | Large, sometimes inconsistent API |
| Vectorized column operations are fast | Row-wise loops and `apply` are slow |
| Strong support for missing values and time series | Index and copy-versus-view behavior can surprise |

## Basic usage

Read a CSV and summarize it by group:

```python
import pandas as pd

df = pd.read_csv("loans.csv")
print(df.describe())

summary = (
    df.groupby("reason")
      .agg(n_loans=("loan_id", "count"),
           avg_amount=("loan_amount", "mean"),
           default_rate=("defaulted", "mean"))
      .sort_values("default_rate", ascending=False)
)
print(summary)
```

## Documentation

[pandas documentation](https://pandas.pydata.org/docs/) — official, from the pandas project.
