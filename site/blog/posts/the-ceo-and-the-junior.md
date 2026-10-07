---
date: 2026-10-07
slug: the-ceo-and-the-junior
short: "The CEO and the AI junior"
categories: [AI governance, Human in the loop, Teams & hiring]
tags: [ai governance, accountability, ai-assisted development, code review, verification, leadership, ai literacy]
audience: [Hiring managers, Executives and boards, CTOs and heads of technology, AI and ML engineers]
section: AI insight
---

# I didn't write most of this site. Here's why I'm still accountable for all of it

There's an irony in this portfolio, and a fair reader will spot it. It sets out to show I can use AI under proper
governance, yet an AI assistant wrote most of what's on it. So do I actually have command of the content, or is
the AI governing itself while I watch? This is how I think about that paradox, and how I handle it.

<!-- more -->

## The paradox, stated plainly

Count the commits. At the time of writing, 93 of the 97 in this site's repository carry a `Co-Authored-By: Claude`
line. That covers most of the code, most of the tests, most of the documentation and the first drafts of most of the
posts. The four without it are three pull-request merges, which are me approving work into the main branch, and a
short note. Even the commits under my own name, the governance standard the site runs on, its licence and the rules
for who may reuse it, were co-written. What I authored, in the sense that matters, were the decisions.

Two readings of that number are possible:

- **The facade.** Someone who can't do the work has had a machine produce something that looks like work. The
  governance console, the eval gates and the 30 controls are props. Ask one hard question and it collapses. Worse,
  a governance showcase built by an AI that nobody qualified checked would be the very failure it claims to prevent.
- **The leverage.** Someone who knows the domain has done what any leader does: set direction and standards, then
  had a capable junior do most of the typing, under review. A CEO doesn't write the financial model or format the
  board deck, and nobody concludes they don't understand the business.

Both readings are possible from the outside, and the commit count can't tell them apart. What decides it is how the
work is run. That's what this post is about.

## The model I use: CEO and junior

I treat the assistant as a fast, tireless and occasionally overconfident junior employee. It's very good, and it's
also capable of reporting "done" on something that isn't. That's not a criticism; capable juniors do it too. The job is to run the relationship so its speed becomes my leverage, not my
risk.

What follows is six habits. None is clever. Together they're the difference between the two readings above.

### 1. Probe the report

A junior's summary is a claim, not evidence. When the assistant tells me something passed, I ask what exactly ran,
how many cases, and what it didn't run. The repo's standing instructions in
[`CLAUDE.md`](https://github.com/{{GITHUB_OWNER}}/ai-portfolio/blob/main/CLAUDE.md) make that the default: never
claim a result you didn't run, and never push or publish without my approval in the conversation.

This week tested that. The assistant came back to a project it had built the day before, a
[data marketplace platform](data-lifecycle-platform.md), with no memory of having built it: its working context
had been cleared. It found the work from the repo's status file and history. Before pushing, it re-ran the 43
tests, the end-to-end pipeline, the eval gate and the governance check itself, rather than trust a report it
couldn't remember writing. That's the behaviour I want from a junior who's inherited a half-finished handover.

### 2. Own the concepts, not every line

I don't write every line, but I own what the lines are for. Every project starts as a spec, and the assistant has
to stop and get my approval before it builds anything. The ideas that make a project worth looking at are mine. In
the data platform, they were keeping the ontology, the knowledge graph, the semantic layer and the context layer
apart, running the full data lifecycle, and choosing to model it as a marketplace. If I can't explain why a project
is shaped the way it is, without the site open, it doesn't belong on the site.

### 3. Stay hands-on enough to stay honest

I keep some of the work in my own hands, deliberately. The governance decisions went in under my name: the
standard, the licence and who may reuse what. I run the server and deployment steps myself, and I read the diffs
that matter. The point isn't to compete with the assistant on volume. It's to
keep my judgement calibrated, so I can tell when its work is good rather than just plausible.

### 4. Force transparency

A junior who hides mistakes is more dangerous than one who makes them. So everything is set up to be visible:

- every AI-written commit is labelled, so the history shows who wrote what;
- each project's governance mapping marks controls as built, partial or "option documented, not built", rather
  than claiming full coverage;
- every post says what's synthetic, what's mocked and what isn't built yet;
- a status file holds what's in flight, so nothing depends on one conversation's memory.

### 5. Install checks and controls, then let them fail

This is where most of the leverage comes from. Checks run on every change: tests, golden-set evals, a governance
check, a security scan and a check that each live app's real install has every library its code loads. I've
described the full chain in [how I govern this site](how-i-govern-this-site.md).

The checks earn their keep by catching what the junior missed. Three real ones from this week:

- **A test that passed for days, then didn't.** The governance console seeds a simulated history in which a
  workflow is switched off for a day. The assistant had scripted that day as "twelve days ago". When that date fell
  on a weekend, simulated traffic was zero, the event silently vanished, and a test failed only on certain dates.
  CI caught it; the fix was to use the next business day
  ([`6e0d709`](https://github.com/{{GITHUB_OWNER}}/ai-portfolio/commit/6e0d709)).
- **A failing deploy nobody looked at.** The site build refused to deploy three pushes in a row, over about six
  hours, because a generated catalog of projects was out of date. The check worked. What didn't work was attention:
  nobody looked until the next push. A check that fails quietly is half a control.
- **A library the live app didn't have.** Earlier, the console crashed on start-up because its code loaded a library
  the tests had but the real install didn't. The outside-in uptime check caught it, the fix was
  [`8bd1bb8`](https://github.com/{{GITHUB_OWNER}}/ai-portfolio/commit/8bd1bb8), and the lasting fix was a new check
  so that class of mistake now fails the build.

Each of these is the CEO model working as intended. I didn't find the bugs by rereading code. The system I insisted
on found them, and then I decided what the fix should become.

### 6. Dive into the detail where it matters, or where I'm curious

Oversight by checklist alone goes stale. When a result surprises me, or a design choice looks odd, I go down to the
line: read the code, run it, ask the assistant to walk me through it, and push back until the explanation is
specific. Some of that is risk management. A lot of it is curiosity, which I think is the more reliable motive,
because it doesn't wait for something to go wrong.

## What "accountable" means here

I take responsibility for everything on this site, including the parts I didn't type. Concretely, that means I hold
myself to being able to break and fix anything here. That doesn't mean reciting a file from memory. It means that
with the repo, its tests and some time, I can find a fault, explain it and fix it. If I couldn't, the project
wouldn't be finished.

There's an equally real limit in the other direction. If I rebuilt every piece by hand to prove I could, I'd have a
fraction of the portfolio and no more confidence than the tests already give me. Doing the work twice isn't
oversight. It's throwing away the leverage that's the whole point of using AI.

## Where the paradox still bites

I don't think this is fully solved, and pretending otherwise would undercut everything above.

- **There are lines I haven't read.** Review is sampled, guided by risk and by the checks. That's how oversight of
  any team works, but it's a choice, not a guarantee.
- **The checks were mostly written by the same junior.** Who checks the checker? Partly me: the checks are short and
  I read them. Partly independence: the uptime check runs from outside, on GitHub's servers, and that's the one that
  caught the console outage.
- **A passing test only proves what it tests.** The weekend bug passed for days. Green means "nothing I thought of
  is broken", not "nothing is broken".

## If you're evaluating someone like me

The commit count won't tell you which reading is true. Questions will:

| Ask | A facade answers… | Someone in command answers… |
|---|---|---|
| Why is it built this way? | By describing what it does | With the trade-off and the option rejected |
| What broke last week? | "Nothing" | With the failure, the cause, and the check it became |
| Pick a file: what if this input is wrong? | By opening the file | Roughly, then by running it to confirm |
| What's mocked or not built? | Vaguely | Precisely, because it's written down |
| Can you change this now? | Not without the AI | Yes, with or without it, more slowly without |

The same questions work for any leader whose team, human or AI, does most of the hands-on work. The skill that
matters is no longer typing the code. It's setting the standard, building the checks, reading the evidence and
knowing where to look when it's wrong. And it's still owning the result when it is.

*Drafted with Claude from my notes, then edited and approved by me. Which is rather the point.*
