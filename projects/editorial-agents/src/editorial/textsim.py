"""Novelty without a model: TF-IDF vectors and cosine similarity, standard library only.

Good enough to spot "this is about the same thing" between short texts (titles + summaries vs. post titles +
intros), deterministic, and testable offline. Embeddings would catch paraphrases better; that's a documented option.
"""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an the and or of to in on for with by from at as is are was were be been being it its this that these
those we you they he she i our your their his her not no can could will would should may might do does did done has
have had into about over under than then so such via using use used new how what why when which who whom more most
also just only very up out if but all any each other some""".split())


def tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z][a-z0-9\-]+", (text or "").lower()) if w not in STOP and len(w) > 2]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]      # bigrams catch "supply chain", "kill switch"


class Space:
    """IDF fitted on a reference collection (published posts + candidates), so common words weigh little."""

    def __init__(self, docs: list[str]):
        self.n = max(1, len(docs))
        df = Counter()
        for d in docs:
            df.update(set(tokens(d)))
        self.idf = {t: math.log((1 + self.n) / (1 + c)) + 1 for t, c in df.items()}

    def vec(self, text: str) -> dict[str, float]:
        tf = Counter(tokens(text))
        v = {t: c * self.idf.get(t, math.log(1 + self.n) + 1) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def max_sim(v: dict[str, float], others: list[dict[str, float]]) -> float:
    return max((cosine(v, o) for o in others), default=0.0)
