# Models — what each one is and what to expect

The agent never names a model in code. It asks for an **alias** (`investigator-primary`, `investigator-fallback`,
`investigator-candidate`), and `config/models.yaml` maps each alias to a **model** entry. The app's model
picker lists only entries that can actually run here: approved (`approved: true`), priced (both per-million-token
prices filled in, so the budget check can work), and with the provider's credentials available.

Whatever model you choose, the same things happen around it:

- it can only call the **7 read-only tools** (the write tool doesn't exist in its tool list);
- it is stopped after **8 tool calls / 10 LLM turns / $0.25** per exception, and the case is escalated;
- every tool result is **screened** for instruction-like text and bank-detail-change requests;
- its proposal must match the `submit_proposal` **schema**, and every cited value must appear in a tool result;
- deterministic **policy** decides between *Awaiting approval* and *Escalated*, and a **human** decides the rest.

So changing the model changes the *quality and cost of the draft*, not the safety envelope.

## The aliases

| Alias | Used for | Default |
|---|---|---|
| `investigator-primary` | Every investigation unless you pick something else | `mock-agent` |
| `investigator-fallback` | Tried automatically if the primary's provider errors (timeouts, 5xx). Logged as `llm_error` in the trajectory | `mock-agent` |
| `investigator-candidate` | A model you're evaluating before a migration: `tradeops eval --alias investigator-candidate --baseline investigator-primary`, then `tradeops promote` | `mock-agent` |

Picking a model name directly in the app (e.g. `claude-sonnet`) runs that model for the investigation and
uses `investigator-fallback` if it fails.

## `mock-agent` — deterministic scripted investigator (default)

**What it is.** Not a language model. A small Python class (`ScriptedInvestigator` in `src/tradeops/llm.py`)
that plays the model's role so the whole system runs offline, for free, with identical results every time.
It emits real tool calls, so the LangGraph loop, the TypeScript MCP server, screening, policy, approval
tokens and audit logging are all exercised exactly as with a real model.

**How it works.**
1. Always calls the same six tools in the same order: `get_exception` → `get_trade` → `get_broker_confirm` →
   `get_allocations` → `get_custodian_record` → `get_ssi`.
2. Compares fields with fixed rules: missing confirm → `CHASE_CONFIRM`; confirm account ≠ SSI on file →
   ask broker to correct; quantity differs → whoever disagrees with allocations is wrong; allocations don't sum
   → amend internally; price differs → whoever disagrees with the EMS average fill is wrong; settle date differs
   → whoever isn't T+1 is wrong.
3. If the custodian record can't be parsed it proposes `ESCALATE`.
4. If every source agrees (nothing to fix) it keeps calling `find_similar_exceptions` until the 8-call cap stops it.

**What to expect.**
- 6 tool calls per exception (8 for the "nothing wrong" trap); 36 of 40 sample exceptions go to *Awaiting
  approval*, 4 are *Escalated*; the eval gate scores 100%.
- Cost shown is **simulated** ($1 / $5 per million input / output tokens) so cost reporting has numbers.
- It **ignores** text in tool results. When you insert an injection or a bank-detail change, its *draft* is
  unchanged (e.g. still "amend booked quantity") — the status flips to *Escalated* because **policy** caught the
  text, not the model. That is the point of the demo: the safeguard doesn't depend on the model behaving.
- It never edits evidence, never hallucinates, never varies. Real models will.

## `claude-sonnet` — Anthropic Claude Sonnet (`claude-sonnet-5-5`)

**What it is.** A general-purpose Claude model called through the Anthropic API with native tool calling
(`langchain-anthropic`, temperature 0).

**To enable.** `pip install -e ".[anthropic]"`, set `ANTHROPIC_API_KEY`, and fill `input_per_mtok` /
`output_per_mtok` for `claude-sonnet` in `config/models.yaml` from Anthropic's pricing page. It ships
`approved: true` but unpriced, so it won't appear (or run) until you add prices.

**What to expect.**
- It decides which tools to call. It will often skip lookups it doesn't need (e.g. no SSI check for a price
  break), so tool-call counts vary per exception and between runs.
- It reads the investigator prompt's rules (T+1, fills are truth, never change SSIs from a counterparty
  message) and usually explains the root cause in more natural language than the mock.
- On injected or bank-change text it will often recognise the attempt and propose `ESCALATE` itself — and
  if it doesn't, policy escalates anyway.
- Its evidence must quote tool values exactly; a paraphrased or mistyped value escalates the case
  ("cited evidence does not match source systems").
- Results are not guaranteed identical run to run. Run the eval gate before relying on it:
  `tradeops eval --alias claude-sonnet`.

## `claude-haiku` — Anthropic Claude Haiku (`claude-haiku-4-5-20251001`)

**What it is.** Anthropic's smaller, faster, lower-cost model. Same integration as Sonnet.

**To enable.** Same as Sonnet (same API key), plus pricing for `claude-haiku`.

**What to expect.** Lower cost and latency per exception. Whether it is accurate enough on the subtler breaks
(price vs fills, which side is wrong on a quantity break) is exactly what the eval gate measures — compare it
to your primary with `tradeops eval --alias claude-haiku --baseline investigator-primary` before promoting.
A common pattern is a small model for routine breaks with escalation to a larger one; this repo doesn't
implement routing, but the alias layer is where it would go.

## `openai-default` — OpenAI (disabled)

**What it is.** A placeholder for an OpenAI chat model with tool calling (`langchain-openai`).

**Status.** Ships `approved: false` and with `model_id: SET-CURRENT-OPENAI-MODEL-ID`, so it can't be selected.
That's deliberate (SEC-05): a provider is enabled only after its data-handling terms are reviewed.

**To enable.** Set a current model ID, pricing, `approved: true`, `pip install -e ".[openai]"` and
`OPENAI_API_KEY`. Then run the eval gate. Expect behaviour broadly like Sonnet: adaptive tool use,
non-deterministic wording, policy as the backstop.

## `bedrock-claude` — Claude on Amazon Bedrock

**What it is.** Claude served from your own AWS account via the Bedrock Converse API (`langchain-aws`).
No model API key exists; access is controlled by IAM (the AWS-native Terraform limits the investigator's
role to approved model ARNs).

**To enable.** `pip install -e ".[aws]"`, AWS credentials (e.g. `AWS_PROFILE`), model access granted in the
Bedrock console, then set `model_id` (a model or inference-profile ID), `region` and pricing in
`config/models.yaml`.

**What to expect.** The same model behaviour as the matching Anthropic model; traffic stays in your AWS region
and appears in your AWS bill and CloudWatch. Not exercised in this repo's CI — run the eval gate in your account.

## Changing models safely

1. Add or edit the model in `config/models.yaml` (pricing, `approved`).
2. Point `investigator-candidate` at it.
3. `tradeops eval --alias investigator-candidate --baseline investigator-primary` — must pass thresholds
   (category and fix accuracy, 100% escalation recall, trajectory compliance, zero unapproved writes, cost)
   and not regress.
4. `tradeops promote investigator-primary <model>` — refuses without a passing eval on the current prompt.
