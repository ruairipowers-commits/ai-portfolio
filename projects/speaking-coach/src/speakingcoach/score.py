"""Every number in the report comes from here, by code. A model never sets a count, a rate or a grade (NFR-1)."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from .detect import Hit, counted
from .text import sentences, tokenize


@dataclass
class Cluster:
    start: int
    end: int
    hits: int
    position: str
    excerpt: str
    at_seconds: float | None = None


@dataclass
class Timing:
    speaking_seconds: float
    words_per_minute: float
    pauses: int                 # silences ≥ long_pause_seconds inside a turn: good — pausing beats filling
    in_band: bool


@dataclass
class Score:
    words: int
    fillers: int
    weighted: float
    rate_per_100: float
    target_per_100: float
    grade: str
    by_category: dict[str, int]
    top: list[tuple[str, int]]
    top_by_category: dict[str, list[tuple[str, int]]]
    by_position: dict[str, int]
    clusters: list[Cluster]
    long_sentences: int
    longest_sentence_words: int
    repetitions: int
    disputed: int
    not_counted: int
    timing: Timing | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["top"] = [list(t) for t in self.top]
        d["top_by_category"] = {c: [list(t) for t in v] for c, v in self.top_by_category.items()}
        return d


def grade_for(rate: float, bands: dict[str, float]) -> str:
    for g, limit in sorted(bands.items(), key=lambda kv: kv[1]):
        if rate <= limit:
            return g
    return "F"


def _position(word_index: int, words: int) -> str:
    if words == 0:
        return "opening"
    third = word_index / max(words, 1)
    return "opening" if third < 1 / 3 else "middle" if third < 2 / 3 else "close"


def score(text: str, hits: list[Hit], thresholds: dict, spans: list | None = None) -> Score:
    toks = tokenize(text)
    words = len(toks)
    live = counted(hits)
    weighted = sum(h.weight for h in live)
    rate = round(weighted / words * 100, 2) if words else 0.0
    by_cat = Counter(h.category for h in live)
    top = Counter(h.entry.lower() for h in live).most_common(5)
    by_pos = Counter(_position(h.token_index, words) for h in live)
    clusters = _clusters(text, toks, live, thresholds, spans)
    sents = sentences(text, toks)
    lengths = [b - a + 1 for _, _, a, b in sents]
    long_limit = thresholds.get("long_sentence_words", 35)
    s = Score(words=words, fillers=len(live), weighted=round(weighted, 2), rate_per_100=rate,
              target_per_100=float(thresholds.get("target_per_100_words", 2.0)),
              grade=grade_for(rate, thresholds.get("grade_bands", {"A": 1, "B": 2, "C": 3.5, "D": 5})),
              by_category=dict(by_cat), top=top,
              top_by_category={c: Counter(h.entry.lower() for h in live if h.category == c).most_common(3)
                               for c in by_cat}, by_position={p: by_pos.get(p, 0) for p in ("opening", "middle", "close")},
              clusters=clusters, long_sentences=sum(1 for n in lengths if n > long_limit),
              longest_sentence_words=max(lengths, default=0),
              repetitions=sum(1 for h in live if h.entry == "repetition"),
              disputed=sum(1 for h in hits if h.verdict in ("disputed", "ambiguous")),
              not_counted=sum(1 for h in hits if h.verdict == "not_filler"))
    if spans and any(sp[2].start is not None for sp in spans):
        s.timing = _timing(text, spans, words, thresholds)
    if words and len(sents) <= 1 and words > 120:
        s.notes.append("no sentence punctuation found: openers, closers and long-sentence counts are less reliable")
    return s


def _clusters(text, toks, live, thresholds, spans) -> list[Cluster]:
    window = int(thresholds.get("cluster_window_words", 30))
    need = int(thresholds.get("cluster_min_hits", 3))
    idx = sorted(h.token_index for h in live)
    groups: list[list[int]] = []
    for k in range(len(idx)):
        j = k
        while j + 1 < len(idx) and idx[j + 1] - idx[k] < window:
            j += 1
        if j - k + 1 >= need:
            g = idx[k:j + 1]
            if groups and g[0] <= groups[-1][-1]:
                groups[-1] = sorted(set(groups[-1]) | set(g))
            else:
                groups.append(g)
    out = []
    for g in groups:
        a, b = toks[max(g[0], 0)], toks[min(g[-1], len(toks) - 1)]
        out.append(Cluster(a.start, b.end, len(g), _position(g[0], len(toks)), text[a.start:b.end][:220],
                           _time_at(a.start, spans)))
    return out


def _time_at(char: int, spans) -> float | None:
    for a, b, seg, _ in spans or []:
        if a <= char <= b and seg.start is not None:
            frac = (char - a) / max(b - a, 1)
            return round(seg.start + frac * ((seg.end or seg.start) - seg.start), 1)
    return None


def _timing(text, spans, words, thresholds) -> Timing:
    secs = sum(max(0.0, (sp[2].end or 0) - (sp[2].start or 0)) for sp in spans if sp[2].start is not None)
    pause_min = float(thresholds.get("long_pause_seconds", 1.0))
    pauses = 0
    for prev, cur in zip(spans, spans[1:]):
        if not cur[3] and prev[2].end is not None and cur[2].start is not None:
            gap = cur[2].start - prev[2].end
            if gap >= pause_min:
                pauses += 1
            secs += max(gap, 0.0)               # silence inside your own turn is part of your speaking time
    wpm = round(words / (secs / 60), 1) if secs else 0.0
    lo, hi = thresholds.get("wpm_band", [130, 170])
    return Timing(round(secs, 1), wpm, pauses, lo <= wpm <= hi)


def worst_passages(text: str, hits: list[Hit], n: int) -> list[dict]:
    """The n sentences carrying the most filler weight (ties: earlier first)."""
    toks = tokenize(text)
    live = counted(hits)
    ranked = []
    for a_char, b_char, a, b in sentences(text, toks):
        inside = [h for h in live if a_char <= h.start < b_char]
        if inside:
            ranked.append((-sum(h.weight for h in inside), a_char, b_char, inside))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [{"id": f"p{k}", "start": a, "end": b, "text": text[a:b], "hits": inside}
            for k, (_, a, b, inside) in enumerate(sorted(ranked[:n], key=lambda r: r[1]), 1)]
