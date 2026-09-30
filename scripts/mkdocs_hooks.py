"""MkDocs hook: substitute portfolio placeholders ({{SITE_URL}}, {{GITHUB_OWNER}}) from portfolio.yaml.

Runs on rendered HTML so it also covers content pulled in by pymdownx.snippets.
"""
from pathlib import Path

import yaml

_cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "portfolio.yaml").read_text())
_SUBS = {"SITE_URL": _cfg["site_url"].rstrip("/"), "GITHUB_OWNER": _cfg["github_owner"]}


def _sub(text: str) -> str:
    for k, v in _SUBS.items():
        text = text.replace("{{" + k + "}}", v).replace("%7B%7B" + k + "%7D%7D", v)
    return text


def on_page_content(html, page, config, files):
    return _sub(html)
