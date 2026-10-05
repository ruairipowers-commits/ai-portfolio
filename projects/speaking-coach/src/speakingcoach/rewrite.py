"""Rewrites of the worst passages, and the guard every rewrite must pass before anyone sees it (SEC-04, OBS-02).

The guard is code, not another model:
  - none of the speaker's flagged words or repeats left in (checked with the same detector and word list)
  - every number and every name placeholder from the original is still there (nothing dropped or invented)
  - no new numbers
  - length within a band of the passage with its fillers removed (a rewrite, not a new speech)
"""
from __future__ import annotations

import re

from .detect import Hit, detect
from .lexicon import Lexicon

MARK_L, MARK_R = "⟦", "⟧"
NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
                    r"seventy|eighty|ninety|hundred|thousand|million|billion|percent|half|quarter)\b", re.I)
PLACEHOLDER = re.compile(r"\[(?:NAME|EMAIL|PHONE)_\d+\]")
WORDS = re.compile(r"[A-Za-z0-9']+")


def mark(text: str, start: int, hits: list[Hit]) -> str:
    """Wrap each counted hit in ⟦ ⟧ (offsets relative to the passage start)."""
    out, pos = [], 0
    for h in sorted(hits, key=lambda h: h.start):
        a, b = h.start - start, h.end - start
        if a < pos or b > len(text):
            continue
        out += [text[pos:a], MARK_L, text[a:b], MARK_R]
        pos = b
    out.append(text[pos:])
    return "".join(out)


def strip_marked(marked: str) -> str:
    """Remove ⟦marked⟧ spans and tidy the punctuation they leave behind. Used by the offline mock and as the
    length baseline for the guard."""
    s = re.sub(rf"{MARK_L}[^{MARK_R}]*{MARK_R}", "\x00", marked)
    s = re.sub(r",\s*\x00\s*,", ",\x00", s)                       # "I've, um, been" → "I've,\x00 been"
    s = re.sub(r"(^|[.?!]\s+|\n)\s*(\x00\s*,?\s*)+", r"\1", s)     # leading filler(s) and their comma
    s = re.sub(r",\s*\x00\s*\?", ".", s)                              # "slow, you know?" → "slow." (a tag, not a question)
    s = re.sub(r",?\s*\x00\s*,?\s*(?=[.?!]|$)", "", s)              # trailing filler before the full stop
    s = re.sub(r",\x00", " ", s)
    s = re.sub(r"\s*\x00\s*", " ", s)
    s = re.sub(r"\s+([,.?!])", r"\1", s)
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r"([.?!])(\s*[.?!])+", r"\1", s)                    # a sentence that was only filler
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    s = re.sub(r"(^|[.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    s = re.sub(r"^,\s*", "", s)
    return s


def check(original_marked: str, rewrite: str, lex: Lexicon) -> list[str]:
    """Problems with a rewrite (empty list = passes). Both strings are in placeholder form."""
    problems = []
    if not rewrite or not rewrite.strip():
        return ["empty rewrite"]
    if MARK_L in rewrite or MARK_R in rewrite:
        problems.append("still contains ⟦ ⟧ markers")
    left = [h for h in detect(rewrite, lex) if h.verdict == "filler"]
    if left:
        problems.append("still has flagged words: " + ", ".join(sorted({h.text.strip() or h.entry for h in left})))
    original = original_marked.replace(MARK_L, "").replace(MARK_R, "")
    want_nums = {n.lower() for n in NUMBER.findall(original)}
    got_nums = {n.lower() for n in NUMBER.findall(rewrite)}
    if want_nums - got_nums:
        problems.append("dropped numbers: " + ", ".join(sorted(want_nums - got_nums)))
    if got_nums - want_nums:
        problems.append("added numbers: " + ", ".join(sorted(got_nums - want_nums)))
    missing = set(PLACEHOLDER.findall(original)) - set(PLACEHOLDER.findall(rewrite))
    if missing:
        problems.append("dropped names: " + ", ".join(sorted(missing)))
    added = set(PLACEHOLDER.findall(rewrite)) - set(PLACEHOLDER.findall(original))
    if added:
        problems.append("added names: " + ", ".join(sorted(added)))
    base = len(WORDS.findall(strip_marked(original_marked)))
    n = len(WORDS.findall(rewrite))
    if base and not (0.6 * base <= n <= 1.3 * base + 2):
        problems.append(f"length {n} words vs {base} with fillers removed (allowed 60–130%)")
    return problems
