---
date: 2026-11-06
slug: vocabx-tokenizer-cost
short: "Cheaper small models via vocabulary"
categories: [Cost & FinOps, Self-hosting, Evaluation]
tags: [tokenizer, vocabulary, small language models, inference cost, qwen3, vllm, structured output, AutoPublished]
audience: [CTOs and heads of technology, AI and ML engineers, Heads of data]
section: AI insight
---

# VocabX: Cutting Small‑Model Inference Costs by Re‑engineering Tokenizers

If you run a small language model for a single structured task—say grading essays or parsing trade confirmations—then the cost of each generated token can dominate your bill. A recent case study reports that tailoring the tokenizer alone cut measured inference cost by 77% on one workload. This post explains how, why it matters beyond AI labs, what to watch out for, and where I’d go next.

<!-- more -->

## What it is

The technique, called **VocabX**, was described by Dharma‑AI in a [Hugging Face blog post](https://huggingface.co/blog/Dharma-AI/vocabx-vocabulary-specialization) on a Portuguese essay grader built with Qwen3‑4B. The grader receives an essay, a prompt, and supporting text, then outputs a JSON object with a grade and a comment for each competency. In the original system, the general multilingual tokenizer from Qwen3 wasted money twice: text the grader writes over and over, like the JSON wrapper, was split into many tokens, and every generated token was scored against all 151,669 vocabulary entries, most of which this task never needs.

VocabX rebuilds two layers of the vocabulary:

1. **Sub‑word layer** – domain words are re‑tokenised so they split into fewer, better‑fitting pieces.
2. **Macro token layer** – repeated spans such as short expressions, whole lines or entire JSON envelopes are collapsed into one “macro” token, identified by five mining algorithms.

The selection is weighted by where a token is saved. In the grader, writing a token cost 7.4 times as much as reading one, so a token saved in the model's answer counts for far more than one saved in the prompt.

The new tokenizer reduces the vocabulary from 151,669 entries to 64,767 and cuts the average response length from 350 to 101 tokens. Across seven versions trained the same way, with only the tokenizer changed, the final one cut measured inference cost by 77% on an RTX 5090 running vLLM, and its score on the authors' own benchmark rose from 0.703 to 0.810.

The method was tested across five public domains—contracts, medical papers, scientific papers, news, and Python code—and three model families (Qwen3, Llama‑3.1, Gemma‑3). In every combination it compressed more than the strongest reference method by 1.2 to 9.3 points.

Two caveats before anyone gets excited. The paper behind it is still under review and the numbers may change. And as [RuntimeWire noted](https://runtimewire.com/article/dharma-ai-vocabx-inference-cost), the 77% is company‑measured on one workload. The idea itself isn't new: [AdaptiVocab](https://arxiv.org/abs/2503.19693v2), published in 2025, adapted vocabularies to niche domains and reported cutting token usage by over 25% without hurting performance.

## Why it matters beyond AI labs

In my experience, the small models firms actually run tend to do repetitive, structured work: compliance checks, document classification, data extraction. Where a firm hosts the model itself, I think the savings from VocabX could be substantial because:

* **Output tokens can dominate** – in the grader, writing a token cost 7.4 times as much as reading one, though the authors say that ratio varies with hardware, task, batch size and context length.
* **Domain specificity** – many tasks use a fixed set of keys, phrases, or code snippets that can be collapsed into macro tokens.

That covers more than finance: an insurer's claims triage model writing the same assessment fields, a legal team's contract‑review model tagging standard clauses, a health care administrator's model coding forms. Any team that asks a small model to fill in the same template thousands of times a day is paying to write the same JSON keys over and over.

### Worked example: Trade Confirmation Parser

Take a hypothetical bank that runs a small self‑hosted model to read trade confirmation emails and produce a JSON record with fields like `counterparty`, `instrument`, `break_reason`, and an optional comment. The JSON skeleton is identical for every email, while the `break_reason` field contains the decision that matters.

Applying VocabX would:

1. Collapse the JSON keys into macro tokens, reducing the number of output tokens.
2. Keep the `break_reason` token separate to avoid compression‑induced quality loss (in the Dharma‑AI study, fusing the grade into a macro token dropped the bench score to 0.689, below the original grader's 0.703, while giving the grade its own token cost two extra tokens and scored 0.810).

How much that would save is unknown until it's measured on the bank's own data and hardware. The 77% does not transfer.

## What I'd watch out for

| Risk | Mitigation |
|------|------------|
| **Single‑company benchmark** – The 77% figure comes from one workload on one machine, scored on the authors' own benchmark, in a paper not yet reviewed. | Run your own microbenchmark on representative data and hardware before adopting. |
| **Tokenizer changes require model retraining** – A new tokenizer means re‑training or fine‑tuning the model. | Treat the tokenizer as a separate artefact in your version control; perform golden‑set regression tests after each update. |
| **Compression hurts decision tokens** – The failed VocabX variant fused grades into macro tokens and scored worse than the model it replaced. | Identify which output spans carry critical decisions; keep those as individual tokens. |
| **Limited gains on input‑heavy tasks** – If the model reads long documents but writes short answers, savings may be smaller. | Measure token ratios (generated vs read) for your specific workload. |
| **Model lock‑in** – A custom tokenizer ties you to a fine‑tuned, self‑hosted model. | Keep the tokenizer definition portable; document how it was derived so future teams can rebuild or swap models. |

For governance, a tokenizer change is a model change. Under [the governance standard](../../blog/posts/governance.md) it has to pass the eval gate against a golden set before promotion (MODEL-02, EVAL-01), and the cost saving should be logged as a measured effect, not assumed (COST-03).

## What I'd try next

1. **Measure my own read/write ratio** – The 7.4× cost ratio between generated and read tokens may vary with hardware, batch size or context length. Before touching a tokenizer, I'd measure that ratio on my own workload; if output is a small share of cost, the case is weak.

2. **Hosted API question** – Many firms use managed LLM services rather than hosting models. The sources don't address whether any of this applies there, so I'd treat it as a self‑hosting technique until shown otherwise.

3. **Fine‑tuning with n‑gram tokens** – The 2025 AdaptiVocab work reported over 25% fewer tokens using a lightweight fine‑tune on a single GPU. Comparing that simpler approach with VocabX's macro tokens, once the VocabX paper is out, would show how much the cost weighting adds.

4. **Count the repeated output** – Before any tokenizer work, I'd take a week of a model's outputs and measure what share of tokens are fixed keys and stock phrases. That number bounds what a macro‑token layer could ever save.

What would change my mind is an independent replication, or the published paper showing the saving holds on ordinary batch sizes and other GPUs. Until then, I'd treat the vocabulary as a cost lever worth testing on my own workload, not a saving to bank.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
