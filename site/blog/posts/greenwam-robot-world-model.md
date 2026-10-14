---
date: 2026-10-14
slug: greenwam-robot-world-model
short: "One model for many robots"
categories: [Research, Evaluation, Operations]
tags: [greenwam, robotics, world models, foundation models, humanoids, logistics, benchmarks, sber]
audience: [Executives and boards, CTOs and heads of technology, Operations leads, AI and ML engineers]
section: AI insight
---

# GreenWAM: one model that predicts and acts across 20 kinds of robot

Robots usually need two pieces of software: one that predicts what will happen when the robot moves, and one that
decides what to do. A new technical report from Sber Robotics Center builds both into one model and trains it across
20 robot families. The benchmark results are strong. The more useful number for anyone buying or backing robotics is
how fast its success rate falls when the scene changes.

<!-- more -->

## What it is

[GreenWAM](https://arxiv.org/abs/2610.18774) was submitted on 13 October by a five-person team at Sber Robotics
Center. It starts from a problem anyone who has worked with mixed equipment will recognise: every robot records its
movements in its own format, and the software that predicts the world (a "world model") is usually built and tested
separately from the software that acts (a "policy").

GreenWAM does both. It maps 20 robot families onto one shared set of 79 joint coordinates, so a single set of weights
can drive different bodies. The paper describes the range as running from two-armed robots to dexterous humanoids;
the [project page](https://greenvla.github.io/GreenWAM/) describes the training families as two-armed. It's built on
Cosmos 3 Edge 4B and trained on 1,688.5 hours of data, 74% of it from real robots. When it acts, it predicts the video
of what's about to happen alongside its planned movements, carries out the first part of the plan, then replans.

The headline results:

- **As a world model:** top-tier trajectory, depth and 3D accuracy on WorldArena 1.0, outperforming every world-action
  model and video generator it was compared with.
- **As a policy:** 86.98% success in clean scenes and 48.10% in randomised ones on RoboTwin 2.0, across 50 tasks
  with 100 trials each, among the top entries. It completes 4.64 instructions per chain on CALVIN, against 4.53 for
  FLOWER.
- **A harder benchmark:** on RoboDojo, its success rate is 10.49%. That's still higher than π0.5, X-VLA and X-WAM,
  but a reminder of how far there is to go.
- **On a real robot:** on the team's "Green" humanoid, doing one packing task across 70 instructions and 14 scene
  set-ups, five of them unlike its training, it succeeded more often than policies adapted from π0.5 and Cosmos 3
  Edge. Neither the paper nor the project page gives the success rates.
- **Speed:** a distilled one-step version runs in 35.4 milliseconds on a single RTX 4090, about 28 times a second,
  which is fast enough for real-time control.

The weights are on Hugging Face and the code is on GitHub. No licence is stated.

## Why it matters beyond AI labs

Warehousing, manufacturing, retail fulfilment and logistics often run mixed fleets: arms from one vendor, mobile
robots from another, a humanoid pilot from a third, each with its own software and its own data.

What follows is my speculation, not something the report shows. If a shared action space holds up outside the lab, a
logistics operator with three robot types could pool its data: what one fleet learns might improve the others. The
report's evidence for this is narrower. It shows that specialising a model for robots improves both its predictions
and its control, and it reports the highest zero-shot success on LIBERO-plus among the methods compared.

In practice a changed scene is mundane: new packaging on a pick line, different lighting on a night shift, a shelf
moved a few centimetres. Before deploying, I'd want a buyer to run the robot on exactly those changes, deliberately,
and compare its success with the clean case.

If the pooling idea does hold, the advantage in robotics would shift towards whoever has the most varied real-world
data, and away from single-purpose software. That's the question I'd keep asking as an investor or a buyer.

## What I'd watch out for

**Changed scenes are where it fails.** This is the number I'd lead with. In randomised scenes, success falls from 85% to 27%
as the model's imagination error grows: the further its picture of the scene drifts from reality, the worse it does.
(That's a different cut from the 86.98% and 48.10% overall figures.) The failure review is telling. Of 20
failures in clean scenes, 19 had imagined the scene correctly, so they failed for other reasons. Of 20 failures in
changed scenes, 13 involved misreading or mis-imagining what was in front of it. A warehouse is a changed scene every
day. Testing against conditions the model hasn't seen, and watching for drift once it's live, are the controls I'd
insist on, in line with [the governance standard](governance.md).

**Real-robot evidence is thin.** The real-robot test covers one humanoid and one task, and the page gives no success
rates for it. The large numbers above all come from benchmarks.

**The model mustn't be the safety system.** Physical robots need hard limits on force, speed and stopping that sit
outside the model and can't be overridden by it. A model that's right most of the time is not a safety case.

**Each benchmark had its own fine-tuning.** The team adapted the model separately for each benchmark, so these aren't
the scores of one model doing everything at once.

**Licence and full model size aren't stated.** The only size given is the 4B base model.

## What I'd try next

If I were evaluating robotics vendors, I'd ask each of them a question GreenWAM has started to answer on benchmarks but
not yet on real hardware: what's your success rate in clean scenes, what is it when the scene changes, and how do you
know? A vendor without that split hasn't tested for the conditions it will actually meet.

What would change my mind: real-robot success rates across several robot types and tasks. The report has early hints
beyond its training data, in the zero-shot LIBERO-plus results and the five unfamiliar real-robot scenes, but not yet
the field numbers I'd want before trusting a mixed fleet to one model.

*Drafted with AI agents from a topic my scout found, then edited and approved by me.*
