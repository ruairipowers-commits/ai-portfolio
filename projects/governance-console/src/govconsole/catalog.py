"""The workflow catalog: every AI workflow the organisation runs, its owner, risk tier and control mapping.

Built automatically from the portfolio repo, so a new project appears in the console with no console change:
  portfolio.yaml           → which workflows exist, in display order
  specs/<slug>.yaml        → title, status, pattern, risk tier, owner, deep-dive controls, demo metadata
  projects/<slug>/docs/governance.md → status of every control (✅ 🟡 ⚪ 🔷) with how / config / options
  governance/controls.md   → the control standard itself

When the console runs inside the portfolio repo it reads those files live. Published on its own, it reads
catalog/workflows.json, which `scripts/build_catalog.py` (portfolio repo) regenerates on every build.
Projects whose spec says `kind: platform` (like this console) are not governed workflows and are skipped.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]          # projects/governance-console
BUNDLED = PKG_ROOT / "catalog" / "workflows.json"
ID = re.compile(r"\b((?:DATA|SEC|COST|MODEL|EVAL|OBS|HITL)-\d{2})\b")
STATUS = {"✅": "implemented", "🟡": "partial", "⚪": "not_applicable", "🔷": "documented_option"}
CATEGORY_HEAD = re.compile(r"^###\s+(.*)$")


def find_portfolio_root() -> Path | None:
    env = os.getenv("PORTFOLIO_ROOT")
    if env:
        return Path(env)
    cand = PKG_ROOT.parents[1]
    return cand if (cand / "portfolio.yaml").exists() and (cand / "governance" / "controls.md").exists() else None


def parse_controls(text: str) -> list[dict]:
    out, category = [], ""
    for line in text.splitlines():
        if m := CATEGORY_HEAD.match(line):
            category = m.group(1).strip()
        elif line.startswith("| ") and (m := ID.search(line.split("|")[1])):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append({"id": m.group(1), "name": cells[1], "category": category,
                        "requirement": cells[2] if len(cells) > 2 else "", "evidence": cells[3] if len(cells) > 3 else ""})
    return out


def parse_mapping(text: str) -> dict[str, dict]:
    """Rows of a project's docs/governance.md: | ID name | status | how | configure | other options |"""
    rows = {}
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not (m := ID.search(cells[0])) or len(cells) < 3:
            continue
        mark = next((k for k in STATUS if k in cells[1]), "")
        rows[m.group(1)] = {"status": STATUS.get(mark, "unknown"), "mark": mark, "how": cells[2],
                            "configure": cells[3] if len(cells) > 3 else "", "options": cells[4] if len(cells) > 4 else ""}
    return rows


def parse_models(path: Path) -> list[dict]:
    """A project's config/models.yaml: every registered model and which aliases point at it (in use)."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    used: dict[str, list[str]] = {}
    for alias, name in (raw.get("aliases") or {}).items():
        used.setdefault(name, []).append(alias)
    return [{"name": n, "provider": m.get("provider"), "model_id": str(m.get("model_id")), "kind": m.get("kind", "chat"),
             "approved": bool(m.get("approved")), "priced": m.get("input_per_mtok") is not None,
             "deprecation_date": str(m["deprecation_date"]) if m.get("deprecation_date") else None,
             "aliases": used.get(n, [])} for n, m in (raw.get("models") or {}).items()]


def build_from_portfolio(root: Path) -> dict:
    portfolio = yaml.safe_load((root / "portfolio.yaml").read_text())
    controls = parse_controls((root / "governance" / "controls.md").read_text())
    workflows = []
    for slug in portfolio.get("projects", []):
        spec_path = root / "specs" / f"{slug}.yaml"
        spec = yaml.safe_load(spec_path.read_text()) if spec_path.exists() else {}
        if spec.get("kind") == "platform":
            continue
        gov = root / "projects" / slug / "docs" / "governance.md"
        bp = spec.get("business_problem") or {}
        workflows.append({
            "slug": slug,
            "title": spec.get("title", slug),
            "name": (spec.get("demo") or {}).get("title") or spec.get("title", slug).split(":")[0],
            "emoji": (spec.get("demo") or {}).get("emoji", "🤖"),
            "status": spec.get("status", "planned"),
            "built": (root / "projects" / slug).is_dir(),
            "pattern": spec.get("pattern", ""),
            "domain": spec.get("domain", ""),
            "risk_tier": spec.get("risk_tier", "unrated"),
            "risk_rationale": spec.get("risk_rationale", ""),
            "users": bp.get("who", ""),
            "deep_dive": (spec.get("governance") or {}).get("deep_dive", []),
            "stack": {k: v for k, v in (spec.get("stack") or {}).items() if isinstance(v, str)},
            "controls": parse_mapping(gov.read_text()) if gov.exists() else {},
            "models": parse_models(root / "projects" / slug / "config" / "models.yaml"),
        })
    return {"generated_from": "portfolio", "controls": controls, "workflows": workflows,
            "author": portfolio.get("author", "")}


def load() -> dict:
    root = find_portfolio_root()
    if root:
        return build_from_portfolio(root)
    return json.loads(BUNDLED.read_text())


def write_bundled(root: Path, path: Path = BUNDLED) -> Path:
    cat = build_from_portfolio(root)
    cat["generated_from"] = "catalog/workflows.json (scripts/build_catalog.py)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
    return path
