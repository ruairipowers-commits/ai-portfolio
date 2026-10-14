---
date: 2026-10-14
slug: aescode-design-as-code
short: "Design as editable code"
categories: [Research, Evaluation, Human in the loop]
tags: [aescode, microsoft, code generation, dashboards, reporting, vision-language models, reinforcement learning, reward design, html]
audience: [CTOs and heads of technology, Heads of data, Product managers, AI and ML engineers]
section: AI insight
---

# AesCode: when an AI designs your dashboard, ask for code, not a picture

A Microsoft research team has trained a model that turns a content prompt into the code for a slide, poster,
dashboard or web page, using an AI-generated image as its design reference. What caught my attention is the output:
HTML and CSS that a person can open, check and change. And the training method splits what code can verify from what
needs a judge, which is how I'd want any generated document checked.

<!-- more -->

## What it is

[AesCode](https://huggingface.co/papers/2610.18860) was posted on 13 October by a 16-person team tagged as
Microsoft. You give it a content prompt. An image model draws a picture of what the result might look like, and
AesCode writes the code for that design. The prompt decides *what* to say; the reference image suggests *how it
should look*.

According to the [project page](https://microsoft.github.io/AesCode/), the output is editable HTML and CSS. Photos
and complex illustrations aren't drawn: they become gray placeholders that hold their place in the layout.

The training method is the part I'd borrow. Each design is described as a "design graph", and its quality is scored
through two separate channels. Properties that can be read from the code and the rendered page are scored by
deterministic checks. The rest is left to a vision-language model acting as a judge, with a rubric written for each
example. The two channels feed reinforcement learning as separate rewards, each normalised on its own, presumably so
that neither drowns out the other.

The team post-trained existing 8-billion and 32-billion parameter models rather than training from scratch, using
3,000 worked examples and then 7,408 reinforcement-learning prompts. Both models are on Hugging Face and the code is
on GitHub. The page doesn't state a licence, or whether the training data is released.

They also built a benchmark that scores rule-following and visual quality separately. On the project page's
evaluation, 300 infographic prompts with three attempts at each, averaged, no cherry-picking and the same reference
images for every model:

- AesCode-32B scores 85.89 out of 100 overall, 77.44 on visual quality and 94.33 on following the rules.
- On visual quality, given the same reference images, the 8B model beats a same-size Qwen3-VL baseline by 31.1
  percentage points, and the 32B
  model beats its own baseline by 22.4. The authors say that puts them in the same range as GPT-5.5 and Claude
  Opus 4.8.
- Style is weak across the board. With references, GPT-5.5 scores 57.91, Opus 4.8 55.51 and AesCode 53 to 56.
  Every model tested is below 60, so expect a designer to finish anything that carries a brand.

One finding applies to tools you may already use: simply giving an existing model a reference image noticeably
improved the visual quality of the code it wrote.

## Why it matters beyond AI labs

Most organisations produce the same visual documents over and over. Today there are two poor options: someone
rebuilds the document by hand each time, or an image model produces something attractive that nobody can edit or
check. Code sits between the two, and the split between checked and judged is what makes it usable in regulated
settings.

Here's a hypothetical. Say you produce a monthly fund performance one-pager:

1. The figures come from the data pipeline, never from the picture.
2. A model proposes the layout as HTML.
3. Deterministic checks confirm that every required number, disclaimer and date is present.
4. A person edits the wording in place and approves it.

The same pattern carries across sectors, with a different rule in the code at step 3:

- **Insurance:** a policy summary must contain the required disclosures, in full, on the first page.
- **Healthcare:** a patient leaflet must show the dosage and warning fields exactly as they appear in the source
  record.
- **Retail and consumer goods:** a product sheet must match the price and specification held in the product
  database.

In each case a model can propose how it looks, and code decides whether it's allowed to go out.

## What I'd watch out for

**The reference picture can make things up.** The authors say reference images can contain hallucinated content.
In a dashboard, that's a number that looks right and isn't. Every figure has to come from the data, and a check
should compare what's rendered with what's in the source. On this site that's an output check before anything is
published, as set out in [the governance standard](governance.md).

**A good-looking layout isn't a correct one.** Part of the reward comes from a model judging appearance. That's
reasonable for layout and style. It says nothing about whether the content is right, so the deterministic channel
matters more for anything that goes to a customer or a regulator.

**Brand and accessibility should be rules, not taste.** Colour contrast, fonts, logo placement and required
disclosures can be checked in code. Left to a judge, they'll be met most of the time, which isn't the same as every
time.

**Fine detail and complex layouts are weak spots.** The authors list fine icon detail and complex spatial
relationships as limits. Dense dashboards and multi-panel charts are exactly where those show up.

**The licence isn't stated.** The models are downloadable, but I wouldn't use them commercially until the licence is
clear.

## What I'd try next

I haven't tested any of this myself. I'd take one recurring report, generate its layout from a reference image with an
existing model, and write the deterministic checks first: required fields, numbers matching the source table, nothing
cut off. Then I'd measure how often a person still has to fix something. If that rate is low, the code-first
approach earns its place. If not, the picture was never the bottleneck.

What would change my mind: results on real corporate templates rather than infographics, and the cost of running
the 32B model, which neither the paper nor the project page covers.

*Drafted with AI agents from a topic my scout found, then edited and approved by me.*
