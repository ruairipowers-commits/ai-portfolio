---
date: 2026-11-04
slug: ai-managers-evaluation-headache
short: "AI and judging people's work"
categories: [Teams & hiring, Human in the loop, AI governance]
tags: [performance reviews, management, survey, llm bias, shadow ai, AutoPublished]
audience: [Executives and boards, Hiring managers, Operations leads, "Risk, compliance and legal"]
section: AI insight
---

# Managers Say AI Is Making It Harder to Judge Their People

In a recent survey of 1,700 senior managers, more than half say that adopting AI has made it harder to evaluate their people’s work. At the same time, 39% already use AI to draft performance reviews and 58% expect to supervise more AI agents than human staff within a year. My takeaway: before you scale AI, decide how you will measure work done with it, and keep AI out of unchecked judgments about people.

<!-- more -->

## What it is

The findings come from a Monday.com‑commissioned survey conducted by Nielsen across seven countries, reported by [TechCrunch](https://techcrunch.com/2026/10/21/ai-promises-productivity-but-for-managers-its-mostly-a-headache-for-now-says-new-survey/) and [The AI Insider](https://theaiinsider.tech/2026/10/22/ai-adoption-makes-it-harder-for-managers-to-evaluate-staff-monday-com-survey-finds/). Respondents were directors and senior managers; the countries, fieldwork dates and question wording aren’t given in either report.

The numbers my argument rests on:

* **More than half** say evaluating staff has become harder since adopting AI, and nearly **half** spend more time reviewing and guiding their teams’ output. Work now “arrives polished,” which makes it hard to tell what came from the person and what from the tool.
* **78%** have changed how they evaluate employees, putting more weight on prompting skills and deciding what to delegate to AI.
* **39%** use AI to draft performance reviews.

The report calls supervising AI agents “a new layer of invisible labor.”

## Why it matters beyond AI labs

In my own field, polished output was never the test. A research note or a reconciliation report is judged on whether its numbers tie out and whether its calls held up. AI makes that discipline more important, because polish now costs nothing.

### Worked example: a research team in finance

Picture an analyst who drafts market notes with an LLM (my illustration, not a survey finding). The manager can’t judge skill from the prose any more. What still tells you something:

1. **Errors caught** – how many problems the analyst found in the AI’s draft before it went out.
2. **Calls that held up** – whether the note’s conclusions were right when checked later against market data.
3. **AI use logged** – a simple flag on each note saying whether AI drafted it, so the comparison is fair.

### A second example: customer service quality scoring

The same logic applies to a contact centre where agents reply with AI help. Scoring replies on tone tells you little when every reply reads well. Scoring on whether the customer’s problem was solved, and whether the agent overrode a wrong AI suggestion, tells you more. This is my illustration, not a finding from the survey.

Whether every knowledge‑work sector feels this the same way is my view, not something the survey measured; it didn’t break results down by industry.

## What I'd watch out for

### Bias in AI‑drafted performance reviews

A [2026 IZA discussion paper](https://econpapers.repec.org/RePEc:iza:izadps:dp18371) by Rilke and Sliwka tested LLMs as raters. Rating individuals one at a time without objective standards, they repeat familiar human biases. Rating several people at once, their ratings were more spread out and more accurate, and given noisy but objective performance signals they beat human raters.

So if AI drafts reviews at all, the setup matters: feed it objective performance data, have it rate the team as a set rather than one person in isolation, and treat its output as a draft for a human to own.

### Accountability for AI decisions

With **35%** of managers fearing responsibility for AI‑made decisions, the fix is to name who owns the final decision. That is the named‑approver control (HITL‑02) in [the governance standard](../../blog/posts/governance.md): a review about a person is a consequential decision, so a human signs it.

### Tool sprawl and shadow AI

Only **29%** of respondents describe their AI infrastructure as fully optimised and centralised, yet **57%** report more tools in circulation than before. Monday.com’s Michal Miller Levi notes that firms expected AI to shrink their software stacks, but tool and shadow‑AI use grew. My own inference: unapproved tools are exactly where review drafts can escape any governance.

### Who paid for the survey

The survey was commissioned by Monday.com, a provider of work‑management software that has an interest in the topic. Both reports I read describe the same survey, so I’d want an independent study before making big decisions on these numbers.

## What I'd try next

If I were setting this up, I’d start with four things:

1. **A review rubric built on objective signals** – errors caught, calls that held up, turnaround – with the AI‑use flag beside each piece of work.
2. **A log entry for every performance review** saying whether AI drafted any of it, and what data it was given.
3. **A named human approver on every review** (HITL‑02), with no AI draft sent without that sign‑off.
4. **Risk tiers for AI use** (HITL‑01): drafting a meeting summary is low risk; drafting a judgment about a person is high.

What would change my mind: an independent study, not vendor‑commissioned, showing that managers’ difficulty evaluating work fades within a year or two as processes catch up. Then I’d treat this as a transition cost rather than a reason to redesign how work is measured.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
