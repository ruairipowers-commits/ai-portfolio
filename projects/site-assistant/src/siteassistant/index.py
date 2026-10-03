"""The blog as searchable passages, read from the site's own search index.

MkDocs Material publishes search/search_index.json with every page split into sections. Reading that (by URL from
the live site, or a file from a local build) means the assistant always matches what's published — new posts and
technology pages are searchable within `refresh_minutes`, with no build step coupling the two.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import httpx

from .store import Store

STOP = set("a an and are as at be but by can do does for from how i in is it its me my of on or so that the this "
           "to was what when where which who why will with you your".split())


def _clean(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def load_source(source: str) -> dict:
    if re.match(r"^https?://", source):
        r = httpx.get(source, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    return json.loads(Path(source).read_text())


def passages_from(index: dict, site_url: str, min_words: int = 8, max_words: int = 180) -> list[dict]:
    """Material's index → passages of ≤ max_words, each with its page title, section title and absolute URL."""
    docs = index.get("docs", [])
    titles = {d["location"]: _clean(d.get("title", "")) for d in docs if "#" not in d["location"]}
    out = []
    for d in docs:
        loc = d["location"]
        page = loc.split("#")[0]
        if page.startswith(("search/", "404")) or "/page/" in page or page.endswith(("tags/", "archive/")):
            continue
        text = _clean(d.get("text", ""))
        words = text.split()
        if len(words) < min_words:
            continue
        section = _clean(d.get("title", "")) if "#" in loc else ""
        for i in range(0, len(words), max_words):
            out.append({"url": f"{site_url.rstrip('/')}/{loc}", "page_title": titles.get(page, section or page),
                        "section": section, "text": " ".join(words[i:i + max_words])})
    return out


def refresh(store: Store, source: str, site_url: str, min_words: int = 8) -> int:
    try:
        rows = passages_from(load_source(source), site_url, min_words)
        if not rows:
            raise ValueError("the site index had no usable passages")
        return store.replace_passages(rows, source)
    except Exception as e:  # noqa: BLE001 — keep serving the last good index
        store.index_failed(source, f"{type(e).__name__}: {e}")
        raise


def fts_query(q: str) -> str:
    """Free text → an FTS5 query: meaningful words, prefix-matched, OR'd (bm25 ranks the best matches first)."""
    words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*", q.lower()) if w not in STOP and len(w) > 1]
    words = [re.sub(r"[^a-z0-9]", "", w) for w in words]
    return " OR ".join(f'"{w}"*' for w in dict.fromkeys(w for w in words if w))[:500]


def search(store: Store, q: str, limit: int = 8) -> list[dict]:
    fq = fts_query(q)
    if not fq:
        return []
    rows = store.query(
        """select p.pid, p.url, p.page_title, p.section, p.text,
                  snippet(passages_fts, 2, '<mark>', '</mark>', ' … ', 28) as snippet,
                  bm25(passages_fts, 3.0, 2.0, 1.0) as score
           from passages_fts join passages p on p.pid = passages_fts.rowid
           where passages_fts match ? order by score limit ?""", (fq, limit * 3))
    seen, out = set(), []
    for r in rows:   # at most two passages per page, so one long post doesn't fill the list
        page = r["url"].split("#")[0]
        if sum(1 for o in out if o["url"].split("#")[0] == page) >= 2 or r["pid"] in seen:
            continue
        seen.add(r["pid"])
        out.append(r)
        if len(out) >= limit:
            break
    return out


# Questions about the person ("would Ruairi be good for a PM role…", "what's his background") need his profile
# in the context even when the wording (or a misspelt name) doesn't match it.
PERSON = __import__("re").compile(r"\b(ruair\w*|rory|powers?|poers|he|him|his|candidate|hire|hiring|role|fit|"
                                  r"background|experience|resume|cv|career|qualif\w*|suitable|good for)\b", __import__("re").I)
PROFILE_PAGES = ("about/", "")      # the About page and the home page intro


def profile_passages(store: Store, site_url: str, limit: int = 3) -> list[dict]:
    base = site_url.rstrip("/") + "/"
    rows = []
    for page in PROFILE_PAGES:
        rows += store.query("select pid, url, page_title, section, text, '' as snippet, 0 as score from passages "
                            "where url = ? or url like ? order by pid limit 2", (base + page, base + page + "#%"))
    return rows[:limit]


def context_for(store: Store, question: str, site_url: str, top_k: int) -> list[dict]:
    """Passages for the model: the best matches, plus the profile when the question is about Ruairi."""
    hits = search(store, question, top_k)
    if PERSON.search(question):
        prof = profile_passages(store, site_url)          # the About page first, then the best other matches
        ids = {p["pid"] for p in prof}
        hits = prof + [h for h in hits if h["pid"] not in ids][: max(top_k - len(prof), 2)]
    return hits
