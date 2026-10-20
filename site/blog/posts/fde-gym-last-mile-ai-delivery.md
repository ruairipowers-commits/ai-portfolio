---
date: 2026-10-20
slug: fde-gym-last-mile-ai-delivery
short: "FDE-Gym: the unwritten requirements"
categories: [Agents, Evaluation, Human in the loop]
tags: [fde-gym, benchmarks, ai agents, forward-deployed engineering, requirements, evaluation, AutoPublished]
audience: [CTOs and heads of technology, Hiring managers, Product managers, AI and ML engineers, Operations leads]
section: AI insight
---

# FDE‑Gym: A Benchmark for the Messy Part of AI Delivery

In my experience, delivery projects rarely go wrong on the code. They go wrong on a rule nobody wrote down: an approval step,
a cut‑off time, a person who has to sign off. A new benchmark, FDE‑Gym, tests AI agents on exactly that kind of work,
and its headline finding is that they struggle with the same thing. If you're deciding where an agent can take on
change work, it's worth reading because it scores the part that matters: finding the unstated rules, with an
incident counting as zero.

<!-- more -->

## What it is

FDE stands for forward‑deployed engineer: someone who delivers working systems inside a customer's environment. The
paper, presented on [Hugging Face's Papers page](https://huggingface.co/papers/2610.22350), argues that real
delivery means clarifying vague requests, working in live systems and uncovering constraints nobody stated, and that
most agent benchmarks skip all three.

FDE‑Gym has 95 end‑to‑end tasks from 20 customer scenarios across 18 sectors, adapted by industry experts from real
projects; the [README on GitHub](https://github.com/deeplethe/fde-gym) names banking, healthcare, logistics,
manufacturing and energy among them. Each task starts with a short paragraph from a customer sponsor, which may not
describe what actually needs building. The AI agent works in a simulated customer environment, can message scripted
stakeholders and change systems, and is judged on how much the customer's own success metric improves.

The scoring is what makes it useful:

* Improvement runs from 0 (system unchanged) to 1 (the reference solution).
* Stakeholder interactions (messages, trial runs and waiting time) are penalised.
* A production incident caps the score at zero.
* A task counts as resolved at 0.8 or more with no incident.

The authors tested 13 model configurations from seven providers. In the realistic setting, the best achieved a mean
score of 0.56 and resolved 14 of the 95 tasks. They name discovering unstated constraints as the main bottleneck. My reading is that it isn't the only one: on the 23
tasks where the best configuration got every key fact from the stakeholders, it still reached 0.8 on only 10. In a
comment on the paper, the authors add that withholding unstated constraints costs leading models 0.28, and that a
misdirected request costs little more than that.

## Why it matters beyond AI labs

Most AI evaluation uses clean, well‑defined tasks. FDE‑Gym deals with vague requests, hidden rules and live systems
where a mistake causes an incident. That's what internal change work looks like in any organisation.

### Worked example (hypothetical): banking operations

This is an illustration of my own, not one of the benchmark's cases. A bank's operations team asks an agent to
"reduce failed trade settlements." The request looks simple, but the real constraints are:

* Which settlement exceptions must still be approved by a human?
* What contractual cut‑off times apply to different asset classes?
* Who signs off changes to the matching rules?

An agent that simply tweaks the matching engine to lower the failure rate may cause a production incident if it
breaks any of these. FDE‑Gym would score that delivery zero even though the metric improved, which is the right
answer.

Other sectors have their own versions of these unwritten rules; in healthcare, logistics or manufacturing they might
be privacy obligations, contractual delivery windows or safety sign‑offs. The README's list of what the cases train is
a decent checklist for any of them: what can be automated, what needs a person, and who decides.

## What I'd watch out for

* **Simulation vs reality** – The benchmark uses scripted stakeholders in a controlled environment. Real people
  contradict each other and change their minds, so real delivery is probably harder.
* **Negative impact** – The authors note that weak models often leave the customer worse off than doing nothing. Any
  production change by an agent should pass a human gate before it goes live.
* **Interpretation of the mean score** – The 0.56 figure does not mean agents do half the job. It is a normalised
  uplift relative to a reference solution, less the interaction penalties, averaged across tasks, and only 14 of 95 were resolved.
* **Early days** – The project's README describes it as early, and the human practice site opens on 1 November 2026.
  I couldn't read the leaderboard, so I'm not naming which models did best.

Human approval before production is a control in [the governance standard](../../blog/posts/governance.md) I use for
this site.

## What I'd try next

Before handing any agent a change request, I'd do what the benchmark rewards:

1. **Write down the unwritten rules first** – the approvals, cut‑offs and sign‑offs a person would have to discover,
   so the agent doesn't have to guess them.
2. **Score a pilot the way FDE‑Gym does** – improvement in the business metric, minus the staff time the agent used,
   with any incident counted as failure.
3. **Try an open case myself** – three cases are public on Hugging Face (the authors ask that nobody train on them);
   I'd work one with an agent before reading anyone's write‑up of it.
4. **Compare people with and without an agent** – the human practice site uses the same scoring, so how experienced
   delivery engineers score is the comparison a hiring manager needs.

What would change my mind about where agents fit: a configuration that clears 0.8 on most tasks once it has the
facts. Until then, finding the unwritten rules is still the person's job.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
