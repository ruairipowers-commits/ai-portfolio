"""Grading, scoring and the sealed answer key. All code, no model: a player's answer never reaches an LLM.

- normalize(): one canonical form per answer ("Forty-Two" → "42", " The  Owl. " → "the owl", 3.14159 → "3.142"
  at 3 decimals), so equivalent answers match.
- The key is stored as salted HMACs of its accepted normalized forms. Grading compares HMACs, so it never needs
  the plain answer, and a copy of the database doesn't give the answers away.
- seal()/unseal(): the plain key and worked solution are encrypted (Fernet) with PUZZLE_KEY_SECRET and only
  decrypted by the reveal step after close, by the operator's review of an escalated draft, or for an answer-key PDF.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import unicodedata
import warnings
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from cryptography.fernet import Fernet, InvalidToken

DEV_SECRET = "dev-only-not-secret"

_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def words_to_int(text: str) -> int | None:
    """'forty-two' → 42, 'one thousand two hundred and five' → 1205; None if it isn't a number in words."""
    toks = [t for t in re.split(r"[\s\-]+", text.lower().strip()) if t and t != "and"]
    if not toks:
        return None
    neg = toks[0] in ("minus", "negative")
    toks = toks[1:] if neg else toks
    total = cur = 0
    for t in toks:
        if t in _UNITS:
            cur += _UNITS[t]
        elif t in _TENS:
            cur += _TENS[t]
        elif t == "hundred":
            cur = (cur or 1) * 100
        elif t in _SCALES:
            total += (cur or 1) * _SCALES[t]
            cur = 0
        else:
            return None
    return -(total + cur) if neg else total + cur


def _number(text: str) -> Decimal | None:
    t = text.strip().replace(",", "").replace("_", "").replace("−", "-")
    t = re.sub(r"\s+", "", t)
    try:
        return Decimal(t)
    except InvalidOperation:
        w = words_to_int(text)
        return Decimal(w) if w is not None else None


def normalize(answer: str, answer_type: str = "text", decimals: int | None = None) -> str | None:
    """Canonical form, or None if the answer can't be of this type (e.g. 'abc' for an integer)."""
    a = unicodedata.normalize("NFKC", str(answer or "")).strip()[:200]
    if answer_type in ("int", "float"):
        a = re.sub(r"^(the\s+)?(answer\s+(is\s+)?)?", "", a, flags=re.I).strip().rstrip(".")
        n = _number(a)
        if n is None:
            return None
        if answer_type == "int":
            if n != n.to_integral_value():
                return None
            return str(int(n))
        q = Decimal(1).scaleb(-(decimals if decimals is not None else 3))
        v = n.quantize(q, rounding=ROUND_HALF_UP)
        return format(v + Decimal(0), "f")          # + 0 turns -0.000 into 0.000
    a = a.lower()
    a = re.sub(r"[\"'`“”‘’]", "", a)
    a = re.sub(r"[^\w\s\-]", " ", a)                 # punctuation → space
    a = re.sub(r"\s+", " ", a).strip()
    a = re.sub(r"^(the answer is|answer is|answer)\s+", "", a)
    return a or None


# ---------------------------------------------------------------- secrets
def _secret(name: str) -> str:
    v = os.getenv(name, "")
    if not v:
        if os.getenv("PUZZLE_REQUIRE_SECRETS") == "1":
            raise RuntimeError(f"{name} is not set (SEC-01); refusing to run with the development default")
        warnings.warn(f"{name} not set: using the development default (fine offline, never in production)", stacklevel=3)
        v = DEV_SECRET
    return v


def answer_hash(puzzle_salt: str, normalized: str) -> str:
    """HMAC of one normalized answer. The per-puzzle salt stops one puzzle's hashes matching another's."""
    key = (_secret("PUZZLE_SALT") + ":" + puzzle_salt).encode()
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()


def key_hashes(puzzle_salt: str, forms: list[str], answer_type: str, decimals: int | None) -> list[str]:
    out = []
    for f in forms:
        n = normalize(f, answer_type, decimals)
        if n is not None and (h := answer_hash(puzzle_salt, n)) not in out:
            out.append(h)
    return out


def _fernet() -> Fernet:
    k = hashlib.sha256(_secret("PUZZLE_KEY_SECRET").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(k))


def seal(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def unseal(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise RuntimeError("answer key can't be decrypted: PUZZLE_KEY_SECRET changed since it was sealed") from e


# ---------------------------------------------------------------- grading
def grade(answer: str, answer_type: str, decimals: int | None, hashes: list[str], puzzle_salt: str) -> tuple[bool, str | None]:
    """(correct, normalized). A wrong type (letters for a number) is simply incorrect."""
    n = normalize(answer, answer_type, decimals)
    if n is None:
        return False, None
    return any(hmac.compare_digest(answer_hash(puzzle_salt, n), h) for h in hashes), n


def same_answer(a: str, b: str, answer_type: str, decimals: int | None) -> bool:
    na, nb = normalize(a, answer_type, decimals), normalize(b, answer_type, decimals)
    return na is not None and na == nb


# ---------------------------------------------------------------- scoring
def points(attempts: int, solved: bool, scoring: dict, track: str = "") -> int:
    """round(base × decay^(attempts−1)), at least floor while solved; 0 if unsolved. Defaults 100/70/49/34/24/17."""
    if not solved or attempts < 1:
        return 0
    base, decay, floor = float(scoring.get("base", 100)), float(scoring.get("decay", 0.7)), int(scoring.get("floor", 10))
    mult = float((scoring.get("track_multiplier") or {}).get(track, 1.0))
    p = int(Decimal(base * decay ** (attempts - 1)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return int(round(max(p, floor) * mult))
