"""Feeds mode of the daily scan: read each course's release feeds (config/feeds.yaml), keep entries newer than the
course's latest item, and summarise each with the `course-news` alias (DATA-01: every item links its source).

Feed text is untrusted: it goes to the model inside the delimited request (SEC-02), the reply must validate against
`NewsSummary` (SEC-04), and code sets the course, date, title, link and source fields itself.
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Literal

import yaml
from pydantic import Field

from . import ai
from .config import LEVELS, Settings, root
from .news import KINDS, NewsItem
from .schemas import Strict

ATOM = "{http://www.w3.org/2005/Atom}"
PRE = re.compile(r"(?i)(\b|\d)(rc|alpha|beta|dev|pre|preview|nightly)\d*\b")


class NewsSummary(Strict):
    summary: str = Field(min_length=10, max_length=400)
    kind: Literal[KINDS] = "release"
    material: bool = False
    affects: list[Literal[LEVELS]] = []
    reason: str = Field(default="", max_length=300)
    status: Literal["deprecated", "replaced", "retired"] | None = None


def feeds_config() -> dict[str, list[dict]]:
    p = root() / "config" / "feeds.yaml"
    return (yaml.safe_load(p.read_text()) or {}).get("courses", {}) if p.exists() else {}


def feed_url(f: dict) -> str:
    if "github" in f:
        return f"https://github.com/{f['github']}/releases.atom"
    if "pypi" in f:
        return f"https://pypi.org/rss/project/{f['pypi']}/releases.xml"
    return f.get("rss", "")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "crash-course-news/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(3_000_000).decode("utf-8", "replace")


def _text(html: str) -> str:
    t = re.sub(r"(?s)<(script|style).*?</\1>", " ", html or "")
    t = re.sub(r"<[^>]+>", " ", t)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&"), ("&nbsp;", " ")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def _day(value: str) -> str:
    value = (value or "").strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse(xml: str) -> list[dict]:
    """Atom or RSS → [{title, link, date, text}], newest first."""
    root_ = ET.fromstring(xml)
    out = []
    for e in root_.iter(f"{ATOM}entry"):
        link = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), "")
        body = e.findtext(f"{ATOM}content") or e.findtext(f"{ATOM}summary") or ""
        out.append({"title": (e.findtext(f"{ATOM}title") or "").strip(), "link": link or "",
                    "date": _day(e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published") or ""),
                    "text": _text(body)})
    for it in root_.iter("item"):
        out.append({"title": (it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip(),
                    "date": _day(it.findtext("pubDate") or ""), "text": _text(it.findtext("description") or "")})
    return sorted([x for x in out if x["title"] and x["date"]], key=lambda x: x["date"], reverse=True)


def scan(conn, s: Settings, courses: dict, existing: list[dict], only: list[str] | None = None,
         fetcher=fetch) -> tuple[list[dict], list[str]]:
    """New items for every course with feeds, and a list of problems (unreachable feeds, failed summaries)."""
    cfg = s["news"]
    newest = {}
    for it in existing:
        newest.setdefault(it["course"], it["date"])
    floor = (datetime.now(timezone.utc).date() - timedelta(days=cfg["lookback_days"])).isoformat()
    spent, items, problems = 0.0, [], []
    for slug, feeds in sorted(feeds_config().items()):
        if (only and slug not in only) or slug not in courses:
            continue
        since = max(newest.get(slug, floor), floor)
        entries = []
        for f in feeds:
            url = feed_url(f)
            if not url.startswith("https://"):
                problems.append(f"{slug}: feed is not https")
                continue
            try:
                entries += [e for e in parse(fetcher(url)) if e["date"] > since
                            and (f.get("prereleases") or not PRE.search(e["title"]))]
            except Exception as e:  # noqa: BLE001 — one bad feed must not stop the scan
                problems.append(f"{slug}: {url} unreadable ({type(e).__name__})")
        entries = sorted({e["link"] or e["title"]: e for e in entries}.values(), key=lambda e: e["date"],
                         reverse=True)[: cfg["max_items_per_course"]]
        for e in entries:
            if not e["link"].startswith("https://"):
                continue
            payload = {"course": slug, "course_title": courses[slug].title, "title": e["title"][:160],
                       "link": e["link"], "date": e["date"], "text": e["text"][:4000], "levels": list(LEVELS)}
            res = ai.call(conn, s, "news_summary", "news", cfg["summary_alias"], payload, NewsSummary,
                          budget_usd=max(cfg["max_usd_per_scan"] - spent, 0.0), max_tokens=500)
            spent += res.cost_usd
            if not res.value:
                problems.append(f"{slug}: {e['title'][:60]}: {res.error[:120]}")
                continue
            v = res.value
            item = {"course": slug, "date": e["date"], "title": e["title"][:160], "summary": v.summary, "url": e["link"],
                    "kind": v.kind, "material": v.material and bool(v.affects), "affects": v.affects if v.material else [],
                    "reason": v.reason if v.material else "", "status": v.status, "source": "feeds"}
            try:
                NewsItem.model_validate(item)
                items.append(item)
            except ValueError as err:
                problems.append(f"{slug}: {e['title'][:60]}: {str(err).splitlines()[0][:120]}")
    return items, problems

