"""Ranking: predicted engagement, novelty and sector breadth, then a diversity re-rank (MMR) so the queue stays varied.

All numbers come from code. The model's only input is its 1-5 interest rating, one part of engagement.

  engagement    = 0.6 × source-signal percentile (within its own source, so 300 Reddit upvotes and 300 HN points
                  aren't compared directly) + 0.25 × interest/5 + 0.15 × recency (halves every 7 days)
  novelty       = 1 − highest similarity to any published post on the site
  breadth       = number of sectors it applies to, capped at 4, ÷ 4
  score         = weighted sum (settings: queue.weights)
  queue         = picked topics, then MMR: repeatedly take the topic with the best
                  λ × score − (1 − λ) × similarity-to-what's-already-in, skipping anything above queue.max_similarity
"""
from __future__ import annotations

from datetime import datetime, timezone

from .textsim import Space, cosine, max_sim

SIGNAL_KEYS = ("upvotes", "points", "likes", "trending", "comments")


def _signal(t: dict) -> float:
    s = t.get("signals") or {}
    return sum(float(s.get(k, 0) or 0) * (0.5 if k == "comments" else 1.0) for k in SIGNAL_KEYS)


def _percentiles(topics: list[dict]) -> dict[str, float]:
    by_source: dict[str, list[dict]] = {}
    for t in topics:
        by_source.setdefault(t["source"], []).append(t)
    out = {}
    for group in by_source.values():
        vals = sorted(_signal(t) for t in group)
        n = len(vals)
        for t in group:
            v = _signal(t)
            out[t["id"]] = 0.5 if n == 1 or vals[-1] == vals[0] else sum(x <= v for x in vals) / n
    return out


def recency(published: str, now: datetime | None = None) -> float:
    if not published:
        return 0.5
    now = now or datetime.now(timezone.utc)
    try:
        age = (now - datetime.fromisoformat(published)).total_seconds() / 86400
    except ValueError:
        return 0.5
    return 0.5 ** (max(0.0, age) / 7)


def text_of(t: dict) -> str:
    a = t.get("analysis") or {}
    return f"{t['title']}. {a.get('summary', '')} {t.get('summary', '')[:400]}"


def score(topics: list[dict], published: list[str], weights: dict, now: datetime | None = None) -> dict[str, dict]:
    """Scores for every topic: {id: {engagement, novelty, breadth, score, closest_post_similarity}}."""
    space = Space(published + [text_of(t) for t in topics])
    pubv = [space.vec(p) for p in published]
    pct = _percentiles(topics)
    out = {}
    for t in topics:
        a = t.get("analysis") or {}
        eng = 0.6 * pct[t["id"]] + 0.25 * (a.get("interest", 3) / 5) + 0.15 * recency(t.get("published", ""), now)
        sim = max_sim(space.vec(text_of(t)), pubv)
        breadth = min(len(a.get("sectors") or []), 4) / 4
        s = weights["engagement"] * eng + weights["novelty"] * (1 - sim) + weights["sector_breadth"] * breadth
        out[t["id"]] = {"engagement": round(eng, 3), "novelty": round(1 - sim, 3), "breadth": round(breadth, 3),
                        "score": round(s, 4), "closest_post_similarity": round(sim, 3)}
    return out


def select(topics: list[dict], scores: dict[str, dict], size: int, lam: float, max_similarity: float,
           pinned: list[dict] | None = None, published: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """MMR re-rank. Returns (queue in order, rejected-as-too-similar). Pinned (picked) topics stay and count as
    already selected, so new picks must differ from them too."""
    pinned = pinned or []
    space = Space((published or []) + [text_of(t) for t in topics + pinned])
    vec = {t["id"]: space.vec(text_of(t)) for t in topics + pinned}
    chosen = list(pinned)
    similar = []
    pool = [t for t in topics if scores[t["id"]]["closest_post_similarity"] <= max_similarity]
    similar += [t for t in topics if scores[t["id"]]["closest_post_similarity"] > max_similarity]
    while pool and len(chosen) < size:
        best, best_val = None, -1e9
        for t in pool:
            red = max((cosine(vec[t["id"]], vec[c["id"]]) for c in chosen), default=0.0)
            val = lam * scores[t["id"]]["score"] - (1 - lam) * red
            if val > best_val:
                best, best_val = t, val
        pool.remove(best)
        red = max((cosine(vec[best["id"]], vec[c["id"]]) for c in chosen), default=0.0)
        if red > max_similarity:
            similar.append(best)
            continue
        chosen.append(best)
    return chosen, similar
