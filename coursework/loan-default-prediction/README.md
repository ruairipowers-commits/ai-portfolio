# Loan default prediction — MIT capstone

My capstone for MIT Professional Education's Applied AI and Data Science Program (May 2026). It predicts which
home-equity loans will default, explains why, and proposes how a bank would roll the model out safely.

| File | What it is |
|---|---|
| `loan_default_prediction.ipynb` | The analysis: EDA, cleaning, logistic regression, decision trees and random forests, tuned for recall on defaults. Saved with the outputs of my final run. |
| `hmeq.csv` | The public HMEQ home-equity dataset: 5,960 loans, 12 application fields, `BAD` = defaulted |
| `loan-default-prediction-deck.pdf` | The final presentation |

**Run it in Colab (read-only):**
[open the notebook](https://colab.research.google.com/github/ruairipowers-commits/ai-portfolio/blob/main/coursework/loan-default-prediction/loan_default_prediction.ipynb),
then **Runtime → Run all**. You get your own copy; the data loads from this repository.

**Run it locally:**

```bash
pip install pandas scikit-learn seaborn scipy jupyterlab
jupyter lab loan_default_prediction.ipynb     # reads hmeq.csv from this folder
```

**Write-up:** [Capstone: predicting home-loan defaults](https://ruairipowers-commits.github.io/ai-portfolio/classes/loan-default-capstone/)

This is coursework, not one of the governed portfolio workflows, so it has no governance mapping, tests or CI.
In the original notebook the data loaded from my Google Drive. That, and a note at the top on how to run it,
are the only changes: it now loads from this folder or from GitHub. A third-party image was removed from one slide of the deck.
