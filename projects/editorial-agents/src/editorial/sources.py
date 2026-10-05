"""Where candidate topics come from: official APIs and public feeds only (DATA-04).

Each source is a fetch (network) plus a parse (pure function), so tests run the parsers on fixture files and never
touch the network. Every candidate keeps its link, a short summary, a date and the source's own engagement signals
(upvotes, points, comments, likes), which the ranker turns into a comparable score. LinkedIn is deliberately absent:
it has no public search API and its terms prohibit scraping.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote, urlsplit, urlunsplit

from .config import feeds, settings

Getter = Callable[..., str]


def canonical(url: str) -> str:
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme or "https", p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", ""))


def topic_id(url: str) -> str:
    return hashlib.sha1(canonical(url).encode()).hexdigest()[:16]


def clean(text: str | None, limit: int = 600) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return " ".join(text.split())[:limit]


def _iso(value) -> str:
    if not value:
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(
            timespec="seconds")
    except ValueError:
        return ""


def cand(source: str, title: str, url: str, summary: str = "", published="", **signals) -> dict:
    return {"id": topic_id(url), "source": source, "title": clean(title, 300), "url": url, "summary": clean(summary),
            "published": _iso(published), "signals": {k: v for k, v in signals.items() if v is not None}}


# ---------------------------------------------------------------- parsers (pure)
def parse_hf_papers(text: str) -> list[dict]:
    out = []
    for item in json.loads(text):
        p = item.get("paper", item)
        pid = p.get("id", "")
        if not pid or not p.get("title"):
            continue
        out.append(cand("huggingface_papers", p["title"], f"https://huggingface.co/papers/{pid}", p.get("summary", ""),
                        item.get("publishedAt") or p.get("publishedAt"), upvotes=p.get("upvotes", 0),
                        comments=item.get("numComments", 0)))
    return out


def parse_hf_models(text: str) -> list[dict]:
    out = []
    for m in json.loads(text):
        mid = m.get("id") or m.get("modelId")
        if not mid:
            continue
        task = m.get("pipeline_tag") or "model"
        out.append(cand("huggingface_trending", f"{mid} ({task})", f"https://huggingface.co/{mid}",
                        f"Trending {task} model on Hugging Face: {mid}.", m.get("createdAt") or m.get("lastModified"),
                        likes=m.get("likes", 0), trending=m.get("trendingScore", 0)))
    return out


ATOM = "{http://www.w3.org/2005/Atom}"


def parse_arxiv(text: str) -> list[dict]:
    root = ET.fromstring(text)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        link = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel") == "alternate"), None) \
            or (e.findtext(f"{ATOM}id") or "")
        out.append(cand("arxiv", e.findtext(f"{ATOM}title") or "", link.replace("http://", "https://"),
                        e.findtext(f"{ATOM}summary") or "", e.findtext(f"{ATOM}published")))
    return out


def parse_hn(text: str) -> list[dict]:
    out = []
    for h in json.loads(text).get("hits", []):
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append(cand("hacker_news", h.get("title") or "", url, h.get("story_text") or "", h.get("created_at"),
                        points=h.get("points", 0), comments=h.get("num_comments", 0),
                        discussion=f"https://news.ycombinator.com/item?id={h.get('objectID')}"))
    return out


def parse_reddit(text: str) -> list[dict]:
    out = []
    for child in json.loads(text).get("data", {}).get("children", []):
        d = child.get("data", {})
        if d.get("stickied") or d.get("over_18"):
            continue
        link = "https://www.reddit.com" + d.get("permalink", "")
        out.append(cand("reddit", d.get("title", ""), link, d.get("selftext", ""), d.get("created_utc"),
                        upvotes=d.get("score", 0), comments=d.get("num_comments", 0),
                        subreddit=d.get("subreddit", "")))
    return out


def parse_rss(text: str, name: str = "rss") -> list[dict]:
    root = ET.fromstring(text)
    out = []
    items = root.findall(".//item")
    if items:                                             # RSS 2.0
        for i in items:
            out.append(cand("rss", i.findtext("title") or "", (i.findtext("link") or "").strip(),
                            i.findtext("description") or "", i.findtext("pubDate"), feed=name))
    else:                                                 # Atom
        for e in root.findall(f"{ATOM}entry"):
            link = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), "")
            out.append(cand("rss", e.findtext(f"{ATOM}title") or "", link,
                            e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content") or "",
                            e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated"), feed=name))
    return [c for c in out if c["url"].startswith("http")]


# ---------------------------------------------------------------- fetch (network)
def http_get(url: str, headers: dict | None = None, data: dict | None = None, auth=None) -> str:
    import httpx
    s = settings()["sources"]
    h = {"User-Agent": s["user_agent"], **(headers or {})}
    with httpx.Client(timeout=s["timeout_s"], follow_redirects=True) as c:
        r = c.post(url, data=data, headers=h, auth=auth) if data is not None else c.get(url, headers=h)
        r.raise_for_status()
        return r.text


def _reddit_token(get: Getter) -> str | None:
    cid, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    body = get("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
               auth=(cid, secret))
    return json.loads(body).get("access_token")


def collect(get: Getter = http_get) -> tuple[list[dict], dict]:
    """Fetch every enabled source. Returns (candidates, health) — health says per source: ok n / skipped / error."""
    s = settings()["sources"]
    out: list[dict] = []
    health: dict[str, str] = {}

    def run(name: str, fn):
        try:
            got = fn()
            out.extend(got)
            health[name] = f"ok {len(got)}"
        except Exception as e:  # noqa: BLE001 — one dead source must not stop the others
            health[name] = f"error {type(e).__name__}"

    if s["huggingface_papers"]["enabled"]:
        run("huggingface_papers", lambda: parse_hf_papers(get(s["huggingface_papers"]["url"]))[: s["huggingface_papers"]["limit"]])
    if s["huggingface_trending"]["enabled"]:
        run("huggingface_trending", lambda: parse_hf_models(get(s["huggingface_trending"]["url"])))
    if s["arxiv"]["enabled"]:
        q = "+OR+".join(f"cat:{c}" for c in s["arxiv"]["categories"])
        run("arxiv", lambda: parse_arxiv(get(f"https://export.arxiv.org/api/query?search_query={q}"
                                             f"&sortBy=submittedDate&sortOrder=descending&max_results={s['arxiv']['limit']}")))
    if s["hacker_news"]["enabled"]:
        since = int(time.time()) - 7 * 86400
        for q in s["hacker_news"]["queries"]:
            run(f"hacker_news:{q}", lambda q=q: parse_hn(get(
                f"https://hn.algolia.com/api/v1/search?tags=story&query={quote(q)}"
                f"&numericFilters=created_at_i>{since},points>{s['hacker_news']['min_points']}")))
    if s["reddit"]["enabled"]:
        try:
            token = _reddit_token(get)
        except Exception as e:  # noqa: BLE001
            token, health["reddit"] = None, f"error {type(e).__name__}"
        if token:
            for sub in s["reddit"]["subreddits"]:
                run(f"reddit:{sub}", lambda sub=sub: parse_reddit(get(
                    f"https://oauth.reddit.com/r/{sub}/top?t=week&limit={s['reddit']['limit']}",
                    headers={"Authorization": f"bearer {token}"})))
        else:
            health.setdefault("reddit", "skipped (no REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)")
    if s["rss"]["enabled"]:
        for f in feeds():
            run(f"rss:{f['name']}", lambda f=f: parse_rss(get(f["url"]), f["name"]))
    return dedupe(out), health


def dedupe(cands: list[dict]) -> list[dict]:
    """One candidate per canonical URL, and per near-identical title (the same paper on HN and arXiv)."""
    seen_ids, seen_titles, out = set(), set(), []
    for c in cands:
        key = re.sub(r"[^a-z0-9]+", " ", c["title"].lower()).strip()[:80]
        if c["id"] in seen_ids or (key and key in seen_titles):
            continue
        seen_ids.add(c["id"])
        seen_titles.add(key)
        out.append(c)
    return out
