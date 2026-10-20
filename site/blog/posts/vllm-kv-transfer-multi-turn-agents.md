---
date: 2026-10-20
slug: vllm-kv-transfer-multi-turn-agents
short: "Faster later turns for agents"
categories: [Agents, Operations, Self-hosting]
tags: [vllm, kv cache, disaggregated serving, ttft, latency, inference, nixl, AutoPublished]
audience: [AI and ML engineers, CTOs and heads of technology, Data engineers]
section: AI insight
---

# Bi‑Directional KV Transfer in vLLM: When It Helps Multi‑Turn Agent Latency

The complaint I'd expect from analysts using an in‑house agent is that it gets slower the longer they work with it.
Every turn sends the whole conversation back to the model, and the wait before the first word grows. A new vLLM
feature cuts that wait for teams that serve their own models in a particular way. The decision for most teams is
whether they're in that group at all, and if so, to measure before switching it on.

<!-- more -->

## What it is

The [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/improve-ttft-for-multi-turn-agentic-workloads-with-bi-directional-kv-transfer-in-vllm/)
(19 Oct 2026) and the [vLLM blog](https://vllm.ai/blog/2026-10-12-bidirectional-kvxfer-multiturn-agentic-workload)
(12 Oct 2026) describe a feature that lets the decode server send its key‑value (KV) cache, the model's working
memory of the conversation, back to the prefill server for the next turn.

It only applies to disaggregated serving, where one machine reads the prompt (prefill) and another writes the answer
(decode). Normally KV data flows only from prefill to decode. On the next turn the prefill server can't reuse what
decode holds; it recomputes the latest reply, and if it has dropped the session from its own cache, it recomputes
the whole history.

With bi‑directional KV transfer:

* The decode server keeps a finished conversation's KV blocks for a configurable time
  (`decoder_kv_blocks_ttl`, default 480 seconds), fixed and not renewed.
* A lightweight router remembers, per `conversation_id`, where those blocks are stored. It stores only metadata, not
  the KV data itself.
* On the next turn, if at least 64 tokens can be reused (the default threshold), the prefill server fetches them from
  decode and computes only the new part locally; below that it simply recomputes.

It was built and validated first on AWS Trainium, then contributed to vLLM as a hardware‑independent feature.

## Does it apply to you?

Three questions decide it:

1. **Do you run disaggregated prefill and decode yourself?** If you call a hosted model, this isn't something you
   control.
2. **Do users come back within the retention window?** A turn that arrives after the 480‑second default falls back to
   normal prefill.
3. **Does your prefill server actually lose sessions?** The biggest gains in the benchmark come from simulating that
   case, so your eviction rate sets most of your upside; without eviction, prefill still saves recomputing the last
   reply.

## Why it matters beyond AI labs

Long, multi‑turn sessions are where the effect shows. In financial services that's a research or operations agent
working through one filing or one batch of trade breaks. In customer service it's a case kept open across many
messages. In software engineering it's a coding agent whose context grows with every file it reads. In each, the
early turns are quick and the later ones are where the waiting builds up.

### Worked example (hypothetical): an internal research assistant

Picture an investment firm serving its own open model to analysts who spend 20 turns with an agent on one filing,
pausing a minute or two between questions, which keeps them well inside the retention window. Its gain would depend
on its own cache‑miss rate and hardware.

The published benchmark gives a sense of scale. It's a deliberately hard case: one prefill and one decode server on two `p5en.48xlarge`
instances connected by EFA networking, with prefix caching turned off on prefill to simulate lost sessions. Running
Qwen3‑32B without the new feature, TTFT climbs from 158 ms at 2k tokens to 778 ms at 24k tokens. Enabling
bi‑directional KV transfer brings that down to 122 ms and 460 ms respectively, which AWS calls about a 1.6× improvement
at the longest prompt; for GLM‑5‑FP8 (500 ms to 2,334 ms off, 358 ms to 702 ms on) it reports up to about 3.3×. The cost of moving the KV blocks between servers
(30–130 ms for Qwen3‑32B) is far less than the compute it saves. Both posts say results depend on workload, model,
hardware and network.

## What I'd watch out for

| Issue | Why it matters | Control |
|-------|----------------|---------|
| **Prefix caching disabled in benchmarks** | Gains depend on how often the prefill server loses sessions. If yours rarely does, the benefit may be smaller. | Measure your cache misses before switching it on. |
| **Router state loss on restart** | The router keeps its map in process memory, and a restart clears it; my inference is that later turns then fall back to normal prefill. | Treat router restarts as a performance event and monitor TTFT after deploys. |
| **Fixed retention window** | Conversations idle longer than the TTL lose the benefit. The vLLM post itself suggests a renewable lease as future work. | Compare your users' gaps between turns with the TTL. |
| **Additional network traffic** | My own concern, not one the posts raise: an extra transfer between servers per turn could matter in busy environments. | Monitor network utilisation alongside TTFT. |
| **Version compatibility** | The AWS post says vLLM v0.21.0 or later; the vLLM post's reproduction uses v0.29.0 with PR #40186. | Pin the version you test. |

Changes to serving infrastructure should go through the same release and monitoring controls as any production
system; see [the governance standard](../../blog/posts/governance.md).

## What I'd try next

1. **Measure real eviction rates and turn gaps** – a week of logs on how long sessions run, how long users pause and
   how often prefill misses its cache tells you whether there's anything for this feature to save.
2. **Test a smaller deployment** – the benchmark used two large GPU instances; I'd want to see whether the gains hold
   in more modest set‑ups.
3. **Profile network overhead** – capture per‑turn transfer times next to the compute saved.

What would change my mind is results outside the test set‑up. Only one prefill and one decode server were
benchmarked, so a larger deployment, and a smaller one, would need to show the same pattern before I'd call this a
default.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
