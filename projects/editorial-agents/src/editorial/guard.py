"""SEC-02: everything the scout reads is untrusted text from the internet.

A candidate whose title or summary tries to instruct the model (or game the ranking) is escalated: kept for the
record, never classified, never ranked. The model also sees candidates only inside delimiters, with a prompt that
says they are data.
"""
from __future__ import annotations

import re

PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (the |all )?(previous|prior|above)",
    r"you are now\b", r"\bsystem prompt\b", r"\bsystem:\s", r"</?candidate>",
    r"rank (this|me|it) (first|#?1|top)", r"(give|assign) (this|it) (a )?(score|rating) of",
    r"reveal (your|the) (instructions|prompt|keys?)", r"\bjailbreak\b",
]
_RX = re.compile("|".join(PATTERNS), re.I)


def scan(*texts: str) -> list[str]:
    hits = []
    for t in texts:
        hits += [m.group(0) for m in _RX.finditer(t or "")]
    return hits
