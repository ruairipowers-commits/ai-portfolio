# launch-tracker

**Every launch to space from free public data: missions and payloads, rockets and booster reuse, crews and
splashdowns, live countdowns, measured delays, success and failure, published costs, launches by industry with a
back-tested projection, and what is already in orbit — with a model writing short summaries that code checks
against the data.**

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers · a personal project ·
> Write-up: [{{SITE_URL}}/personal/launch-tracker/]({{SITE_URL}}/personal/launch-tracker/) ·
> Governance: [this project's mapping](docs/governance.md)

## What it does

- **Upcoming** — next launches with a live T-minus clock, status (Go / TBC / TBD / Hold), and how far each has
  slipped since it was first scheduled. Slips are *measured*: every refresh records each launch's target time.
- **Launch page** — provider, country, rocket and family, pad and site, mission (purpose, orbit or destination),
  payload mass, programme; each stage with its serial, flight number, days since its last flight and landing
  (drone ship or landing zone); spacecraft with destination and return (splashdowns flagged); crew with roles;
  images with credit and licence; the published cost if there is one; and a cited plain-English summary.
- **Explorer** — filter by year, provider, country, rocket, orbit, industry, outcome, crewed and reused booster;
  summarise by any of them; download the rows as CSV.
- **Dashboard** — launches per year by outcome and by country/provider/family, success rate by rocket with sample
  sizes, failures, retired rockets, booster landings and reflights, delays, published costs and cost per kg, a map
  of launch sites.
- **Economy** — launches by industry per year, our own trend projection (back-tested, labelled ours), third-party
  projections (labelled theirs) and the sectors that grow alongside space, each with its source.
- **Orbit** — what's in orbit by type, regime and owner; objects per 50 km altitude shell in low Earth orbit with
  active vs dead vs rocket bodies vs debris; the largest constellations; re-entries per year; and ESA's published
  findings on crowding beside our own counts.

### Sources

| Source | What it gives | Licence / terms | Refresh |
|---|---|---|---|
| [Launch Library 2](https://thespacedevs.com/llapi) (The Space Devs) | upcoming and past launches, stages and landings, spacecraft, crews, pads, missions, images | free for everyone; images carry their own licence | hourly, within the free tier's **15 requests an hour** (enforced) |
| [GCAT](https://planet4589.org/space/gcat/) (Jonathan McDowell) | every launch since 1957, outcomes, payload mass | CC-BY-4.0 | daily |
| [CelesTrak SATCAT](https://celestrak.org/satcat/) | every catalogued object in orbit | CelesTrak usage policy | daily |
| `data/reference/costs.yaml` | published prices and reported costs, each cited, **used only after a person approves it** | per source | by hand |
| `data/reference/market.yaml`, `sectors.yaml`, `orbit_findings.yaml` | WEF/McKinsey space-economy projection; ESA Space Environment Report 2025 | per source | by hand |

## Quickstart

```bash
pip install -e ".[ui,dev]"
launches all          # offline: the fictional sample → database → headline → three summaries → digest → changes
launches eval         # golden set + gate (mock model, $0)
launches ui           # the app
pytest -q

LAUNCHES_MODE=live launches fetch      # real data (needs network): LL2 within its budget, GCAT, SATCAT
pip install -e ".[flows]" && launches flows   # scheduled refreshes with Prefect
launches approve sls-orion-oig-2021 --reviewer "Your Name"   # approve a cited cost (the human step)
```

**The offline sample is fictional.** Every provider, rocket, pad, country, crew member and satellite in it is
invented, so nobody mistakes it for real history — but it is written in the exact formats of the three real sources,
and the same parsers read both. The app says which one it is showing. The history backfill from Launch Library 2
takes a few hours at 15 requests an hour; it resumes where it stopped.

## Results (offline run on the fictional sample, mock model)

| What | Result |
|---|---|
| `launches all` end to end | 1.5 s: 2,691 launches (1,329 with full detail), 13,869 catalogued objects, 1 source disagreement found |
| Reconciliation | every detailed past launch matched to the history (by designator, or by time and rocket family for one without) |
| Delays | 13 launches tracked, 10 slipped, median slip 4 days, 1.54 target changes per launch |
| Reuse | 691 landings in 722 attempts; most-flown booster 17 flights; median 33.6 days between flights; 28 splashdowns |
| Trend projection | 17.0% a year (fitted 2016–2025); back-test on 2023–2025: 9.5% average error |
| Eval gate (9 cases) | accuracy 1.0, citation accuracy 1.0, injection flag recall 1.0; 1 draft rejected by the guard, as designed |
| Model cost | $0.0035 for the eval, $0.00085 per summary on average (simulated mock pricing) |
| Tests | 30 passing (controls, end to end, governance client, headless app) |

These numbers describe the fictional sample and the mock model. Real figures come from `launches fetch` on a
machine with network access.

## Configuration

Everything is in `config/settings.yaml`: sources and their cadences and budgets, which image licences may be shown,
whether costs need approval, model aliases and prompts, budgets, guard behaviour, the retirement heuristic (no
launch for 18 months), forecast window and back-test, and the altitude-shell width. Models are in
`config/models.yaml`; the industry mapping in `data/reference/industries.yaml`.

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Following launches and the space economy out of interest; a worked example of reconciling public sources and keeping a model honest |
| **Users** | Me; anyone curious; anyone sizing the launch market as a starting point |
| **Not for** | Investment decisions, flight safety, or anything that needs an authoritative launch record (use the sources themselves) |
| **Owner** | Ruairi Powers |
| **Model's job** | Write short summaries from facts it is given. It decides no number, cost or outcome |
| **Known failure modes** | Sources lag or disagree (shown, not hidden); mission-type → industry mapping is coarse and older launches have none ("Unclassified"); the retirement rule is a heuristic; few launch costs are public; the trend fit is a simple curve, not a forecast |
| **Human step** | A named person approves each cost before it is used |

## Architecture

See [docs/architecture.md](docs/architecture.md) (flow, the summary sequence, decisions) and
[docs/aws-native.md](docs/aws-native.md).

## License

Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you reuse it (see [NOTICE](NOTICE)).
