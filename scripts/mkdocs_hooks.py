"""MkDocs hook: substitute portfolio placeholders ({{SITE_URL}}, {{GITHUB_OWNER}}, {{HF_OWNER}}), build the
project tables from portfolio.yaml (<!-- projects:featured -->, <!-- projects:platform -->, <!-- projects:personal -->),
build the technology index (<!-- tech:index -->) from site/tech/*.md front matter, and link every technology named
in a post's **Stack:** line or a project table's stack column to its page under site/tech/.

Values come from scripts/portfolio_config.py (env in CI, else gh login, else portfolio.yaml),
so no personal details need to be committed. Runs on rendered HTML so it also covers
content pulled in by pymdownx.snippets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import posixpath  # noqa: E402

from portfolio_config import demo_url, resolve, tiers  # noqa: E402

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


# ---------------------------------------------------------------- technologies
import re  # noqa: E402

import yaml  # noqa: E402

_TECH_DIR = Path(__file__).resolve().parents[1] / "site" / "tech"
# Short forms of AWS services as they appear in stack lines → section anchor on tech/aws.md
_AWS_SHORT = {"MWAA": "mwaa", "RDS": "rds", "SNS": "sns", "SES": "ses", "App Runner": "app-runner",
              "Aurora": "aurora-serverless", "AppConfig": "appconfig", "Athena": "athena", "Glue": "glue",
              "ECS Fargate": "ecs-fargate", "ECS": "ecs-fargate", "Fargate": "ecs-fargate", "Lambda": "lambda",
              "Step Functions": "step-functions", "Secrets Manager": "secrets-manager", "CloudWatch": "cloudwatch",
              "S3 Object Lock": "s3-object-lock", "S3": "s3", "Firehose": "kinesis-data-firehose",
              "Kinesis Data Firehose": "kinesis-data-firehose", "OpenSearch Serverless": "opensearch-serverless",
              "Bedrock Knowledge Bases": "bedrock-knowledge-bases", "Bedrock Knowledge Base": "bedrock-knowledge-bases",
              "AWS Budgets": "aws-budgets", "Budgets": "aws-budgets"}


def _load_tech() -> tuple[list[dict], dict[str, str]]:
    techs, links = [], {}
    for f in sorted(_TECH_DIR.glob("*.md")):
        if f.name == "index.md":
            continue
        m = re.match(r"^---\n(.*?)\n---\n", f.read_text(), re.S)
        meta = yaml.safe_load(m.group(1)) if m else {}
        meta["slug"] = f.stem
        techs.append(meta)
        for a in meta.get("aliases") or []:
            links.setdefault(a, f"tech/{f.stem}.md")
    for short, anchor in _AWS_SHORT.items():
        links.setdefault(short, f"tech/aws.md#{anchor}")
    return techs, links


_TECHS, _TECH_LINKS = _load_tech()
_TECH_RE = re.compile(r"(?<![\w/#.-])(" + "|".join(re.escape(a) for a in sorted(_TECH_LINKS, key=len, reverse=True))
                      + r")(?![\w-])") if _TECH_LINKS else None


def link_tech(text: str, page_uri: str) -> str:
    """Wrap each technology named in `text` (once each) in a link to its page, relative to `page_uri`."""
    if not _TECH_RE:
        return text
    here, seen = posixpath.dirname(page_uri) or ".", set()

    def sub(m):
        target = _TECH_LINKS[m.group(1)]
        if target in seen:
            return m.group(0)
        seen.add(target)
        path, _, anchor = target.partition("#")
        rel = posixpath.relpath(path, here) + (f"#{anchor}" if anchor else "")
        return f"[{m.group(1)}]({rel})"
    return _TECH_RE.sub(sub, text)


def _tech_index(page_uri: str) -> str:
    order = ["Languages", "Data & storage", "Search & retrieval", "Orchestration & agents", "Model providers",
             "Apps & APIs", "Infrastructure & delivery", "Cloud (AWS)"]
    here = posixpath.dirname(page_uri) or "."
    out = []
    for cat in order + sorted({t.get("category", "Other") for t in _TECHS} - set(order)):
        rows = [t for t in _TECHS if t.get("category", "Other") == cat]
        if not rows:
            continue
        out += [f"## {cat}", "", "| Technology | What it is | Official docs |", "|---|---|---|"]
        for t in sorted(rows, key=lambda t: t.get("title", t["slug"]).lower()):
            rel = posixpath.relpath(f"tech/{t['slug']}.md", here)
            host = re.sub(r"^https?://(www\.)?", "", t.get("docs", "")).split("/")[0]
            out.append(f"| [{t.get('title', t['slug'])}]({rel}) | {t.get('summary', '')} | "
                       f"[{host}]({t.get('docs', '')}) |")
        out.append("")
    return "\n".join(out)


def _table(tier: str, page_uri: str) -> str:
    rows = tiers(_cfg)[tier]
    if not rows:
        return "*None yet.*" if tier == "personal" else ""
    here = posixpath.dirname(page_uri)
    out = ["| Project | Problem | Pattern | Stack highlights | Try it |", "|---|---|---|---|---|"]
    for r in rows:
        if r["post"]:
            name = f"[{r['name']}]({posixpath.relpath(r['post'], here or '.')})"
        elif r.get("url"):
            name = f"[{r['name']}]({r['url']})"
        else:
            name = r["name"]
        if r["demo"] and _cfg["demos_url"]:
            link = f"✅ [Live demo]({demo_url(r['slug'], _cfg)})"
        elif r.get("url"):
            link = f"[Repo]({r['url']})"
        else:
            link = ""
        out.append(f"| {name} | {r['problem']} | {r['pattern']} | {link_tech(r['stack'], page_uri)} | {link} |")
    return "\n".join(out)


def on_page_markdown(markdown, page, config, files):
    for tier in ("featured", "platform", "personal"):
        tag = f"<!-- projects:{tier} -->"
        if tag in markdown:
            markdown = markdown.replace(tag, _table(tier, page.file.src_uri))
    if "<!-- tech:index -->" in markdown:
        markdown = markdown.replace("<!-- tech:index -->", _tech_index(page.file.src_uri))
    # a post's **Stack:** line names its technologies: link each to its page
    markdown = re.sub(r"(?m)^(\*\*Stack:\*\*)(.*)$",
                      lambda m: m.group(1) + link_tech(m.group(2), page.file.src_uri), markdown)
    return markdown


def on_page_content(html, page, config, files):
    return _source_links(_sub(html))


def on_nav(nav, config, files):
    """Read every page's front matter up front, so a page's `icon:` shows on the navigation tabs of every page,
    not only on pages rendered after it."""
    for page in nav.pages:
        if not page.meta:
            try:
                page.read_source(config)
            except Exception:  # noqa: BLE001 — generated pages (blog indexes) have no source to read yet
                pass
    return nav
