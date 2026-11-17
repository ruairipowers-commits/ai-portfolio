---
date: 2026-11-14
slug: chemeleon-low-data-molecules
short: "Cheap labels for small datasets"
categories: [Research, Evaluation, Data quality]
tags: [foundation models, pre-training, transfer learning, low-data, chemistry, benchmarks, AutoPublished]
audience: [Heads of data, Data scientists, AI and ML engineers, CTOs and heads of technology]
section: AI insight
---

# CheMeleon: Pre-Training on Labels Nobody Had to Measure

Most models I have seen stall do it for the same reason: a few hundred labels that cost real expert time, and no
budget for more. A group at MIT has a result worth borrowing. They pre-trained a molecular property model on about
1,600 properties a computer calculates without a lab, instead of on the scarce measurements everyone
else chases, and it beat the classical baselines on small datasets. The transferable decision is the choice of
pre-training target.

<!-- more -->

## What it is

CheMeleon is a pre-trained model that predicts molecular properties where experimental data is scarce, described by
[MIT News](https://news.mit.edu/2026/how-to-predict-molecule-behavior-with-scant-data-1106)
(6 November 2026) and in the paper
[Deep Learning Foundation Models for Low-Data Regimes from Classical Molecular Descriptors](https://arxiv.org/abs/2506.15792) by Jackson
Burns, Akshat Shirish Zalte and colleagues at MIT with three researchers at BASF, published in the *Journal of
Chemical Information and Modeling* in September. An earlier version of the paper has been online since last year,
so this is attention rather than a new release.

It was trained on one million molecules drawn at random from PubChem, using **Mordred** descriptors as its target:
1,613 chemist-designed features that can be computed for any valid structure. The paper's argument for that choice
is the whole idea. Descriptors are deterministic, low-noise and cheap to compute, while experimental labels are
noisy and quantum-mechanical labels are expensive and cover only parts of chemical space.

The architecture is a directed message-passing neural network in Chemprop: hidden dimension 2048, depth six, mean
aggregation and a two-layer feed-forward head. 12.9 million parameters in total, 8.7 million of them in the
message-passing part. During pre-training 85% of the descriptor targets were masked in the loss, and the model was
trained to reconstruct the rest. The reported pre-training test RMSE was 0.14, though the authors are careful to
say they do not treat that number as important and leave it to later work whether it says anything about
downstream quality.

To use it on a new property you keep the encoder, drop the pre-training head, attach a fresh task-specific head and
fine-tune end to end. In [Chemprop](https://chemprop.readthedocs.io/en/main/chemeleon_foundation_finetuning.html)
that is the flag `--from-foundation chemeleon`, with the weights downloaded from Zenodo
(doi 10.5281/zenodo.15426600) and the code on GitHub at `JacksonBurns/CheMeleon`. It has been part of Chemprop since
version 2.2.0.

The results, in win rates — the share of benchmarks where a model was statistically best:

| Model | Polaris (28 benchmarks) | MoleculeACE, all assays | MoleculeACE, cliff subset |
|---|---|---|---|
| CheMeleon | 21 (75%) | 29 (97%) | 30 (100%) |
| minimol | 20 (71%) | 12 (40%) | 20 (67%) |
| Random Forest | 19 (68%) | 15 (50%) | 20 (67%) |
| MoLFormer | 11 (39%) | 5 (17%) | 10 (33%) |
| fastprop | 10 (36%) | 5 (17%) | 12 (40%) |
| Chemprop | 9 (32%) | 0 (0%) | 4 (13%) |
| MolCLR | 4 (14%) | 0 (0%) | 2 (7%) |

MIT also reports that nine of the top 20 entries in an OpenADMET prediction contest used CheMeleon and that several
pharmaceutical companies have adopted it, and quotes William Green, who leads the MIT group, saying the model "drastically reduces the number
of molecules that need to be tested experimentally". Those are reported claims, not numbers anyone outside the group
has reproduced.

## Why it matters beyond AI labs

Strip out the chemistry and the move is this: when expensive labels are scarce, stop trying to buy more of them and
find a cheap, deterministic property of the same object that a machine can compute for every record you own. Then
pre-train on thousands of those at once and spend your few real labels on fine-tuning.

That pattern is not specific to molecules — but I should be plain that nobody has tested it outside them. The paper
is about chemistry. Everything below is my own hypothesis about where the shape would fit, not a result.

- **Health care and materials.** The direct case, and the one the paper covers: fewer compounds made and tested per
  useful hit.
- **Financials.** Confirmed outcomes are scarce — defaults, verified fraud, analyst-checked events — while derived
  statistics for the same instrument, filing or payment stream are abundant and free to compute.
- **Industrials and energy.** Long sensor histories against a handful of confirmed failures: pre-train on computed
  signal statistics across every machine-hour you have logged, fine-tune on the failures you can actually label.

A worked example of the financial version. Say a team holds 400 analyst-confirmed labels on counterparty documents
and twelve million unlabelled documents. The usual answers are weak supervision or a generic text embedding. The
CheMeleon-shaped answer is to compute a few hundred deterministic statistics for all twelve million documents,
pre-train an encoder to predict them, then fine-tune that encoder on the 400. The pre-training label costs compute
rather than analyst time, which is the part of the budget that is actually fixed. Compute is not free either: the
Chemprop documentation notes that training may take longer per epoch, because the model carries more parameters.

## What I'd watch out for

The headline number is a win rate, and a win rate counts how often a model was statistically best, not by how much.
75% against Random Forest's 68% on Polaris is a narrower gap than it reads. Anyone running this comparison on their
own data should still run the simple baseline, because on these benchmarks the simple baseline is close.

The comparison was also run without per-benchmark hyperparameter tuning, over five repetitions, in single-task
settings. That is a defensible choice for a fair fight between methods, and it is not the same as a tuned
production bake-off. The paper's own dataset count does not add up either: the abstract cites 58 datasets, while
the methods describe 28 Polaris benchmarks and 29 MoleculeACE assays, which is 57. The MoleculeACE columns above
have the same wrinkle — 29 wins read as 97% and 30 wins as 100% — so take the win rates as the paper reports them
rather than back-calculating the denominators.

Two gaps matter more than the benchmark arithmetic.

Out-of-distribution behaviour is not characterised. The paper never addresses what happens on molecules unlike the
PubChem sample; its nearest statement is that the representations generalise across diverse molecular spaces. For a
low-data problem this is the question, because a domain with few labels is usually also a domain where the next
input is unlike anything in the training set.

Activity cliffs are the second gap. These are pairs where a small structural change produces a large change in
behaviour, and CheMeleon does not reliably tell them apart from the rest: statistically best cliff/non-cliff
consistency in only four assays, against two for minimol. The business analogue is the near-identical input with a
very different correct answer, which is exactly where an automated decision does the most damage.

On governance, a pre-trained encoder is a third-party dependency before it is a model. The weights come from a
Zenodo record, and while the paper describes the work as permissively licensed, the Chemprop documentation page
does not state a licence for the weights. That is model provenance (SEC-06) and usage rights (DATA-04) before it is
anything else, with a named approver on whatever the output feeds (HITL-02); see
[the governance standard](../../blog/posts/governance.md).

## What I'd try next

The test I would actually run is the cheap one: take a small labelled dataset I already have, compute a few hundred
deterministic features over the large unlabelled pool, pre-train an encoder to predict them with most masked, and
see whether it beats a tuned gradient-boosted baseline on the same split. If it does not beat the baseline, the idea
does not travel out of chemistry and that is worth knowing in a week rather than a quarter.

What would change my mind in the other direction is an out-of-distribution result. A model that holds up on inputs
unlike its pre-training sample would be worth real effort; one that is only strong on held-out splits of the same
distribution is a benchmark result, not a tool. Until someone measures that, the honest summary is that this is a
clever and well-evidenced choice of pre-training label in chemistry, and an untested idea everywhere else.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
