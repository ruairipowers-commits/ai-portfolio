"""What the site assistant knows beyond the site's search index, built from this repo at site-build time.

The MkDocs hook calls `write()` after every build. It publishes build/assistant/corpus.json next to the site's
search index, so the assistant only ever reads what is already public. It contains:

  profile  a compact "profile card": who Ruairi is, his MIT courses, evidence by topic, the technologies each piece
           of work demonstrates, and the newest work first. It's rebuilt from the posts on every build, so a new
           project or technology shows up in answers as soon as it's published.
  pages    every post's date, type, topics and short title, by site path, so excerpts can carry dates.
  docs     public text that isn't on the site itself: each project's README and docs/ in the GitHub repo, the
           governance controls, coursework READMEs and notebook commentary, and the resume PDF.

`evidence_markdown()` renders the same evidence as tables for the About page (<!-- evidence -->), so people and
the assistant see the same thing.

    python scripts/assistant_corpus.py            # print the profile card (what the model sees about Ruairi)
"""
from __future__ import annotations

import datetime as dt
import json
import posixpath
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
POST_DIRS = {"blog": "Industry project", "personal": "Personal project", "classes": "Class"}
GOVERNANCE = {"governance", "governance-console", "questions-for-your-ai-team", "how-i-govern-this-site"}


# ---------------------------------------------------------------- reading the site
def _front(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (yaml.safe_load(m.group(1)) or {}, text[m.end():]) if m else ({}, text)


def plain(md: str) -> str:
    md = re.sub(r"<!--.*?-->", " ", md, flags=re.S)
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"\{[ .#][^}]*\}", " ", md)                     # attr_list
    md = re.sub(r"[*_`#>|]", " ", md)
    return " ".join(md.split())


def posts() -> list[dict]:
    """Every post on the site, newest first."""
    out = []
    for folder, kind in POST_DIRS.items():
        for f in sorted((SITE / folder / "posts").glob("*.md")):
            meta, body = _front(f.read_text())
            slug = meta.get("slug", f.stem)
            title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), slug)
            intro = body.split("<!-- more -->")[0]
            intro = "\n".join(ln for ln in intro.splitlines() if not ln.startswith("# "))
            out.append({"src": f"{folder}/posts/{f.name}", "path": f"{folder}/{slug}/", "slug": slug,
                        "title": title, "short": meta.get("short") or re.split(r"[:—]", title)[0].strip(),
                        "date": str(meta.get("date", "")),
                        "kind": meta.get("section") or ("AI governance" if slug in GOVERNANCE else kind),
                        "topics": meta.get("categories") or [], "keywords": meta.get("tags") or [],
                        "audience": meta.get("audience") or [],
                        "summary": plain(intro),
                        "stack": next((ln for ln in body.splitlines() if ln.startswith("**Stack:**")), "")})
    return sorted(out, key=lambda p: p["date"], reverse=True)


def technologies(all_posts: list[dict]) -> list[dict]:
    """Each technology page and the posts its "In this portfolio" section links to."""
    by_src = {p["src"]: p for p in all_posts}
    out = []
    for f in sorted((SITE / "tech").glob("*.md")):
        if f.name == "index.md":
            continue
        meta, body = _front(f.read_text())
        section = body.split("## In this portfolio", 1)[1].split("\n## ", 1)[0] if "## In this portfolio" in body else ""
        used = []
        for target in re.findall(r"\]\(([^)#]+\.md)", section):
            src = posixpath.normpath(posixpath.join("tech", target))
            if src in by_src and by_src[src] not in used:
                used.append(by_src[src])
        aliases = meta.get("aliases") or [meta.get("title", f.stem)]
        pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in aliases) + r")(?![\w-])")
        for p in all_posts:                  # …and every post whose **Stack:** line names it
            if p not in used and pat.search(p["stack"]):
                used.append(p)
        used.sort(key=lambda p: p["date"], reverse=True)
        out.append({"slug": f.stem, "title": meta.get("title", f.stem), "category": meta.get("category", ""),
                    "used_in": used})
    return out


def about_lines() -> list[str]:
    """The About page's bullet list, one entry per bullet (continuation lines joined)."""
    body = _front((SITE / "about.md").read_text())[1]
    items: list[str] = []
    for ln in body.split("## ", 1)[0].splitlines():
        if ln.startswith("- "):
            items.append(ln[2:])
        elif ln.startswith("  ") and items:
            items[-1] += " " + ln.strip()
    return [plain(i) for i in items]


def resume_pdf() -> Path | None:
    found = sorted((SITE / "assets").glob("*[Rr]esume*.pdf"))
    return found[0] if found else None


def resume_text() -> str:
    pdf = resume_pdf()
    if not pdf:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:                       # site builds without pypdf still work; the resume just isn't indexed
        return ""
    return " ".join(" ".join((pg.extract_text() or "") for pg in PdfReader(str(pdf)).pages).split())


# ---------------------------------------------------------------- the profile card
def profile_card(all_posts: list[dict], techs: list[dict], today: str) -> str:
    classes = [p for p in all_posts if p["kind"] == "Class"]
    work = [p for p in all_posts if p["kind"] != "Class"]
    topics: dict[str, list[dict]] = {}
    for p in all_posts:
        for t in p["topics"]:
            topics.setdefault(t, []).append(p)
    lines = [f"Profile and evidence for Ruairi Powers, generated {today} from his published site. Newest work first.",
             "", "Background (About page):"] + [f"- {ln}" for ln in about_lines()]
    lines += ["", "MIT Professional Education coursework (the Classes page has the full write-ups):"]
    for p in sorted(classes, key=lambda p: p["date"]):
        lines.append(f"- {p['short']} ({p['date']}): {_trim(p['summary'], 55)}")
    lines += ["", "Most recent work (date · type · title):"]
    lines += [f"- {p['date']} · {p['kind']} · {p['short']}" for p in all_posts[:8]]
    lines += ["", "Evidence by topic (each item is a published write-up):"]
    for t in sorted(topics, key=str.lower):
        lines.append(f"- {t}: " + "; ".join(f"{p['short']} ({p['date'][:7]})" for p in topics[t]))
    lines += ["", "Technologies demonstrated in his own work (technology: where):"]
    shown = [t for t in techs if t["used_in"]]
    lines += [f"- {t['title']}: " + "; ".join(p["short"] for p in t["used_in"]) for t in shown]
    lines += ["", f"Industry projects: {len([p for p in work if p['kind'] == 'Industry project'])}; "
                  f"personal projects: {len([p for p in work if p['kind'] == 'Personal project'])}; "
                  f"classes: {len(classes)}; technology pages: {len(techs)}."]
    return "\n".join(lines)


def _trim(text: str, words: int) -> str:
    w = text.split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


# ---------------------------------------------------------------- public docs outside the site
def repo_docs(github_base: str) -> list[dict]:
    """README and docs/ of every project, the controls, coursework: [{url, title, section, text}] per section."""
    files = []
    for proj in sorted(p for p in (ROOT / "projects").iterdir() if p.is_dir()):
        files += [proj / "README.md"] + sorted((proj / "docs").glob("*.md"))
    files += [ROOT / "governance" / "controls.md"] + sorted((ROOT / "coursework").glob("*/README.md"))
    out = []
    for f in files:
        if not f.exists():
            continue
        rel = f.relative_to(ROOT).as_posix()
        url, title, section, buf = f"{github_base}/blob/main/{rel}", f"GitHub · {rel}", "", []

        def flush():
            text = plain("\n".join(buf))
            if len(text.split()) >= 8:
                out.append({"url": url + (f"#{_anchor(section)}" if section else ""), "title": title,
                            "section": section, "text": text})
        for ln in f.read_text().splitlines():
            if re.match(r"^#{1,3} ", ln):
                flush()
                buf, section = [], plain(ln.lstrip("#"))
            else:
                buf.append(ln)
        flush()
    for nb in sorted((ROOT / "coursework").glob("*/*.ipynb")):           # the analysis commentary, not the code
        rel = nb.relative_to(ROOT).as_posix()
        cells = json.loads(nb.read_text()).get("cells", [])
        text = plain("\n".join("".join(c.get("source", [])) for c in cells if c.get("cell_type") == "markdown"))
        if text:
            out.append({"url": f"{github_base}/blob/main/{rel}", "title": f"GitHub · {rel} (notebook commentary)",
                        "section": "", "text": text})
    return out


def _anchor(s: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", s.lower()).strip().replace(" ", "-")


# ---------------------------------------------------------------- outputs
def build(site_url: str, github_owner: str, repo: str = "ai-portfolio", today: str | None = None) -> dict:
    today = today or dt.date.today().isoformat()
    all_posts = posts()
    techs = technologies(all_posts)
    docs = repo_docs(f"https://github.com/{github_owner}/{repo}")
    pdf = resume_pdf()
    text = resume_text()
    if pdf and text:
        docs.append({"url": f"{site_url.rstrip('/')}/assets/{pdf.name}", "title": "Resume (PDF)", "section": "",
                     "text": text})
    return {"generated": today, "profile": profile_card(all_posts, techs, today),
            "profile_url": f"{site_url.rstrip('/')}/about/#skills-and-evidence",
            # page list: the assistant's citations, its new-post emails to subscribers (intro + link), and the
            # editorial scout's novelty check (what's already published)
            "pages": {p["path"]: {**{k: p[k] for k in ("title", "short", "date", "kind", "topics", "audience")},
                                  "intro": p["summary"][:600]} for p in all_posts},
            "docs": docs}


def write(site_dir: str, site_url: str, github_owner: str, repo: str = "ai-portfolio") -> Path:
    out = Path(site_dir) / "assistant" / "corpus.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(site_url, github_owner, repo), ensure_ascii=False, indent=1))
    return out


def evidence_markdown(page_uri: str) -> str:
    """The About page's "Skills and evidence" section: the same evidence the assistant uses, as tables."""
    here = posixpath.dirname(page_uri) or "."
    all_posts = posts()
    link = lambda p: f"[{p['short']}]({posixpath.relpath(p['src'], here)})"      # noqa: E731
    topics: dict[str, list[dict]] = {}
    for p in all_posts:
        for t in p["topics"]:
            topics.setdefault(t, []).append(p)
    out = ["Generated from the published write-ups on every build, so it's always current. Newest first.", "",
           "| Area | Evidence | Latest |", "|---|---|---|"]
    for t in sorted(topics, key=str.lower):
        ps = topics[t]
        out.append(f"| {t} | " + " · ".join(link(p) for p in ps) + f" | {ps[0]['date']} |")
    out += ["", "**Technologies used in my own work**", "", "| Technology | Where |", "|---|---|"]
    for tech in technologies(all_posts):
        if tech["used_in"]:
            tlink = f"[{tech['title']}]({posixpath.relpath('tech/' + tech['slug'] + '.md', here)})"
            out.append(f"| {tlink} | " + " · ".join(link(p) for p in tech["used_in"]) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    ps = posts()
    print(profile_card(ps, technologies(ps), dt.date.today().isoformat()))
