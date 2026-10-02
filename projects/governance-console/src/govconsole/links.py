"""Where things live: the portfolio site, each workflow's write-up, source repo and live demo.

Resolved without committing anyone's username: env PORTFOLIO_SITE_URL / PORTFOLIO_GITHUB_OWNER / PORTFOLIO_HF_OWNER,
then portfolio_links.json (written by the portfolio's publish script), then — inside the portfolio repo —
scripts/portfolio_config.py. Anything still unresolved is simply not linked.
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache

from .catalog import PKG_ROOT, find_portfolio_root


@lru_cache(maxsize=1)
def portfolio() -> dict:
    data = {}
    f = PKG_ROOT / "portfolio_links.json"
    if f.exists():
        data = json.loads(f.read_text())
    root = find_portfolio_root()
    if not data and root and (root / "scripts" / "portfolio_config.py").exists():
        sys.path.insert(0, str(root / "scripts"))
        try:
            from portfolio_config import resolve
            data = resolve()
        except Exception:
            data = {}
    out = {"site_url": os.getenv("PORTFOLIO_SITE_URL") or data.get("site_url", ""),
           "github_owner": os.getenv("PORTFOLIO_GITHUB_OWNER") or data.get("github_owner", ""),
           "hf_owner": os.getenv("PORTFOLIO_HF_OWNER") or data.get("hf_owner", ""),
           "demos_url": os.getenv("PORTFOLIO_DEMOS_URL") or data.get("demos_url", ""),
           "demos_target": os.getenv("PORTFOLIO_DEMOS_TARGET") or data.get("demos_target", ""),
           "source_base": os.getenv("PORTFOLIO_SOURCE_BASE") or (data.get("source_url", "").rsplit("/", 1)[0] if data.get("source_url") else "")}
    return {k: v.rstrip("/") for k, v in out.items() if v and "REPLACE" not in v and "{{" not in v}


def for_slug(slug: str) -> dict[str, str]:
    p = portfolio()
    out = {}
    if "site_url" in p:
        out["blog"] = f"{p['site_url']}/blog/{slug}/"
    if p.get("source_base"):
        out["source"] = f"{p['source_base']}/{slug}"
    elif "github_owner" in p:
        out["source"] = f"https://github.com/{p['github_owner']}/{slug}"
    if p.get("demos_url"):
        out["demo"] = f"{p['demos_url']}/{slug}" + ("" if p.get("demos_target") == "huggingface" else "/")
    elif "hf_owner" in p:
        out["demo"] = f"https://huggingface.co/spaces/{p['hf_owner']}/{slug}"
    return out


def console() -> dict[str, str]:
    p = portfolio()
    out = for_slug("governance-console")
    if "site_url" in p:
        out["portfolio"] = p["site_url"] + "/"
        out["governance"] = p["site_url"] + "/blog/governance/"
    out.pop("demo", None)
    return out
