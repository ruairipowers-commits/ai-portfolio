"""MkDocs hook: substitute portfolio placeholders ({{SITE_URL}}, {{GITHUB_OWNER}}, {{HF_OWNER}}), build the
project tables from portfolio.yaml (<!-- projects:featured -->, <!-- projects:platform -->, <!-- projects:personal -->),
build the technology index (<!-- tech:index -->) from site/tech/*.md front matter, and link every technology named
in a post's **Stack:** line or a project table's stack column to its page under site/tech/.

Values come from scripts/portfolio_config.py (env in CI, else gh login, else portfolio.yaml),
so no personal details need to be committed. Runs on rendered HTML so it also covers
content pulled in by pymdownx.snippets.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import posixpath  # noqa: E402

from portfolio_config import demo_url, resolve, tiers  # noqa: E402
import assistant_corpus  # noqa: E402

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
    order = ["Languages", "Data & storage", "Search & retrieval", "Machine learning & data science",
             "Orchestration & agents", "Model providers",
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
        elif r.get("try_url"):
            link = f"✅ [{r['try_label']}]({r['try_url']})"
        elif r.get("url"):
            link = f"[Repo]({r['url']})"
        else:
            link = ""
        out.append(f"| {name} | {r['problem']} | {r['pattern']} | {link_tech(r['stack'], page_uri)} | {link} |")
    return "\n".join(out)


# ---------------------------------------------------------------- all posts, filterable (blog index)
import html as _html  # noqa: E402

_SITE = Path(__file__).resolve().parents[1] / "site"
# blog folder → (section label, URL prefix); posts use post_url_format "{slug}"
_POST_DIRS = {"blog": ("Industry project", "blog"), "personal": ("Personal project", "personal"),
              "classes": ("Class", "classes")}
_GOVERNANCE_SLUGS = {"governance", "governance-console"}


def _strip_md(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)            # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)         # links → their text
    text = re.sub(r"[*_`]", "", text)
    return " ".join(text.split())


def all_posts() -> list[dict]:
    """Every post from the three blogs, newest first: title, date, topics, keywords, section, excerpt, URL."""
    out = []
    for folder, (section, prefix) in _POST_DIRS.items():
        for f in sorted((_SITE / folder / "posts").glob("*.md")):
            text = f.read_text()
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            meta = yaml.safe_load(m.group(1)) if m else {}
            body = text[m.end():] if m else text
            title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), f.stem)
            intro = body.split("<!-- more -->")[0]
            intro = "\n".join(ln for ln in intro.splitlines() if not ln.startswith("# "))
            slug = meta.get("slug", f.stem)
            out.append({"title": title, "date": str(meta.get("date", "")), "slug": slug,
                        "topics": meta.get("categories") or [], "tags": meta.get("tags") or [],
                        "section": "AI governance" if slug in _GOVERNANCE_SLUGS else section,
                        "url": f"{prefix}/{slug}/", "excerpt": _strip_md(intro)})
    return sorted(out, key=lambda p: p["date"], reverse=True)


def _posts_index(page_uri: str) -> str:
    """Server-rendered list of every post (works without JS); assets/blog-filter.js adds the topic/section/date
    filters on top, reading the data-* attributes."""
    import datetime as dt
    depth = posixpath.dirname(page_uri).count("/") + (1 if posixpath.dirname(page_uri) else 0)
    up = "../" * depth
    e = _html.escape
    posts = all_posts()
    topics = sorted({t for p in posts for t in p["topics"]}, key=str.lower)
    sections = [s for s in ("Industry project", "AI governance", "Personal project", "Class")
                if any(p["section"] == s for p in posts)]
    months = sorted({p["date"][:7] for p in posts if p["date"]}, reverse=True)
    month_name = lambda ym: dt.date(int(ym[:4]), int(ym[5:7]), 1).strftime("%B %Y")  # noqa: E731
    h = ['<div class="post-filter" data-posts-filter>',
         '<div class="post-filter__row"><span class="post-filter__label">Topic</span>',
         '<button type="button" class="post-chip" data-topic="" aria-pressed="true">All</button>']
    h += [f'<button type="button" class="post-chip" data-topic="{e(t)}" aria-pressed="false">{e(t)}</button>'
          for t in topics]
    h += ['</div><div class="post-filter__row">',
          '<label class="post-filter__label" for="post-section">Type</label>',
          '<select id="post-section" data-section-select><option value="">All types</option>']
    h += [f'<option value="{e(s)}">{e(s)}s</option>' for s in sections]
    h += ['</select><label class="post-filter__label" for="post-when">When</label>',
          '<select id="post-when" data-when-select><option value="">Any time</option>',
          '<option value="30">Last 30 days</option><option value="90">Last 90 days</option>']
    h += [f'<option value="{m}">{month_name(m)}</option>' for m in months]
    h += ['</select><span class="post-filter__count" data-count></span></div></div>', '<div class="post-list">']
    for p in posts:
        d = dt.date.fromisoformat(p["date"]) if p["date"] else None
        chips = "".join(f'<span class="post-topic">{e(t)}</span>' for t in p["topics"])
        keys = ", ".join(p["tags"])
        h.append(
            f'<article class="post-card" data-date="{p["date"]}" data-section="{e(p["section"])}" '
            f'data-topics="{e("|".join(p["topics"]))}">'
            f'<p class="post-card__meta"><span class="post-card__section">{e(p["section"])}</span> · '
            f'<time datetime="{p["date"]}">{d.strftime("%-d %B %Y") if d else ""}</time></p>'
            f'<h2 class="post-card__title"><a href="{up}{p["url"]}">{e(p["title"])}</a></h2>'
            f'<p class="post-card__excerpt">{e(p["excerpt"])}</p>'
            f'<p class="post-card__topics">{chips}</p>'
            + (f'<p class="post-card__keys">Keywords: {e(keys)}</p>' if keys else "")
            + '</article>')
    h.append('<p class="post-empty" data-empty hidden>No posts match those filters.</p></div>')
    return "\n".join(h)


def _post_topics(markdown: str, page) -> str:
    """Under a post's title: its topics, each linking to the blog page filtered to that topic."""
    from urllib.parse import quote
    topics = page.meta.get("categories") or []
    if not topics:
        return markdown
    links = " ".join(f'<a class="post-topic" href="../../blog/?topic={quote(t)}">{_html.escape(t)}</a>' for t in topics)
    line = f'<p class="post-card__topics post-topics">{links}</p>'
    return re.sub(r"(?m)^(# .+)$", lambda m: m.group(1) + "\n\n" + line, markdown, count=1)


def _build_stats() -> str:
    """One line of facts about how this site was built, computed at build time from git and the content."""
    import datetime as dt
    import subprocess
    root = Path(__file__).resolve().parents[1]

    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    first = (git("log", "--reverse", "--format=%ad", "--date=short") or "").splitlines()[:1]
    commits = git("rev-list", "--count", "HEAD")
    posts = assistant_corpus.posts()
    techs = len([f for f in (root / "site" / "tech").glob("*.md") if f.name != "index.md"])
    projects = len([p for p in (root / "projects").iterdir() if p.is_dir()])
    parts = []
    if first:
        start = dt.date.fromisoformat(first[0])
        days = (dt.date.today() - start).days + 1
        parts.append(f"First commit **{start:%-d %B %Y}**; **{days} days** to this build")
    if commits and int(commits) > 1:
        parts.append(f"**{commits} commits**")
    parts += [f"**{projects} runnable projects**", f"**{len(posts)} write-ups**", f"**{techs} technology pages**"]
    return " · ".join(parts) + "."


def on_page_markdown(markdown, page, config, files):
    if re.match(r"(blog|personal|classes)/posts/", page.file.src_uri):
        markdown = _post_topics(markdown, page)
    if "<!-- posts:all -->" in markdown:
        markdown = markdown.replace("<!-- posts:all -->", _posts_index(page.file.src_uri))
    for tier in ("featured", "platform", "personal"):
        tag = f"<!-- projects:{tier} -->"
        if tag in markdown:
            markdown = markdown.replace(tag, _table(tier, page.file.src_uri))
    if "<!-- build:stats -->" in markdown:
        markdown = markdown.replace("<!-- build:stats -->", _build_stats())
    if "<!-- evidence -->" in markdown:
        markdown = markdown.replace("<!-- evidence -->", assistant_corpus.evidence_markdown(page.file.src_uri))
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


def on_config(config):
    """The site assistant's URL for the Ask button (overrides/main.html): its live demo URL, when the demos are
    deployed. Unset (local preview without DEMOS_URL) → no button, and no page-view or search logging."""
    url = demo_url("site-assistant", _cfg) if "site-assistant" in _cfg["projects"] and _cfg["demos_url"] else ""
    config.extra["assistant_url"] = os.getenv("PORTFOLIO_ASSISTANT_URL", url).rstrip("/")
    return config


def on_post_build(config):
    """Publish the assistant's extra knowledge (assistant/corpus.json: profile card, post dates, public repo docs,
    resume text), and ship its widget with the blog so the Ask button is always there (one source: the service)."""
    assistant_corpus.write(config["site_dir"], _cfg["site_url"], _cfg["github_owner"], _cfg.get("repo_name", "ai-portfolio"))
    if not config.extra.get("assistant_url"):
        return
    import shutil
    src = Path(__file__).resolve().parents[1] / "projects" / "site-assistant" / "src" / "siteassistant" / "static"
    dst = Path(config["site_dir"]) / "assets" / "assistant"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("widget.js", "widget.css"):
        shutil.copy2(src / name, dst / name)
