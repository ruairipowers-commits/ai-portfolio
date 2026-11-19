---
date: 2026-11-19
slug: aws-emulator-agent-built
short: "AWS Emulator, built by agents"
categories: [Agents, Evaluation, Security]
tags: [AWS, AWS Emulator, local testing, CI, coding agents, supply chain, AutoPublished]
audience: [CTOs and heads of technology, Heads of data, AI and ML engineers, Data engineers]
section: AI insight
---

# AWS Emulator: What an Agent-Built Local Cloud Is Good For, and How the Agents Were Kept Honest

AWS has released a free local emulator of its APIs that, Amazon says, autonomous AI agents wrote without its team writing or reviewing the code. I'd use it as a disposable AWS sandbox for every developer and coding agent, with real-account tests kept for anything that matters, and I'd copy the way it was built. I haven't run it myself; the hands-on figures below come from someone else's test.

<!-- more -->

## What it is

AWS released a free program called **AWS Emulator** on 11 November 2026 ([the repository on GitHub](https://github.com/aws/aws-emulator)). The emulator runs locally on your machine, on a development server or in CI and answers AWS API calls, so you can test code without calling AWS. Not every AWS feature is there ([TechRadar](https://www.techradar.com/pro/a-new-aws-emulator-has-been-built-entirely-by-ai-agents-to-bring-its-cloud-straight-to-your-pc)). It was written entirely by autonomous AI agents, and the team hasn't written or reviewed any of the code, according to [Amazon's own description](https://www.aboutamazon.com/news/aws/how-autonomous-ai-agents-built-aws-emulator). The agents started from a three-step prompt:

1. **Write tests** based on the AWS CLI.
2. **Iterate until the tests pass against real AWS**, the reference.
3. **Build an in-memory implementation** that passes those tests.

A first version of Amazon SQS took about 15 minutes. It is released under CC0, and three agent teams keep it updated; more on how below. On Mac and Windows you run it in Docker; on Linux there are RPM and Debian packages.

Per AWS's stated limits, as reported by [Mulga Defense Corporation](https://mulgadc.com/blog/aws-emulator-local-to-production) (which sells a competing product): it is written in Rust; it matches control-plane APIs most closely, and data-plane behaviour varies by service; state is in memory only and disappears when the process stops; telemetry is on by default but can be turned off; and AWS advises against using it for security testing or production.

## Why it matters beyond AI labs

A local stand-in for AWS is useful to any firm on AWS that wants fast, free integration tests. An insurer could test a claims-document pipeline (S3 upload, Lambda, a DynamoDB status table) on synthetic documents the same way as the example below. Developers and coding agents can test against the AWS APIs without credentials and without a bill, and each instance has its own port, keys and state, so every pull request can get its own.

### Worked example: market-data ingestion

This is an illustrative scenario, how I'd set it up, not something I've run. A market-data team builds a Lambda function that pulls end-of-day vendor files from S3 and writes one row per file to DynamoDB. In a CI pipeline:

1. **Spin up a fresh emulator** for each pull request.
2. The coding agent writes tests that exercise the Lambda, S3 and DynamoDB interactions.
3. Tests run against the local emulator in seconds. In a [hands-on test on DEV Community](https://dev.to/ishank-dev/aws-emulator-hands-on-test-s3-lambda-and-dynamodb-locally-with-a-coding-agent-35bb), the median cold start was 375 ms, a coding agent built a similar Lambda, S3 and DynamoDB app with tests in about three minutes, and re-running those tests against a fresh emulator took 5 to 11 seconds.
4. A guard refuses to deploy unless the endpoint is a loopback address and the account is the emulator's. The tester's agents added a guard like this to their deploy script.
5. Keep test files small: the tester reports a cap of 1,000 objects per bucket, and single uploads over 8 MiB failed.

The CI run checks that the Lambda logic and the S3 and DynamoDB calls work. IAM policies and larger payloads still get tested in a real AWS test account.

## How the agents were kept honest

The bigger lesson is how it was built. The agents had a spec (AWS's API models, in Smithy), a reference (real AWS), tests checked against that reference, and a merge gate. Three agent teams run it: test writers build fidelity tests and verify them against real AWS, issue finders replay them against the emulator and file failures, and fixers take one issue each. The gate checks that a change builds, meets coding standards, passes security checks and doesn't regress fidelity. That pattern carries to any team letting agents write code: the agent's output is trusted only as far as tests verified against something real.

## What I'd watch out for

| Issue | Why it matters | Control |
|-------|----------------|---------|
| **Fidelity gaps**: roughly S3 83%, DynamoDB 71%, IAM 71%, Lambda 50% single-service pass rates, from one tester on version 1.0.338, not from AWS | Local success does not guarantee real-world behaviour; gaps can surface in production. | Run the same suite against a small, dedicated AWS account before promotion. |
| **IAM limitations**: the sources disagree (Mulga, citing AWS, says it doesn't evaluate IAM policies; the tester found only identity policies on roles enforced), and AWS says not to use it for security testing | Permission logic may pass locally and fail, or be wrong, in real AWS. | Treat the emulator as a *development* tool; always validate IAM rules on a real account. |
| **No human code review**: Amazon says its team hasn't written or reviewed the code | Supply-chain risk: it's unreviewed code running inside your build pipeline. | Pin a version, run it in a locked-down container with no outbound network, and record which version every test run used. |
| **Telemetry on by default** | What it collects isn't stated in what I read. | Turn it off in CI (the tester used `EMULATOR_TELEMETRY=off`). |
| **In-memory state and size limits**: state lost on shutdown, bucket and upload caps | Tests may not reflect real persistence; large payloads fail locally but succeed in AWS. | Use the real test account for larger objects or long-running state. |
| **Runtime differences**: Python Lambdas run on RustPython, not CPython, in the tester's version | Packages with C extensions will likely fail; `sqlite3` was missing. | Keep native-dependency Lambdas on the real-account path. |

Two controls from [the governance standard](../../blog/posts/governance.md) apply directly: SEC-06 (supply chain: pin and scan what you run, record provenance) and SEC-03 (least privilege: the deploy guard above blocks deploys to anything but the emulator's account).

## What I'd try next

How fidelity is measured overall, and exactly which services are covered, isn't in what I read; Matthew Goldberg, who wrote Amazon's account, plans follow-up posts. If I were to experiment further, I would:

1. **Extend the test suite**: add larger S3 and DynamoDB workloads to see where the gaps widen.
2. **Benchmark against real AWS**: run identical Lambda functions in both environments side by side, and check how the emulator's RustPython runtime differs from CPython for the libraries I use.
3. **Run the published fidelity tests myself**: AWS publishes them separately as [an evaluation suite](https://github.com/aws/aws-emulator-evaluation-suite), which is the honest way to see coverage for the services I care about.
4. **Copy the build method, not just the tool**: for my own agent-written code, a spec, a reference, tests checked against the reference, and a gate that rejects regressions.

If those experiments show it reliably mimics real AWS across the services I use, I'd make it the primary sandbox, not a supplement. Until then, I see it best used as a *supplementary* tool: fast local iteration with a safety net of real-world validation.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
