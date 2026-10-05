---
date: 2026-10-05
slug: questions-for-your-ai-team
short: "Questions to ask your AI team"
categories: [AI governance, Evaluation, Human in the loop, Machine learning, Security]
tags: [ai governance, model risk, model monitoring, drift, retraining, genai, executive guide, sr 11-7, gdpr, pii, eu ai act, privacy]
---

# Is our AI behaving? A leader's guide to questioning your tech team

You don't need to read code to know whether your firm's AI is under control. You need to ask the right questions,
in the right order, and insist that every answer comes with **evidence**: a document, a report or a log, with a date
and an owner's name on it.

This is the walk-through I'd give a CEO, COO or business head who's accountable for AI but not technical. It uses
three examples: a credit model at a bank, an assistant that answers customers, and an AI that reads customer
feedback to guide product decisions.

<!-- more -->

## The one rule: "show me", not "tell me"

"Yes, we monitor it" is a statement. A monitoring report from last month, with someone's name on it and a decision
recorded, is evidence. Keep asking until you get the evidence.

Three tests turn any answer into something you can check:

1. **Is it written down?** A policy, a threshold or a decision that only lives in someone's head isn't a control.
2. **Did it actually run?** A monitoring process that exists on paper but hasn't produced a report since spring
   isn't working. Ask for the most recent output.

3. **Who acted on it?** A report nobody reads is noise. Ask what changed the last time it flagged something.

## Step 1: Start with the inventory

Before asking whether any one system is behaving, ask **what AI you actually run**. This is where most firms find
surprises.

**Ask for:** an AI inventory. It's one list, kept current, with a row for each AI system.

| Column | Why it matters |
|---|---|
| What it does and what it decides | A model that recommends is lower risk than one that decides on its own |
| Who is affected | Customers, staff, markets, regulators |
| Business owner and technical owner | Two named people, not a team |
| Risk tier (low / medium / high) | Sets how much checking it gets |
| Built, bought or a tool staff use | Vendor features and staff using public chatbots count too |
| Last review date | Anything older than a year is a question |

**Red flag:** the list is assembled for your meeting rather than maintained. Ask when it was last updated, and by
whom.

## Step 2: For each system, ask for its "use-case card"

One page per system, written before it went live:

- what it's for, and what it must **not** be used for;
- the data it uses;
- its known weaknesses;
- who approves changes.

If the team can't produce it, nobody has agreed what "behaving properly" means for that system, so nobody can tell
you whether it does.

## Step 3: A classic model, using a credit model at a bank as the example

For my MIT capstone I built a model that predicts which home-equity loans will default
([the write-up](../../classes/posts/loan-default-capstone.md)). It's a decision tree that catches **81%** of
defaults. I chose it over a gradient-boosting model with better precision because it can explain each decision
in plain rules.

**Imagine a regional bank put it into production** to flag risky applications for an underwriter to review. This
is a thought experiment, not a real deployment. Here's what its leadership should be asking a year later, and
what good answers look like.

### "Is it still behaving properly?"

**Ask for:** the monthly monitoring report.

| What it should show | In plain terms |
|---|---|
| **Applicant drift** | Are today's applicants like the ones the model learned from? Shifts in income, loan size or loan purpose mean it's being asked about people it hasn't seen |
| **Flag rate** | What share of applications it flags, against what was expected at launch |
| **Defaults caught (recall), back-tested** | Of the loans that went bad, how many had it flagged? |
| **Overrides** | How often underwriters disagree with it, and which way |

One trap for non-specialists: **defaults take months or years to show up.** A model can look fine today on loans
that simply haven't had time to fail. Ask how the team measures performance while waiting for outcomes. A good
answer uses early-warning signals, such as missed first payments, and says when the full answer will be known.

### "Is it still tuned the way we decided?"

Every credit model has a cut-off: the score above which a loan is flagged. Choosing it is a **business decision**
about two costs: missed defaults, and good customers slowed down or turned away.

**Ask:**

- What's the current cut-off, who approved it, and when?
- What was the trade-off at the time, and has either cost changed since? For example, rates went up, losses are
  higher, or the underwriting team shrank.

**Red flag:** the cut-off is "whatever the data scientist picked", with no approval on record.

### "Are its parameters and inputs up to date?"

**Ask:** what version of the model is running, when its training data ends, and whether that matches the version
that was validated and approved.

Then ask the question that catches the quiet failures: **"Has anything changed upstream of the model?"**

In my capstone, the single strongest warning sign was a blank field. Applicants who left debt-to-income empty
defaulted **62%** of the time, against under 9% for those who filled it in. Now imagine the bank redesigns its
application form and makes that field mandatory. Nothing in the model changes, and nothing crashes, but its best
signal quietly disappears. Only a check on the *inputs* would notice.

Ask whether such checks exist, and who gets alerted when they fire.

### "Does it need retraining?"

Retraining shouldn't be a judgment call made in a hurry. **Ask for the retraining triggers, agreed in advance:**

- performance drops below an agreed level;
- applicant drift passes an agreed threshold;
- a policy, product or regulatory change;
- a scheduled review, at least yearly.

Then **ask how a new version gets in.** The safe answer is the one I designed for the capstone:

- the new model runs **in parallel** with the old one for a period;
- the two are compared on the same applications;
- a named person approves the switch;
- the old model stays ready to switch back.

**Red flag:** "We retrain it automatically every month." That can be fine, but only if each new version passes the
same tests and approval as the first one did.

### "Can we explain and defend its decisions?"

In lending this isn't optional. A declined applicant must be told the principal reasons, and the bank must show the
model doesn't treat protected groups unfairly.

**Ask for:**

- a sample of real explanations;
- the most recent fairness testing.

That's why I chose a readable decision tree over a model that needed extra tools to explain itself.

!!! note "The same questions for a trading model"
    Swap the nouns and the questions hold.

    - **Behaving properly?** Compare live results with what the backtest promised: returns, trading costs, how
      often it trades. A widening gap is the early warning.
    - **Still tuned?** Ask when its settings, such as signal look-backs and position limits, were last reviewed, and
      against which market conditions. A model tuned in a calm market may misbehave in a volatile one.
    - **Retrain?** Ask for triggers agreed in advance, a parallel or paper-trading period, and who signs off.
    - **Kill switch?** Ask who can switch it off, how fast, and when that was last tested.

## Step 4: A generative AI that answers customers

Now an AI that writes replies to customer questions, by chat or email. The risks are different: it can say
something wrong, promise something you can't deliver, leak information, or be tricked by a customer.

**Ask:**

| Question | Evidence to ask for | Red flag |
|---|---|---|
| What is it allowed to say, and not say? | A written content policy: no advice, no promises on fees or outcomes, escalate complaints | "The model is smart enough to know" |
| Where do its answers come from? | Answers grounded in approved documents, with sources it can cite | It answers from general knowledge |
| How was it tested before launch? | A test set of real and tricky questions, including attempts to manipulate it, with pass rates | Testing was "we tried it for a week" |
| Which conversations does a human see? | Rules for handing over to a person: complaints, vulnerable customers, anything financial | No hand-over path |
| How do we know it's still good? | A weekly sample of real conversations reviewed against the policy, with scores tracked over time | Reviews stopped after launch |
| What happens to customer data? | Which vendor sees it, where it's stored, whether the vendor may train on it | Nobody has read the vendor terms |
| What if it goes wrong? | An off switch, and an incident process with an owner | Switching it off needs a code release |

## Step 5: A generative AI that reads feedback and guides decisions

An AI that reads thousands of reviews, survey answers and support tickets, and summarises what customers want. It
feels low-risk because it doesn't talk to customers. But it **shapes decisions**, and a subtly wrong summary can
steer a roadmap.

**Ask:**

- **Is the summary faithful?** Ask the team to show you five themes, and the raw comments behind each. Do the
  quotes say what the summary claims?

- **Who's missing?** Which sources fed it? Did it read every channel, or only the easy ones? Loud customers
  shouldn't outweigh quiet ones.

- **Who did the counting?** "40% of complaints are about fees" should come from a count in code, not from a model's
  estimate. Language models describe well and count badly.

- **Who decided?** The AI should inform a product decision, not make it. Ask for the decision record: what was
  decided, by whom, and what evidence they looked at.

## Step 6: Personal data, privacy and regulation

AI systems are hungry for data, and much of it is about people: applicants, customers, employees. That's where the
legal exposure sits, and it's where a leader most needs evidence rather than reassurance. I'm not a lawyer, and the
rules differ by country and change often, so treat this as the questions to ask, then check the answers with your
legal and compliance team.

**Start with one question per system: "What personal data goes in, and where does it go?"** That covers the data
the model was trained on, the data it sees each time it runs, what's logged, and anything sent to a vendor.

| Question | Evidence to ask for | Red flag |
|---|---|---|
| What personal data does each AI system use, and why does it need it? | A data map per system: fields used, purpose, where it's stored, who can see it | "It uses the customer record" (all of it) |
| What's our legal basis for using it this way? Under GDPR, every use of personal data needs one | The documented basis per purpose, signed off by privacy or legal | "Customers agreed to our terms" |
| Did we assess the risk before launch? GDPR requires a data protection impact assessment (DPIA) for high-risk processing, which automated credit decisions are | The DPIA, its date and who approved it | No DPIA, or one written after go-live |
| Does any decision about a person rest on the model alone? GDPR gives people the right not to be subject to solely automated decisions with legal or similarly significant effects, and to a human review | Where a human reviews, and how a customer asks for one | "The model decides; staff just click approve" |
| Can we honour access and deletion requests? | The process, and how a request reaches training data, logs and the vendor | "We can't remove someone from the model" with no plan (retraining without them is a plan) |
| Where does the data travel? | Vendors and regions; the data processing agreement; the transfer safeguards if data leaves the EU or UK | Nobody knows which region the AI vendor uses |
| Does the vendor keep or train on our data? | The contract clause, and the setting switched on | "We use the enterprise version", with nothing in writing |
| How long do we keep prompts, transcripts and logs? | A retention period per log, applied automatically | Logs kept forever "in case" |

**And the rules that apply to the use, not just the data.** Which ones depend on your industry and your markets.
Some examples:

- **Lending:** in the US, fair lending law requires the principal reasons for a decline, and fairness testing across
  protected groups. Credit reporting rules apply to the data used.
- **The EU AI Act** treats AI used to assess people's creditworthiness as **high-risk**, with obligations on risk
  management, data quality, documentation, human oversight and logging. It also requires telling people when
  they're talking to an AI. Its obligations are phasing in, so ask your counsel which already apply to you.
- **Financial services generally:** books-and-records rules may cover AI outputs and customer conversations, and
  regulators expect model risk management for models that drive decisions.
- **US state privacy laws** (California's among them) add notice, opt-out and access rights, and some states now
  regulate automated decision-making specifically.

**Applied to the three examples:**

- **The credit model** carries the most: personal financial data, decisions with legal effect, explanation rights,
  fairness, and in the EU, high-risk status. Ask for the DPIA, the human-review step and the adverse-action
  explanations.
- **The customer assistant** collects whatever customers type, including account numbers and health or family
  details they volunteer. Ask what's masked before the vendor sees it, how long transcripts are kept, and whether
  customers are told it's an AI.
- **The feedback analysis** looks harmless, but reviews and tickets are full of names, emails and complaints about
  identifiable staff. Ask whether personal details are stripped before the AI reads them, and whether the original
  purpose of collecting that feedback covers this use.

## Step 7: Is the team managing AI use properly?

Finally, step back from individual systems. Ask for these policies, and for **evidence each one has been used
recently**:

| Policy | What it covers | Evidence it's real |
|---|---|---|
| Acceptable use | Which AI tools staff may use, for what, with which data | Approved tools list; the last exception granted |
| Data classification | What data may go into which AI tools | A recent check that it's followed |
| Model risk management | How models are built, validated, approved and reviewed (in US banking, regulators' SR 11-7 guidance sets the bar) | The last independent validation report |
| Change management | How a model or prompt change gets tested and approved | The approval record for the last change |
| Monitoring and retraining | What's watched, how often, and the triggers | Last month's report and what was done about it |
| Vendor management | Due diligence on AI vendors and their data terms | The review of the main AI vendor |
| Incident response | What happens when AI misbehaves | The last AI incident and its write-up |
| Privacy and data protection | Personal data in AI: legal basis, impact assessments, rights requests, vendors and transfers | The DPIA for the riskiest system, and the last access or deletion request handled |
| Records retention | How long logs and decisions are kept | Being able to retrieve a decision from six months ago |

The question that tests all of them at once: **"Walk me through the last time something went wrong."** A team in
control can tell you what happened, how they noticed, what they did, and what they changed afterwards. A team that
says "nothing has ever gone wrong" either isn't looking or isn't telling you.

## Step 8: Put it on a rhythm

| How often | What you see | Time it takes you |
|---|---|---|
| Monthly | A one-page scorecard per high-risk system: performance, drift, overrides, incidents, cost | 15 minutes |
| Quarterly | The inventory, changes made, upcoming retrains, open issues | An hour |
| Yearly | Independent validation of high-risk models, and a policy refresh | A half-day |

## Red flags, in one place

- No inventory, or one built for the meeting
- "It's monitored" without a recent report
- Thresholds and cut-offs with no approver
- Automatic retraining with no approval step
- Generative AI answering from general knowledge rather than your documents
- Nobody has read the AI vendor's data terms
- No off switch, or one that needs an engineer and a deployment
- No AI incident ever recorded
- No one can say what personal data an AI system uses, or where it goes
- A decision about a person made by the model alone, with no human review on request
- No impact assessment (DPIA) for a high-risk use of personal data

## Where this comes from

I hold my own projects to the same questions, with [30 controls](governance.md) I apply to every AI workflow on this
site. [How I govern the AI on this site, step by step](how-i-govern-this-site.md) shows each step with links to the
code, tests and monitoring behind it, the same evidence I'd want my team to show me.
