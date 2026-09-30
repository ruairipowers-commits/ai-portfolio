"""MkDocs hook: substitute portfolio placeholders ({{SITE_URL}}, {{GITHUB_OWNER}}).

Values come from scripts/portfolio_config.py (env in CI, else gh login, else portfolio.yaml),
so no personal details need to be committed. Runs on rendered HTML so it also covers
content pulled in by pymdownx.snippets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_config import resolve  # noqa: E402

_cfg = resolve()
_SUBS = {"SITE_URL": _cfg["site_url"], "GITHUB_OWNER": _cfg["github_owner"]}


def _sub(text: str) -> str:
    for k, v in _SUBS.items():
        text = text.replace("{{" + k + "}}", v).replace("%7B%7B" + k + "%7D%7D", v)
    return text


def on_page_content(html, page, config, files):
    return _sub(html)
