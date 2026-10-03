---
date: 2026-05-10
slug: applied-ai-data-science
short: "MIT Applied AI and Data Science (course)"
categories: [Learning, Machine learning, Evaluation]
tags: [statistics, regression, classification, decision trees, random forests, deep learning, recommenders, generative ai]
---

# MIT Applied AI and Data Science: what's under the hood

I took MIT Professional Education's Applied AI and Data Science Program from January to May 2026. I wanted to
understand how the models behind AI products actually work, not just call them through an API. Fifteen weeks
covered statistics, classical machine learning, deep learning, recommendation systems and generative AI. Every topic
came with a working notebook, and the course ended with a capstone.

<!-- more -->

**Course:** [Applied AI and Data Science Program](https://professional.mit.edu/course-catalog/applied-ai-and-data-science-program),
MIT Professional Education ·
**When:** 17 January – 10 May 2026, live online ·
**Credits:** 16 CEUs ·
**Credential:** [certificate of completion](https://credentials.professional.mit.edu/f7f85f52-ac19-4e4d-b197-194db5524f71#acc.oNVwJrWn) ·
**Capstone:** [loan default prediction](loan-default-capstone.md) ·
**Stack:** Python, pandas, scikit-learn, seaborn, SciPy, Jupyter, Google Colab

## How it ran

- **Lectures.** Each topic had pre-reading, then a live two-hour lecture from MIT faculty.
- **Weekend mentor sessions.** A practitioner worked a full case study in a notebook, with an industry
  perspective.
- **Time.** 12–18 hours a week was the stated commitment, and that was accurate.
- **Grading.** Projects 60%, quizzes 30%, attendance 10%, with 60% needed to pass.

The program counts toward MIT's Professional Certificate in Machine Learning & Artificial Intelligence.

## What it covered

| Weeks | Topic | Faculty | What I learned to do |
|---|---|---|---|
| Prework, 1 | Python for data science | Mentors | NumPy, pandas and plotting; an Uber rides case |
| 2 | Statistics | Mentors | Distributions, confidence intervals, hypothesis tests in SciPy |
| 3 | Data analysis, networks, unsupervised learning | Prof. Caroline Uhler | PCA and t-SNE; network centrality; k-means, Gaussian mixtures, hierarchical clustering, DBSCAN |
| 4 | Machine learning: regression and classification | Prof. John Tsitsiklis | Linear and regularised regression, cross-validation, bootstrapping; logistic regression, k-NN, LDA/QDA; precision, recall and F1 |
| 5 | Revision | — | A sales-forecasting practice project |
| 6 | Decision trees, random forests, time series | Prof. Munther Dahleh | Entropy and information gain, pruning, bagging and boosting; stationarity, AR/ARIMA, SARIMAX |
| 7 | Deep learning | Dr. Stefanie Jegelka | Neural networks and backpropagation, CNNs, transfer learning, transformers and attention |
| 8 | Recommendation systems | Prof. Devavrat Shah | Popularity, content-based and collaborative filtering; matrix factorisation (SVD, alternating least squares) |
| 9 | Revision | — | Conceptual and case-study review |
| 10–11 | Generative AI | Prof. Munther Dahleh | How LLMs, VAEs and diffusion models generate; prompting; RAG versus fine-tuning; agents and guardrails |
| Final weeks | Capstone | — | [Loan default prediction](loan-default-capstone.md) |

The models, in the order they built on each other:

- **Statistics first.** Distributions, sampling, and tests for whether a difference is real. Everything after this
  is an estimate, and statistics tells you how much to trust it.
- **Unsupervised learning** finds structure without labels. PCA compresses features into the directions that
  matter. Clustering groups similar records; my notes say to pick the elbow and stop, because each extra cluster is
  more to interpret.
- **Regression and classification** learn from labelled examples. The week's real lesson was evaluation:
  - bias against variance;
  - cross-validation to choose a model, then bootstrapping to put a confidence interval on it;
  - and which error costs more, which decides whether you optimise precision or recall.
- **Decision trees** split on the question that most reduces uncertainty, which makes them readable rules.
  **Random forests** average many trees to cut overfitting. **Boosting** builds trees that each fix the last one's
  errors.
- **Time series** need stationarity before forecasting. AR/ARIMA models turn out to be least squares on the
  series' own past.
- **Neural networks** stack weighted sums and nonlinearities, trained by gradient descent:
  - **CNNs** share small filters across an image;
  - **transfer learning** reuses a model trained on millions of images;
  - **transformers** use attention to weigh every token against every other.
- **Recommenders** fill in a sparse user × item matrix. Matrix factorisation by alternating least squares is a
  linear regression on each pass.
- **Generative AI** is next-token probability at scale. That explains both what it's good at and why it
  hallucinates. The course treated prompting as an iterative, versioned process, and RAG as the fix when the model
  doesn't know your data.

Prof. Tsitsiklis made a point in week 4 that stayed with me. Fitting the model is one line of code; the value you
add is in assessing it.

## Why it matters for AI and agentic workflows

Most of my portfolio calls LLMs rather than training models, so why spend fifteen weeks on regression and trees?

| Course idea | Where it shows up in agentic work |
|---|---|
| Precision against recall, and the cost of each error | Every eval gate and alert threshold. A missed escalation and a false alarm don't cost the same. |
| Train/test splits, cross-validation | Golden sets held out from prompt tuning; never grading a model on what it was tuned on |
| Hypothesis tests, confidence intervals | Telling whether a new prompt or model is really better or just noise |
| Explainable models (trees, coefficients) | Giving reasons for decisions that affect people: credit, compliance, escalation |
| Embeddings, attention, next-token prediction | Knowing why retrieval works, why context order matters, and why models invent things |
| RAG versus fine-tuning | The first design decision in any assistant over private documents |
| Drift, stationarity | Monitoring a deployed model and knowing when its inputs no longer look like its training data |

Classical ML is also still most of production machine learning. A mentor said it plainly before the course began:
industry still runs on regression, classification, clustering and A/B tests, and interviews probe whether you can
explain them. Knowing when *not* to use an LLM is part of the job.

## How it's applied in this portfolio

- **Evaluation before release.** Every project here ships a golden set and an eval gate in CI, and the
  [site assistant](../../personal/posts/site-assistant.md) reports retrieval hit-rate. Those are the week 4 habits:
  a held-out test set, and a metric chosen for the error that matters.
- **Retrieval.** The [research Q&A project](../../blog/posts/research-qa-rag.md) and the site assistant are both
  retrieval-augmented. The generative AI weeks covered the same design, with chunking, embeddings, a vector store
  and answers only from the retrieved text.
- **Numbers from code, words from the model.** The portfolio's rule that code and SQL compute every number, and the
  model only explains, is the course's distinction between statistical estimates and generated text.
- **Staged rollout.** My capstone ends with running the model in parallel with the manual process before trusting
  it. That became the backbone of my [agentic AI course](applied-agentic-ai.md).

## The work I completed

- **Weekly case studies**, a notebook or more for every session. Examples:
  - the Game of Thrones and Enron networks;
  - a drug-trafficking network over eleven wiretap phases;
  - country clustering on socio-economic data;
  - hospital length-of-stay and employee-attrition prediction;
  - Bitcoin, CPI and crude-oil forecasting;
  - audio digit recognition and CIFAR-10 image classification;
  - movie and Yelp recommenders.
- **FoodHub** (February), the first graded project: exploratory analysis of a food-delivery order dataset.
- **Elective project: an Amazon product recommender** (March). I designed a hybrid:
  - popularity ranking for new users, who have no history;
  - SVD matrix factorisation for users with enough ratings;
  - item-to-item similarity alongside.

  I ruled out user-to-user k-NN because on that many ratings it was too memory- and compute-heavy without heavy
  pruning.
- **Generative AI case studies** (April):
  - a case study generating a bakery's whole marketing campaign in code: a poster from Stable Diffusion XL, an
    8-second video, and a voice-over;
  - business applications with Gemini: classifying hotel reviews with few-shot prompts, rewriting clinical visit
    notes for patients, and a RAG assistant over an HR manual.
- **Capstone: [loan default prediction](loan-default-capstone.md)** (May). An explainable credit model and a
  rollout plan, presented to the bank as a business case.
- **Hackathon** (May, after the program). A Great Learning hackathon predicting passenger satisfaction on a bullet
  train from travel and survey data, about 84,000 training rows. I logged 27 experiments: Optuna-tuned gradient
  boosting, pseudo-labelling, and multi-layer AutoGluon stacks. Honest cross-validated accuracy was 0.96–0.97.

## What I'd tell someone considering it

- **Do the notebooks, not just the lectures.** The understanding comes from changing a parameter and watching the
  confusion matrix move.
- **It's a lot of material.** Fifteen weeks covers ground a university course would spread over a year. Expect the evenings and
  weekends the time estimate says.
- **The faculty sessions are the reason to take it.** The derivations are available elsewhere. MIT faculty
  explaining why a method works, and where it breaks, isn't.

*Course materials belong to MIT Professional Education and its learning partner, Great Learning; this is my
summary of them, in my words.*
