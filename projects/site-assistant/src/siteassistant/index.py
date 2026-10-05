"""The blog as searchable passages, read from the site's own search index.

MkDocs Material publishes search/search_index.json with every page split into sections. Reading that (by URL from
the live site, or a file from a local build) means the assistant always matches what's published — new posts and
technology pages are searchable within `refresh_minutes`, with no build step coupling the two.

The site build also publishes assistant/corpus.json (scripts/assistant_corpus.py in the portfolio repo):
  - a profile card about Ruairi, regenerated from the posts on every build (background, MIT coursework, evidence by
    topic, technologies by project, newest work first). It goes into every prompt, so questions about him always
    have it, and it's the same text every time, so Ollama can reuse its cached prefix;
  - each post's date and type, so excerpts carry dates and the model can say what's recent;
  - public text that isn't on the site: project READMEs and docs on GitHub, the governance controls, coursework
    READMEs and notebook commentary, and the resume.
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


def corpus_source_for(source: str) -> str:
    """assistant/corpus.json sits next to search/search_index.json, on the live site and in a local build."""
    if re.match(r"^https?://", source):
        return re.sub(r"search/search_index\.json$", "assistant/corpus.json", source)
    return str(Path(source).resolve().parent.parent / "assistant" / "corpus.json")


def corpus_passages(corpus: dict, max_words: int = 180) -> list[dict]:
    out = []
    for d in corpus.get("docs", []):
        words = (d.get("text") or "").split()
        for i in range(0, len(words), max_words):
            out.append({"url": d["url"], "page_title": d.get("title", ""), "section": d.get("section", ""),
                        "text": " ".join(words[i:i + max_words])})
    return out


def refresh(store: Store, source: str, site_url: str, min_words: int = 8, corpus_source: str | None = None) -> int:
    try:
        rows = passages_from(load_source(source), site_url, min_words)
        if not rows:
            raise ValueError("the site index had no usable passages")
    except Exception as e:  # noqa: BLE001 — keep serving the last good index
        store.index_failed(source, f"{type(e).__name__}: {e}")
        raise
    csrc = corpus_source or corpus_source_for(source)
    try:                    # the corpus is extra: without it the assistant still answers from the site
        corpus = load_source(csrc)
        rows += corpus_passages(corpus)
        store.set_kv("profile", {"text": corpus.get("profile", ""), "url": corpus.get("profile_url", ""),
                                 "generated": corpus.get("generated", "")})
        store.set_kv("pages", corpus.get("pages", {}))
        store.set_kv("audiences", corpus.get("audiences", []))
    except Exception as e:  # noqa: BLE001
        print(f"assistant corpus not loaded from {csrc}: {type(e).__name__}: {e}")
    return store.replace_passages(rows, source)


def fts_query(q: str) -> str:
    """Free text → an FTS5 query: meaningful words, prefix-matched, OR'd (bm25 ranks the best matches first)."""
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in STOP and len(w) > 1]   # scikit-learn → scikit, learn
    return " OR ".join(f'"{w}"*' for w in dict.fromkeys(w for w in words if w))[:500]


OFFSITE_WEIGHT = 0.7   # repo docs and the resume rank a little below the site's own pages for the same match


def search(store: Store, q: str, limit: int = 8, site_url: str = "", site_first: bool = False) -> list[dict]:
    """Best passages for q. With site_url, repo docs and the resume rank a little lower; with site_first (the Search
    button: a list of pages to read), every page on the site comes before anything from GitHub."""
    fq = fts_query(q)
    if not fq:
        return []
    rows = store.query(
        """select p.pid, p.url, p.page_title, p.section, p.text,
                  snippet(passages_fts, 2, '<mark>', '</mark>', ' … ', 28) as snippet,
                  bm25(passages_fts, 3.0, 2.0, 1.0) as score
           from passages_fts join passages p on p.pid = passages_fts.rowid
           where passages_fts match ? order by score limit ?""", (fq, limit * 4))
    if site_url:            # bm25 is negative (lower = better): shrinking it pushes off-site passages down
        for r in rows:
            if not r["url"].startswith(site_url.rstrip("/") + "/"):
                r["score"] *= OFFSITE_WEIGHT
        rows.sort(key=lambda r: r["score"])
        if site_first:
            rows.sort(key=lambda r: not r["url"].startswith(site_url.rstrip("/") + "/"))   # stable: keeps bm25 order
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


# Questions about the person ("would Ruairi be good for a PM role…", "what's his background") always get the profile
# card, and the words that only say "is he a fit" are dropped from the search so the role's own words drive it.
PERSON = re.compile(r"\b(ruair\w*|rory|powers?|poers|he|him|his|candidate|hire|hiring|role|fit|background|experience|"
                    r"resume|cv|career|qualif\w*|suitable|good for|skills?|know|knows|can he|has he|does he)\b", re.I)
FIT_WORDS = re.compile(r"\b(would|could|be|a|an|good|great|fit|for|role|position|job|candidate|hire|hiring|suitable|"
                       r"ruair\w*|rory|powers?|poers|he|him|his|have|has|does|do|is|any|experience|with|in|about|"
                       r"tell|me|skills?|know|knows|qualified|qualifications?|projects?)\b", re.I)


def is_about_person(question: str) -> bool:
    return bool(PERSON.search(question))


def profile_passage(store: Store, site_url: str) -> dict | None:
    """The profile card as excerpt [1] (always the same text, so the model's prompt prefix is cacheable)."""
    prof = store.get_kv("profile") or {}
    if not prof.get("text"):
        return None
    return {"pid": -1, "url": prof.get("url") or f"{site_url.rstrip('/')}/about/", "page_title": "Profile and evidence",
            "section": f"generated {prof.get('generated', '')}", "text": prof["text"], "snippet": "", "score": 0,
            "profile": True}


def with_dates(store: Store, rows: list[dict], site_url: str) -> list[dict]:
    """Attach each post's date and type, so the model can tell what's recent."""
    pages = store.get_kv("pages", {}) or {}
    base = site_url.rstrip("/") + "/"
    for r in rows:
        path = r["url"].split("#")[0].removeprefix(base)
        meta = pages.get(path)
        if meta:
            r["date"], r["kind"] = meta.get("date", ""), meta.get("kind", "")
    return rows


def context_for(store: Store, question: str, site_url: str, top_k: int) -> list[dict]:
    """Passages for the model: the profile card first, then the best matches (dated when they're posts).
    For questions about Ruairi, the search uses the role's own words ("LLM features", "product management")."""
    q = question
    if is_about_person(question):
        stripped = FIT_WORDS.sub(" ", question)
        if fts_query(stripped):
            q = stripped
    card = profile_passage(store, site_url)
    hits = search(store, q, top_k + 2, site_url)
    if card:                    # the About page's evidence tables are the card itself: don't spend slots on them
        hits = [h for h in hits if h["url"] != card["url"]]
    if is_about_person(question):   # the resume has the detail the card summarises: always offer its best passage
        resume = [r for r in search(store, q + " resume experience", 20, site_url) if "resume" in r["url"].lower()][:1]
        hits = resume + [h for h in hits if h["pid"] not in {r["pid"] for r in resume}]
    return ([card] if card else []) + with_dates(store, hits[:top_k], site_url)


# Job-ad boilerplate that says nothing about the work, so it shouldn't steer the search for evidence.
ROLE_NOISE = set("about benefits company competitive culture equal employer environment opportunity opportunities "
                 "salary team teams join looking candidate candidates ideal including include strong excellent ability "
                 "abilities work working years year plus preferred required requirements responsibilities "
                 "qualifications role position job apply applicants must will would should also within across using "
                 "other new".split())


def role_keywords(role: str, description: str, n: int = 24) -> str:
    """The role's distinctive words, most frequent first, title words always included: a long job ad becomes a
    search query that FTS can rank (a raw 8,000-character ad would be truncated to its first few words)."""
    from collections import Counter
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9+#.-]*[a-z0-9+#]|[a-z0-9]", description.lower())
             if w not in STOP and w not in ROLE_NOISE and len(w) > 2 and not w.isdigit()]
    title = [w for w in re.findall(r"[a-z0-9]+", role.lower()) if w not in STOP and len(w) > 1]
    top = [w for w, _ in Counter(words).most_common(n)]
    return " ".join(dict.fromkeys(title + top))


LISTINGS = ("", "tour/", "blog/", "personal/", "classes/", "release-notes/")


def _listing(url: str, site_url: str) -> bool:
    """Pages that only list or summarise other pages: evidence should cite the work itself, not a summary of it."""
    base = site_url.rstrip("/") + "/"
    return url.startswith(base) and url.split("#")[0][len(base):] in LISTINGS


BULLET = re.compile(r"^\s*([-*•·▪◦]|\d+[.)])\s+")


def requirements(description: str, limit: int = 8) -> list[str]:
    """The role's own requirement lines: its bullets when it has them, else its sentences."""
    raw = description.splitlines()
    bullets = [BULLET.sub("", ln).strip() for ln in raw if BULLET.match(ln)]
    lines = [b for b in bullets if 3 <= len(b.split()) <= 40]
    if len(lines) < 2:
        text = " ".join(BULLET.sub("", ln).strip() for ln in raw)
        lines = [x.strip() for x in re.split(r"(?<=[.!?;])\s+", text) if 4 <= len(x.split()) <= 40 and not x.endswith(":")]
    return list(dict.fromkeys(lines))[:limit]


def role_context(store: Store, role: str, description: str, site_url: str, top_k: int) -> list[dict]:
    """Evidence for a role: the profile card, the resume's best passage, then the best match for EACH requirement
    (so every requirement gets looked for, not just the ad's most frequent words), then the best overall matches."""
    q = role_keywords(role, description)
    card = profile_passage(store, site_url)
    ok = lambda h: not _listing(h["url"], site_url) and not (card and h["url"] == card["url"])     # noqa: E731
    resume = [r for r in search(store, q + " resume experience", 30, site_url) if "resume" in r["url"].lower()][:1]
    picked = list(resume)
    for req in requirements(description):
        for h in [h for h in search(store, req, 6, site_url) if ok(h)][:2]:
            picked.append(h)
    picked += [h for h in search(store, q, top_k + 8, site_url) if ok(h)]
    seen, out = set(), []
    for h in picked:
        if h["pid"] not in seen:
            seen.add(h["pid"])
            out.append(h)
    return ([card] if card else []) + with_dates(store, out[:top_k], site_url)
