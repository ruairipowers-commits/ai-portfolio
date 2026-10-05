# Architecture — editorial-agents

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
  subgraph sources["Open sources (official APIs + feeds)"]
    HF["Hugging Face<br/>papers · trending"] --- AX["arXiv"] --- HN["Hacker News"] --- RD["Reddit API"] --- RSS["AI + news feeds"]
  end
  subgraph host["Demo host (EVO-X1)"]
    SC["Scout<br/>screen SEC-02 · classify MODEL-01<br/>score · MMR re-rank"]
    Q[("Topic queue<br/>always N")]
    SA["Site assistant<br/>subscribers DATA-03"]
  end
  subgraph claude["Weekly scheduled Claude task"]
    W["Writer"] --> E1["Editor ×2<br/>checklist + rubric EVAL-02"]
  end
  sources --> SC --> Q
  Q -- "ranked email:<br/>Pick / Dismiss" --> O(("Ruairi"))
  O -- "signed link HITL-02" --> Q
  Q -- "queue.md" --> W
  E1 -- "draft PR" --> GH["GitHub PR<br/>label draft-post"]
  GH -- "email: intro,<br/>scorecard, links" --> O
  O -- "merge = publish HITL-02" --> SITE["Blog"]
  SITE -- "new post" --> SA -- "intro + link" --> SUB(("Subscribers"))
  GH -. "drafted / published" .-> Q
```
<!-- --8<-- [end:flow] -->

## Weekly sequence

```mermaid
sequenceDiagram
  participant S as Scout (daily)
  participant R as Ruairi
  participant W as Writer (Claude, weekly)
  participant E as Editor (separate agent)
  participant G as GitHub
  participant A as Site assistant
  S->>R: Monday: 10 ranked topics, Pick / Dismiss links
  R->>S: picks one (confirmation page, POST)
  W->>S: reads queue.md, takes the top picked topic
  W->>W: research, save source texts, draft
  loop two rounds
    W->>E: draft + sources + code checks (no writer notes)
    E-->>W: scores 1–5, top three changes
    W->>W: revise
  end
  W->>G: branch + PR (label draft-post, Topic: id, scorecard)
  G->>R: email: intro, scorecard, Review & approve
  alt approve
    R->>G: merge → site rebuilds
    A->>A: hourly refresh sees the new post
    A-->>R: subscribers get intro + link
  else withhold
    R-->>G: leave open (draft) or close (drop topic)
  end
```

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternative |
|---|---|---|---|
| Who writes and edits | Scheduled Claude task, writer + a separate editor subagent | Best writing on the owner's plan; no API key on the server; the editor never sees the writer's reasoning | Local model (weaker), Claude API on the host (key on the server) |
| How a post is approved | Merge the PR | The host keeps no write access to the repo; GitHub keeps the draft, the review and the history | One-click approve link (would need a repo-write token on the host) |
| Topic sources | Official APIs and RSS only | Within each site's terms; predictable; testable with fixtures | Scraping (fragile, against terms), LinkedIn (no API) |
| Novelty | TF-IDF against published posts + MMR | Deterministic, no extra model, explainable numbers | Embeddings (better paraphrase detection) |
| Engagement | Source signals as percentiles within each source + model interest + recency | Comparable across sources without pretending 300 HN points = 300 Reddit upvotes | Learn weights from the site's own likes once there's history |
| Owner's email links | Signed, expiring, single-use, confirm-then-POST | Mail scanners follow links; a GET must change nothing | Login page (more friction for one click) |
| Subscriptions | In the site assistant, double opt-in | It already sees every published post and sends email | A newsletter service (another account, another processor of addresses) |
<!-- --8<-- [end:decisions] -->
