---
date: 2026-10-03
slug: choosing-the-ask-model
short: "Choosing the Ask button's model"
categories: [Evaluation, Self-hosting, RAG & retrieval]
tags: [ollama, gemma4, qwen3.5, llama3.1, benchmark, prompt design, local models]
---

# Picking the model behind the Ask button: measure on the box it runs on

The [Ask button](site-assistant.md) runs a local open model on a mini PC in my house. I swapped that model after
measuring three candidates on that same machine. The winner was more than twice as fast and more accurate, and it
was the only one that consistently followed the rules.

<!-- more -->

**Stack:** Ollama, Python, FastAPI, SQLite FTS5

## The problem

The assistant answered from the blog with `llama3.1:8b`, running on the CPU of a GMKtec EVO-X1. It worked, but:

- **It felt slow.** Just loading the model and reading the prompt took close to half a minute, which is too long
  for someone deciding whether to keep reading.
- **It undersold me.** Asked "would Ruairi be a good fit for…", it rarely mentioned my MIT coursework or the newest
  projects. It couldn't: it only saw the site's pages, not the GitHub docs or my resume.
- **It handled gaps badly.** When asked about a skill the site doesn't show, I want an honest answer that thanks the
  asker and treats the gap as something to learn. Mostly I got a flat "no".

## The goal

- An answer that starts within a few seconds and finishes in under 20.
- Every claim cited, with roles, MIT courses and projects named and dated.
- Gaps handled honestly and framed as a chance to grow.
- Still free and local: no API bill, and no questions leaving my machine.

## The approach

**Fix what the model sees before choosing the model.** No model can cite a course it was never shown. So the site
build now generates a profile card from the posts: background, both MIT courses, evidence by topic, the technologies
each project uses, and the newest work first. Every prompt starts with it. The assistant also reads the project
READMEs and docs on GitHub, the capstone notebook and my resume.

**Measure on the real machine.** I added a `siteassist bench` command. It loads each model and asks three questions
twice:

- a fit question: "head of AI at a small investment firm?";
- a gap question: "Kubernetes and Rust?" (the resume lists Kubernetes; nothing shows Rust);
- a technical question about the governance console's kill switch.

It records the load time, the time to the first word, the total time, and reading and writing speed. It writes every
answer to a file so I can judge them side by side.

**Read the answers, then fix the prompt.** The first round was humbling.

- `qwen3.5:9b` misspelt my name, described an optional AWS design as how the kill switch works today, and counted
  "Pydantic is written in Rust" as Rust experience.
- Only `llama3.1:8b` used the growth wording for the gap.

Small models follow what they read last. So questions about me now end with a five-line checklist:

- exact spelling of my name;
- a citation for every claim;
- a related fact is not experience;
- the exact wording for a gap;
- point to the About page and resume.

The rules at the top stay word-for-word the same, so the model can reuse its cached reading of them.

## The solution

The second round, same questions and same machine (CPU only):

| | `gemma4:e4b` | `qwen3.5:9b` |
|---|---|---|
| Time to first word | 6–10 s | 12–27 s |
| Full answer | 10–18 s | 25–55 s |
| Writing speed | ~28 tokens/s | ~12.5 tokens/s |
| Fit answer | Senior roles, both MIT courses and four dated projects, all cited | Fuller, but misspelt the name again |
| Gap answer | Kubernetes from the resume; Rust handled with the growth wording | Same, after a detour through Pydantic |
| Kill switch | Accurate | Presented the AWS option as how it works today |

`gemma4:e4b` is now the default. It's Google's on-device size, so it's fast enough on a CPU and stays accurate when
the prompt is strict. `llama3.1:8b` had been slowest to load in the first round (27.5 s), so I didn't carry it
forward.

The gap answer now reads:

> Thank you for asking about Rust! The site doesn't show Rust experience yet. Ruairi is excited to hear more about
> what he may not know and sees it as a chance to grow, so it's now on Ruairi's plate to review.

That phrase isn't just a nice ending. My daily email lists every question about me, and any answer containing "on
Ruairi's plate to review" goes onto a learning list.

## What I'd do next

- **Use the iGPU.** On the second run, time to the first word barely improved. Reading the prompt (about 450
  tokens/s on the CPU) dominates, and with this model the cache seems to help little. Ollama's Vulkan backend can
  put that reading on the Radeon iGPU, and the setup guide shows how. Re-running the bench will show whether it
  helps.
- **Score the answers automatically.** Today I judge them by reading. Checks for the name's spelling, a citation per
  claim and the growth wording would turn the bench into an eval gate, like the retrieval golden set already is.

The lesson is the one I keep relearning: don't pick a model from a leaderboard. Pick it on your own hardware, with
your own questions, after you've fixed what it's allowed to see.
