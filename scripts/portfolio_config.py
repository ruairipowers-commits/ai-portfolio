"""Resolve per-owner settings (site URL, GitHub owner) without storing them in git.

Order: env PORTFOLIO_SITE_URL / PORTFOLIO_GITHUB_OWNER -> `gh api user` login -> portfolio.yaml.
Usage from shell: python3 scripts/portfolio_config.py  ->  "<site_url> <github_owner> <hf_owner>"
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _gh_login() -> str | None:
    try:
        out = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


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
    return {**cfg, "site_url": site.rstrip("/"), "github_owner": owner, "hf_owner": hf or owner}


def links(slug: str, c: dict | None = None) -> dict:
    """Where a project lives: write-up, source repo and live demo (Hugging Face Space)."""
    c = c or resolve()
    return {"project": slug, "portfolio_url": c["site_url"] + "/",
            "blog_url": f"{c['site_url']}/blog/{slug}/",
            "source_url": f"https://github.com/{c['github_owner']}/{slug}",
            "demo_url": f"https://huggingface.co/spaces/{c['hf_owner']}/{slug}"}


if __name__ == "__main__":
    c = resolve()
    print(c["site_url"], c["github_owner"], c["hf_owner"])
