"""The scout: collect → screen → classify → score → re-rank → keep the queue at N topics.

    editorial scout                 # live sources
    editorial scout --fixtures      # recorded responses in fixtures/sources/ (tests, CI, offline demo)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import guard, rank, telemetry
from .config import ROOT, settings, site_url
from .llm import BudgetExceeded, Classifier
from .sources import Getter, collect, http_get
from .store import OPEN, Store

FIXTURES = ROOT / "fixtures"
FIXTURE_NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)   # the fixtures' "today", so they never age out


def fixture_getter(base: Path = FIXTURES / "sources") -> Getter:
    """Serve recorded responses by URL pattern; anything unknown raises like a dead source would."""
    table = [("daily_papers", "hf_papers.json"), ("api/models", "hf_models.json"), ("export.arxiv.org", "arxiv.xml"),
             ("hn.algolia.com", "hn.json"), ("access_token", "reddit_token.json"), ("oauth.reddit.com", "reddit.json"),
             ("huggingface.co/blog/feed", "rss_hf_blog.xml"), ("technologyreview", "rss_techreview.xml")]

    def get(url: str, **_kw) -> str:
        for needle, name in table:
            if needle in url:
                return (base / name).read_text()
        raise ConnectionError(f"no fixture for {url}")
    return get


def published_texts(source: str | None = None) -> list[str]:
    """Titles, short titles and topics of every published post, from the site's assistant/corpus.json."""
    src = source or os.getenv("EDITORIAL_CORPUS") or (site_url() + "/assistant/corpus.json" if site_url() else "")
    if not src:
        src = str(FIXTURES / "corpus.json")
    if src.startswith("http"):
        from .sources import http_get as get
        corpus = json.loads(get(src))
    else:
        corpus = json.loads(Path(src).read_text())
    pages = corpus.get("pages", {})
    return [f"{p.get('title', '')}. {p.get('short', '')}. {p.get('topics', '')} {p.get('intro', '')}"
            for p in pages.values()]


def run(store: Store, get: Getter = http_get, corpus: str | None = None, classifier: Classifier | None = None,
        now: datetime | None = None) -> dict:
    telemetry.require_enabled("scout", actor="service:scout")
    t0 = time.time()
    s = settings()
    now = now or datetime.now(timezone.utc)
    cands, health = collect(get)

    new = escalated = 0
    for c in cands:
        hits = guard.scan(c["title"], c.get("summary", ""))
        if hits:
            c["flags"] = ["injection"]
        if store.upsert_candidate(c):
            new += 1
            if hits:
                store.set_status(c["id"], "escalated", flags=["injection"])
                escalated += 1

    cutoff = (now - timedelta(days=s["queue"]["max_age_days"])).isoformat()
    for t in store.topics(("candidate", "queued")):
        if (t.get("published") or t["fetched_at"]) < cutoff:
            store.set_status(t["id"], "expired", rank=None)

    clf = classifier or Classifier()
    budget_hit, fallbacks, model = False, 0, clf.name
    for t in store.topics(OPEN):
        if t.get("analysis"):
            continue
        try:
            r = clf.classify(t)
        except BudgetExceeded:
            budget_hit = True
            break
        fallbacks += r.fallback
        model = r.model
        store.set_fields(t["id"], analysis={**r.data, "model": r.model, "prompt_hash": r.prompt_hash,
                                            "fallback": r.fallback})

    queue, picked, similar = rerank(store, corpus, now)

    summary = {"candidates": len(cands), "new": new, "escalated": escalated, "queue": len(queue),
               "picked": len(picked), "too_similar": len(similar), "classifier_calls": clf.calls,
               "fallbacks": fallbacks, "budget_hit": budget_hit, "sources": health}
    store.run("scout", "ok", summary)
    flags = (["injection"] if escalated else []) + (["budget_stop"] if budget_hit else []) + \
        (["fallback"] if fallbacks else [])
    telemetry.record("scout", actor="service:scout", model=model, latency_ms=int((time.time() - t0) * 1000),
                     rows_in=len(cands), items=len(queue), flags=flags,
                     detail={k: v for k, v in summary.items() if k != "sources"})
    return summary


def rerank(store: Store, corpus: str | None = None, now: datetime | None = None) -> tuple[list, list, list]:
    """Score every open, classified topic and refill the queue to N. Runs after each scout and after the owner
    picks or dismisses, so the queue is always full without waiting for the next fetch."""
    s = settings()
    pool = [t for t in store.topics(OPEN) if t.get("analysis")]
    pub = published_texts(corpus)
    scores = rank.score(pool, pub, s["queue"]["weights"], now)
    for t in pool:
        store.set_fields(t["id"], scores=scores[t["id"]])
    picked = sorted([t for t in pool if t["status"] == "picked"], key=lambda t: -scores[t["id"]]["score"])
    others = [t for t in pool if t["status"] != "picked"]
    queue, similar = rank.select(others, scores, s["queue"]["size"], s["queue"]["mmr_lambda"],
                                 s["queue"]["max_similarity"], pinned=picked, published=pub)
    queued_ids = {t["id"] for t in queue}
    for i, t in enumerate(queue, 1):
        store.set_fields(t["id"], rank=i)
        if t["status"] != "picked":
            store.set_status(t["id"], "queued")
    for t in others:
        if t["id"] not in queued_ids:
            too_close = scores[t["id"]]["closest_post_similarity"] > s["queue"]["max_similarity"]
            store.set_status(t["id"], "similar" if too_close else "candidate", rank=None)

    return queue, picked, similar
