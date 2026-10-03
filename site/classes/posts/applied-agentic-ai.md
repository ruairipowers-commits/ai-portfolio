---
date: 2026-09-01
slug: applied-agentic-ai
---

# MIT Applied Agentic AI: bringing agents into an organisation without losing control

My [first MIT course](applied-ai-data-science.md) taught me how the models work. This one, in July and August 2026,
was about the harder problem: putting agents to work inside an organisation, safely, and scaling them once they've
earned it. The faculty said at the outset that it was more about people and organisational change than about the
technology stack. They were right.

<!-- more -->

**Course:** [Applied Agentic AI for Organizational Transformation](https://professional.mit.edu/course-catalog/applied-agentic-ai-organizational-transformation),
MIT Professional Education ·
**When:** 8 July – early September 2026, online, eight weekly modules ·
**Credits:** 7 CEUs ·
**Credential:** [certificate of completion](https://www.credential.net/82c2bca4-31f2-4e5f-9e6e-709d11247dcd#acc.6rGHBmwl) ·
**Faculty:** Prof. John R. Williams and Dr. Abel Sanchez, MIT Geospatial Data Center

## How it ran

- **Format.** Eight modules, one a week: videos and case studies, weekly office hours with a learning facilitator,
  and two live faculty webinars.
- **Time.** About 70 hours in all.
- **Assignments.** Each module ended in one. They were either quantitative, such as costing an API, or about
  applying the ideas to your own organisation.
- **Certificate.** It needed six of the first seven assignments plus the capstone, which was 30% of the grade.
- **No lab.** You build with your own API accounts. About $5 of credit covers the course.

| Module | Topic |
|---|---|
| 1 | Foundations of generative and agentic AI: tokens, models, cost |
| 2 | The rise of agentic AI and the platforms for building agents |
| 3 | Connecting agents to digital ecosystems: APIs, MCP, integration platforms |
| 4 | Agentic risks, disinformation and systemic impact |
| 5 | AI agents by business function |
| 6 | The last mile: from pilot to practice (Crawl / Walk / Run), testing agents |
| 7 | Governance, compliance and regulation |
| 8 | Ethics, and the capstone |

## Frameworks for introducing AI and scaling it responsibly

The course's frameworks, and the ones I used in my assignments, apply across domains and business processes:

| Framework | What it's for | Where I applied it |
|---|---|---|
| **Crawl / Walk / Run** (Dr. Sanchez) | Adopt in stages, from a small pilot to production, widening scope as results come in | The staged rollouts below |
| **Sandbox → shadow → phased rollout** | Prove a model is no worse than the current process before it influences a decision | Telehealth and hospital plans; my loan capstone |
| **Regulatory scoping** | Decide which laws apply from the data and the geography, then design to the strictest | HIPAA, GDPR, CCPA, FDA SaMD, ONC HTI-1, EU AI Act |
| **NIST AI RMF** | A shared vocabulary and baseline for AI risk | Adopted as the internal baseline in the hospital plan |
| **NIST Cybersecurity Framework** | Assess security posture: Identify, Protect, Detect, Respond, Recover | Assessing my own firm's AI use |
| **Human-in-the-loop by design** | AI recommends; a named person decides and owns the outcome | Every plan; the model never acts on a patient |
| **Explain every output** | Show the top factors with every score, never an unexplained number | Clinical decision support; credit decisions |
| **Asymmetric error costs** | Set thresholds by what each mistake costs | A missed escalation costs far more than a false alarm |
| **Risk register** | Each risk typed (compliance or operational) with an owner and mitigation | Both governance plans |
| **Cross-functional governance committee** | Standing oversight with the authority to pause or roll back | Clinicians, compliance, legal, IT security, a patient advocate |
| **Cost guardrails** | Caps on tokens, spend and per-user use, decided before launch | Module 1 cost analysis |

The thread through all of them: **autonomy is earned with evidence, and every step must be reversible.**

## Governance

Governance ran through every module, and module 7 was built on it. I wrote two governance plans, both for healthcare
AI, one of the most heavily regulated places to deploy it.

**Telehealth escalation.** A model watches a virtual visit and flags when a patient should go to the ER instead.

- **Recommendations only.** The doctor decides and talks to the patient.
- **Thresholds set by consequence.** A missed escalation is far costlier than a false alarm, so the thresholds are
  conservative.
- **Every override logged** and reviewed by quality control.
- **A full audit trail for each encounter:** inputs, recommendation, action taken and outcome.
- **Subgroup testing** by age, sex and language.
- **HIPAA scoping**, aiming for a superset of the rules that might apply.

**Hospital clinical decision support.** Sepsis risk scoring and radiology triage for a five-hospital system with
an EU telehealth pilot.

- **Regulation across jurisdictions:** HIPAA, FDA software-as-a-medical-device rules with a change-control plan,
  ONC transparency rules, GDPR and the EU AI Act's high-risk tier.
- **Explainability.** Every score shows its top contributing factors.
- **Fairness testing** by race, sex, age and insurance, with a retraining trigger when the gaps exceed a threshold.
- **Drift monitoring** against outcomes.
- **Adversarial tests** for prompt injection and patient-data leakage.
- **A governance committee** that includes a patient advocate and has rollback authority.
- **A model card** for every version.

## Implementation plans

Every plan I wrote follows the same shape:

1. **Sandbox** on de-identified or historical data.
2. **Shadow mode:** the model runs alongside people, 60–90 days in the hospital plan, logging what it would have
   done without influencing anything.
3. **Phased rollout** one unit or one group of doctors at a time, against a control group, measured on the outcome
   that matters (time to treatment, missed escalations) and on the burden it adds (false alerts).
4. **Expand**, with monitoring, scheduled revalidation and rollback thresholds agreed in advance.

For my own firm, the plan put three prerequisites ahead of any more agent autonomy:

- training;
- central monitoring, with agents on their own credentials so they can be watched and switched off;
- a written incident-response playbook.

## The assignments: a series of thought exercises

Each assignment was a small exercise that built toward the capstone:

1. **What does it cost?** I costed a website chatbot by varying input tokens, output tokens and call volume. Spend went
   from about $270 to $27,000 across my scenarios, and output tokens cost several times more than input.
   Conclusion: every dimension needs a failsafe (spend caps, token limits, per-user limits) before launch, not
   after the first bill.
2. **What can you build quickly?** A vibe-coding exercise with the new agent platforms.
3. **How does an agent reach real systems?** TravelGuru, an agent connected to Discord, for the APIs and
   integration module.
4. **How secure is the way we use AI today?** I surveyed my own small firm against the NIST Cybersecurity
   Framework and wrote a report to leadership.
   - **Strong:** we know what our AI workflows can reach. We'd deliberately chosen on-demand workflows over
     autonomous agents.
   - **Weak:** no formal training, no central monitoring, and no recovery plan beyond version control.
   - **Recommended:** training, central logging with a kill switch, and an incident playbook.
5. **Which business functions benefit, and how?** Agents mapped to business functions.
6. **How do you get from pilot to production?** Crawl / Walk / Run applied to a rollout.
7. **How do you govern it under regulation?** The telehealth and hospital governance plans above.
8. **Capstone: put it all together.** AI integration plans for the sales pipeline and business development.

<!-- TODO(Ruairi): fill in one line each for modules 2, 3, 5, 6 and the capstone from the PDFs — only file names were
     available when this was written. -->

## How it's applied in this portfolio

The course gave names to the controls I'd already built into this portfolio, and showed me where they were thin:

- **A kill switch for every workflow.** The [governance console](../../blog/posts/governance-console.md) can switch
  any workflow off. Serious incidents switch it off automatically, and someone has to record the root cause and the
  fix before it comes back on. That's the respond-and-recover step my NIST survey found missing at my own firm.
- **Central monitoring.** Every workflow, including the [site assistant](../../personal/posts/site-assistant.md),
  reports to that one console. That closes the detect gap the survey found.
- **The standard's controls** carry the same ideas:
  - human approval for consequential actions (HITL-02), and reviewer overrides fed back into evals (HITL-03),
    which is the override-logging loop from the governance plans;
  - hard budgets (COST-01) and cost attribution (COST-02), the module 1 lesson;
  - eval-gated changes (MODEL-02): no model or prompt is promoted until it's no worse than the current one. That's
    the shadow-mode idea, in CI.

The [governance standard](../../blog/posts/governance.md) lists every control.

## What I took from it

- **Start with workflows, not autonomous agents.** On-demand AI workflows with a human trigger are easy to govern.
  Earn autonomy one use case at a time.
- **Governance is how you scale.** A shadow period, a rollback threshold and a named owner are what let you say yes
  to the next use case.
- **Regulated industries already know how to do this.** Healthcare's change-control plans and model cards map
  closely to what financial firms need for model risk.

*Course materials belong to MIT Professional Education. This is my summary of them, and the assignments are
mine.*
