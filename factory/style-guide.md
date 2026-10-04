# Writing & build conventions

These rules apply to every generated artifact. Edit this file to change how
future projects are written — the generator reads it every time.

## Voice (blog posts)

- Written as Ruairi, first person, practitioner to practitioner. 25 years in financial data and
  trading technology; the reader is a hiring manager, CTO or head of data at an investment firm.
- Lead with the business problem and the decision, not the technology.
- Concrete over grand: numbers, named trade-offs, what I'd do differently. No "revolutionize",
  "unlock", "seamless", "cutting-edge", "in today's fast-paced world".
- Say plainly what is synthetic, what is mocked, and what isn't built yet.
- Every project on this site is my own work, built for learning and as an example. Never say or imply a project
  (or the EVO-X1 setup) is used for, built for or holds client or employer work or data.
- 1,200–1,800 words per project post. Short paragraphs. Tables for trade-offs.

## Blog post structure (project)

Follow `factory/templates/blog-post.md` exactly — sections are what readers scan for.

## Diagrams

- Mermaid only (renders on GitHub and the site). One flow diagram required; one sequence
  diagram if there's an interactive or multi-call path.
- Label nodes with *what* and the control ID where a control lives (e.g. `DQ gate<br/>DATA-02`).

## Repositories

- Runs offline in < 5 minutes with `pip install -e ".[dev]"` + one command; mock provider by default.
- Every project ships a **Streamlit app** (`<cli> ui`, `src/<pkg>/ui.py`) laid out as **1 · Input → 2 · Run → 3 · Output**:
  - Input: a working default (synthetic data loaded automatically) plus a **"Try to break it"** control that edits the
    untrusted input (vendor notes, broker text, documents) with one-click adversarial examples; uploads where it makes sense.
  - Run: one primary button; steps shown with st.status; a failed data gate stops the run and says why.
  - Output: headline metrics, then tabs for results, the human-review/approval step, the eval gate and audit/cost.
  - Model picker lists only approved, priced models with a key present; default is the offline mock.
  - A "Reset demo data" button. No telemetry (`.streamlit/config.toml` gatherUsageStats=false).
  - Tested headless with `streamlit.testing` (`tests/test_ui.py`): default run, a break-it case, the human step.
  - Links back to the blog post, source repo, portfolio and governance console (`demo.py`), and runs as a hosted demo
    (`Dockerfile.space`) where each visitor gets a private copy of the data.
- Every workflow reports to the governance console through the shared `telemetry.py` and obeys its kill switch in the
  code path (not only by disabling buttons).
- Every project has: README (template), `docs/architecture.md`, `docs/governance.md` (maps EVERY
  control ID), `docs/aws-native.md`, `infra/aws/` Terraform starter, `config/settings.yaml`,
  `config/models.yaml`, `prompts/`, `evals/golden_set.yaml`, tests, CI workflow, LICENSE.
- At least one adversarial golden case (injection/abuse) and one compliance case.
- Numbers are computed by code/SQL; the LLM explains, drafts, or decides within policy.
- Use `{{SITE_URL}}` for links back to the site; publish script substitutes it.

## Governance mapping statuses

✅ implemented · 🟡 partial / manual · ⚪ not applicable (give reason) · 🔷 option documented, not built
