"""Tokens with character spans, sentence and clause boundaries. Plain Python, no NLP library to download.

Every hit, count and highlight points back to a character span in the transcript, so the report can show exactly
where something happened and a test can check it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*%?")
SENTENCE_END = re.compile(r"[.?!]")
CLAUSE_PUNCT = re.compile(r"[,;:—–]|\s-\s|\.\.\.|…")
# words that can sit in front of an opener without stopping it being an opener: "And so,", "Um, so", "Okay so"
LEAD_INS = {"and", "but", "um", "uh", "okay", "ok", "well", "yeah", "alright", "oh", "now", "anyway"}


@dataclass
class Token:
    i: int
    text: str
    low: str
    start: int
    end: int
    sentence_start: bool = False   # first word after . ? ! or a new line/turn
    sentence_end: bool = False     # last word before . ? ! or a new line/turn
    clause_start: bool = False     # sentence start, or after , ; : —
    clause_end: bool = False
    gap_before: str = ""           # the characters between the previous word and this one
    gap_after: str = ""


def norm(word: str) -> str:
    return word.lower().replace("’", "'")


def tokenize(text: str) -> list[Token]:
    toks = [Token(i, m.group(), norm(m.group()), m.start(), m.end()) for i, m in enumerate(WORD.finditer(text))]
    for k, t in enumerate(toks):
        t.gap_before = text[toks[k - 1].end:t.start] if k else text[:t.start]
        t.gap_after = text[t.end:toks[k + 1].start] if k + 1 < len(toks) else text[t.end:]
    for k, t in enumerate(toks):
        boundary_before = k == 0 or bool(SENTENCE_END.search(t.gap_before)) or "\n" in t.gap_before
        boundary_after = k == len(toks) - 1 or bool(SENTENCE_END.search(t.gap_after)) or "\n" in t.gap_after
        t.sentence_start, t.sentence_end = boundary_before, boundary_after
        t.clause_start = boundary_before or bool(CLAUSE_PUNCT.search(t.gap_before))
        t.clause_end = boundary_after or bool(CLAUSE_PUNCT.search(t.gap_after))
    return toks


def is_opener(toks: list[Token], k: int) -> bool:
    """Token k starts a sentence, allowing lead-ins: "So,", "And so", "Um, so", "Okay so"."""
    j = k
    while not toks[j].sentence_start:
        if j == 0 or toks[j - 1].low not in LEAD_INS or k - j >= 3:
            return False
        j -= 1
    return True


def sentences(text: str, toks: list[Token]) -> list[tuple[int, int, int, int]]:
    """(char_start, char_end, first_token, last_token) per sentence."""
    out, first = [], 0
    for k, t in enumerate(toks):
        if t.sentence_end:
            end = t.end
            m = SENTENCE_END.search(t.gap_after)
            if m and "\n" not in t.gap_after[:m.start()]:
                end = t.end + m.end()
                while end < len(text) and text[end] in ".?!\"'”’)":
                    end += 1
            out.append((toks[first].start, end, first, k))
            first = k + 1
    return out


def word_count(text: str) -> int:
    return len(WORD.findall(text))
