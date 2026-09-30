"""Resolve per-owner settings (site URL, GitHub owner) without storing them in git.

Order: env PORTFOLIO_SITE_URL / PORTFOLIO_GITHUB_OWNER -> `gh api user` login -> portfolio.yaml.
Usage from shell: python3 scripts/portfolio_config.py  ->  "<site_url> <github_owner>"
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
    return {**cfg, "site_url": site.rstrip("/"), "github_owner": owner}


if __name__ == "__main__":
    c = resolve()
    print(c["site_url"], c["github_owner"])
