---
title: scikit-learn
category: Machine learning & data science
vendor: open-source project (NumFOCUS-sponsored)
docs: https://scikit-learn.org/stable/
aliases: [scikit-learn, sklearn]
summary: Python library for classical machine learning — models, preprocessing, tuning and metrics behind one API.
---

# scikit-learn

scikit-learn is the standard Python library for classical machine learning on tabular data.

## What it is

scikit-learn is an open-source Python library, sponsored by NumFOCUS, covering supervised and unsupervised learning: linear and logistic regression, decision trees, random forests and gradient boosting, support vector machines, k-means and other clustering, and PCA. It also provides the surrounding pieces — train/test splitting, scaling and encoding, pipelines, cross-validation, hyperparameter search and evaluation metrics.

Every model follows the same pattern: create an estimator, call `fit` on training data, then `predict` or `transform`. That consistency means swapping a logistic regression for a random forest is usually a one-line change, and tools like `GridSearchCV` work with any estimator.

It is not a deep learning library. For neural networks on images, text or very large datasets, PyTorch, TensorFlow or Keras are the usual choice; scikit-learn runs on the CPU and expects data that fits in memory.

## Typical use cases

- Classification and regression on tabular data (credit, churn, pricing).
- Baselines to compare against more complex models.
- Clustering and dimensionality reduction for exploration.
- Hyperparameter tuning with cross-validation.
- Model evaluation: confusion matrices, precision, recall, ROC curves.

## In AI work

Classical models are still the right tool for many structured-data problems, and they are easier to explain than a neural network: a decision tree can be plotted, and a forest reports feature importances. scikit-learn also makes the evaluation choices explicit. Class weights handle imbalanced labels, and the `scoring` argument lets you tune for the metric that matters — recall on defaults, for example, rather than overall accuracy.

## In this portfolio

- [Loan default prediction (MIT capstone)](../classes/posts/loan-default-capstone.md): logistic regression, a decision tree and a random forest are trained on the HMEQ home-equity loan data (5,960 loans), with class weights for the imbalanced default label and `GridSearchCV` tuned for recall on defaults. Data preparation is in [pandas](pandas.md); charts are in [Matplotlib and seaborn](seaborn.md).
- [MIT Applied AI and Data Science](../classes/posts/applied-ai-data-science.md): the course's weekly notebooks on clustering and PCA, regression and classification, and trees and forests.

## Pros and cons

| Pros | Cons |
|---|---|
| One consistent `fit` / `predict` API across models | No deep learning or GPU support |
| Preprocessing, pipelines, tuning and metrics included | Data must fit in memory on one machine |
| Well-documented, with sensible defaults | Categorical data needs explicit encoding |
| Interpretable models (trees, linear) are first-class | Large grid searches get slow quickly |

## Basic usage

Train a random forest on a built-in dataset and print precision and recall:

```python
from sklearn.datasets import load_breast_cancer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

X, y = load_breast_cancer(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, stratify=y, random_state=42
)

model = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42)
model.fit(X_train, y_train)
print(classification_report(y_test, model.predict(X_test)))
```

## Documentation

[scikit-learn documentation](https://scikit-learn.org/stable/) — official, from the scikit-learn project.
