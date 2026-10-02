"""MkDocs hook: substitute portfolio placeholders ({{SITE_URL}}, {{GITHUB_OWNER}}, {{HF_OWNER}}).

Values come from scripts/portfolio_config.py (env in CI, else gh login, else portfolio.yaml),
so no personal details need to be committed. Runs on rendered HTML so it also covers
content pulled in by pymdownx.snippets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_config import resolve  # noqa: E402

_cfg = resolve()
_SUBS = {"SITE_URL": _cfg["site_url"], "GITHUB_OWNER": _cfg["github_owner"], "HF_OWNER": _cfg["hf_owner"],
         "DEMOS_URL": _cfg["demos_url"] or "#demos-not-configured"}


def _sub(text: str) -> str:
    for k, v in _SUBS.items():
        text = text.replace("{{" + k + "}}", v).replace("%7B%7B" + k + "%7D%7D", v)
    return text


_PROJECTS = [p.name for p in (Path(__file__).resolve().parents[1] / "projects").iterdir() if p.is_dir()]


def _source_links(html: str) -> str:
    """While project repos aren't published on their own (source_links: monorepo), point links at this repo's folders."""
    if _cfg.get("source_links", "monorepo") != "monorepo":
        return html
    owner, repo = _cfg["github_owner"], _cfg.get("repo_name", "ai-portfolio")
    for slug in _PROJECTS:
        base = f"https://github.com/{owner}/{slug}"
        mono = f"https://github.com/{owner}/{repo}"
        html = html.replace(base + "/blob/main/", f"{mono}/blob/main/projects/{slug}/")
        html = html.replace(base + "/tree/main/", f"{mono}/tree/main/projects/{slug}/")
        html = html.replace(f'href="{base}"', f'href="{mono}/tree/main/projects/{slug}"')
    return html


def on_page_content(html, page, config, files):
    return _source_links(_sub(html))
