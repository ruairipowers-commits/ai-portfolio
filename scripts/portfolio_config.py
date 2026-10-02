"""Resolve per-owner settings (site URL, GitHub owner) without storing them in git.

Order: env PORTFOLIO_SITE_URL / PORTFOLIO_GITHUB_OWNER -> `gh api user` login -> portfolio.yaml.
Usage from shell: python3 scripts/portfolio_config.py  ->  "<site_url> <github_owner> <hf_owner> <demos_url|->"
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = "governance-console"   # slug of the governance console project


def _gh_login() -> str | None:
    try:
        out = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


TARGETS = ("selfhost", "huggingface", "cloudflare", "cloudrun")


def resolve() -> dict:
    cfg = yaml.safe_load((ROOT / "portfolio.yaml").read_text())
    owner = os.getenv("PORTFOLIO_GITHUB_OWNER")
    site = os.getenv("PORTFOLIO_SITE_URL")
    if not owner and cfg["github_owner"].startswith("REPLACE"):
        owner = _gh_login()
    owner = owner or cfg["github_owner"]
    if not site:
        site = cfg["site_url"] if not cfg["site_url"].count("REPLACE") else f"https://{owner}.github.io/ai-portfolio"
    hf = os.getenv("PORTFOLIO_HF_OWNER") or ("" if cfg.get("hf_owner", "REPLACE").startswith("REPLACE") else cfg["hf_owner"])
    hf = hf or owner
    demos = cfg.get("demos") or {}
    target = (os.getenv("PORTFOLIO_DEMOS_TARGET") or demos.get("target") or "huggingface").strip().lower()
    if target not in TARGETS:
        raise SystemExit(f"demos target '{target}' must be one of {', '.join(TARGETS)}")
    if target == "huggingface":
        demos_url = f"https://huggingface.co/spaces/{hf}"
    else:
        base = os.getenv("PORTFOLIO_DEMOS_URL") or demos.get("base_url", "")
        demos_url = "" if "REPLACE" in base else base
    return {**cfg, "site_url": site.rstrip("/"), "github_owner": owner, "hf_owner": hf,
            "demos_target": target, "demos_url": demos_url.rstrip("/")}


def demo_url(slug: str, c: dict) -> str:
    """Public URL of one app's live demo under the configured target ('' if the base URL isn't set)."""
    if not c["demos_url"]:
        return ""
    return f"{c['demos_url']}/{slug}" + ("" if c["demos_target"] == "huggingface" else "/")


def source_url(slug: str, c: dict) -> str:
    if c.get("source_links", "monorepo") == "standalone":
        return f"https://github.com/{c['github_owner']}/{slug}"
    return f"https://github.com/{c['github_owner']}/{c.get('repo_name', 'ai-portfolio')}/tree/main/projects/{slug}"


def site_title() -> str:
    """The blog's site_name (mkdocs.yml), so the apps' banner says exactly what the blog's header says."""
    import re
    m = re.search(r"^site_name:\s*(.+)$", (ROOT / "mkdocs.yml").read_text(), re.M)
    return m.group(1).strip().strip("'\"") if m else "AI Workflow Portfolio"


def links(slug: str, c: dict | None = None) -> dict:
    """Where a project lives: write-up, source code, live demo, the governance console's demo, and the blog's
    top-level navigation (for the banner the apps share with the blog)."""
    c = c or resolve()
    return {"project": slug, "site_url": c["site_url"], "github_owner": c["github_owner"], "hf_owner": c["hf_owner"],
            "demos_target": c["demos_target"], "demos_url": c["demos_url"],
            "site_title": site_title(),
            "standard_url": c["site_url"] + "/blog/governance/",
            "blog_index_url": c["site_url"] + "/blog/",
            "about_url": c["site_url"] + "/about/",
            "demos_home_url": c["demos_url"] and c["demos_url"] + "/",
            "portfolio_url": c["site_url"] + "/",
            "blog_url": f"{c['site_url']}/blog/{slug}/",
            "source_url": source_url(slug, c),
            "demo_url": demo_url(slug, c),
            "console_url": demo_url(CONSOLE, c)}


def governance_url(c: dict) -> str:
    """What the apps post telemetry to and poll for the kill switch, per target."""
    if c["demos_target"] == "huggingface":
        return space_host(c["hf_owner"], CONSOLE)
    if c["demos_target"] == "selfhost":
        return f"http://{CONSOLE}:7860/{CONSOLE}"      # compose network, never leaves the machine
    return demo_url(CONSOLE, c).rstrip("/")


def space_host(owner: str, slug: str) -> str:
    """Direct URL of a Space's app (what the apps call for telemetry), e.g. https://me-governance-console.hf.space"""
    return "https://" + f"{owner}-{slug}".lower().replace("_", "-").replace(".", "-") + ".hf.space"


if __name__ == "__main__":
    c = resolve()
    print(c["site_url"], c["github_owner"], c["hf_owner"], c["demos_url"] or "-")
