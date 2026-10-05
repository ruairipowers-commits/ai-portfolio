"""Find every configured word and phrase, and settle as many as code can.

Each occurrence becomes a Hit with a verdict:
  filler      counted (by rule, by a model with enough confidence, or by the speaker)
  not_filler  normal English ("I like it", "what kind of", "so far") — shown, never counted
  ambiguous   code can't tell; goes to the disambiguator model with a few words of context
  disputed    the model wasn't sure enough; not counted until the speaker decides

Rules are deliberately readable: a position rule (opener/closer) or a neighbour rule per common word.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .lexicon import Entry, Lexicon
from .text import Token, is_opener, tokenize

COUNTED = {"filler"}


@dataclass
class Hit:
    id: str
    start: int
    end: int
    text: str
    entry: str                 # the list phrase it matched ("you know"), or "repetition"
    category: str
    weight: float
    rule: str
    verdict: str
    source: str = "rule"       # rule · model · speaker
    reason: str = ""
    confidence: float = 1.0
    token_index: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- neighbour rules for common context words
SUBJECTS = {"i", "you", "we", "they", "he", "she", "who", "people", "folks", "everyone", "nobody", "kids"}
VERB_BEFORE_LIKE = {"would", "'d", "do", "don't", "didn't", "does", "doesn't", "to", "might", "will", "won't",
                    "really", "also", "both", "all", "i'd", "you'd", "we'd", "they'd", "he'd", "she'd", "would've"}
PREP_BEFORE_LIKE = {"look", "looks", "looked", "looking", "feel", "feels", "felt", "feeling", "sound", "sounds",
                    "sounded", "seem", "seems", "seemed", "something", "anything", "nothing", "more", "much",
                    "not", "exactly", "things", "stuff", "nothing's", "taste", "tastes", "act", "acts", "acting",
                    "behave", "behaves", "is", "was", "be", "it's", "that's", "what's"}
NOUN_BEFORE_KIND = {"what", "a", "the", "this", "that", "any", "every", "one", "some", "which", "no", "same",
                    "different", "two", "these", "those", "all", "that's", "what's", "another", "other", "my",
                    "your", "our", "their", "his", "her"}
NOT_BEFORE_YOU_KNOW = {"do", "did", "don't", "didn't", "if", "as", "would", "does", "doesn't", "whether", "let",
                       "what", "how", "now", "where", "so", "because", "cause", "should", "might"}
OBJECT_AFTER_YOU_KNOW = {"how", "what", "where", "why", "who", "about", "him", "her", "them", "it", "me", "my",
                         "your", "our", "their", "his", "anyone", "anything", "everything", "nothing", "something"}
RIGHT_NOT_NEXT = {"now", "away", "here", "there", "after", "before", "back", "side", "hand", "answer", "thing",
                  "way", "to", "of", "call", "decision", "choice", "one", "person", "time", "place", "track"}
RIGHT_NOT_PREV = {"the", "all", "that's", "is", "be", "turn", "on", "your", "my", "his", "her", "exactly", "just",
                  "alright", "you're", "it's", "was", "were", "are", "get", "got", "quite", "not", "a", "their"}
SO_NOT_NEXT = {"far", "much", "many", "long", "few", "little", "called", "to"}
WELL_NOT_NEXT = {"done", "known", "enough", "being", "over", "aware", "said"}
I_MEAN_NOT_PREV = {"what", "if", "you", "i", "that's", "which", "do", "don't"}


def _comma_wrapped(first: Token, last: Token) -> bool:
    return ("," in first.gap_before or first.sentence_start) and ("," in last.gap_after or last.sentence_end)


def context_rule(phrase: str, toks: list[Token], a: int, b: int) -> tuple[str, str]:
    """Verdict for the phrase spanning tokens a..b from its neighbours: (filler | not_filler | ambiguous, reason)."""
    first, last = toks[a], toks[b]
    prev = toks[a - 1].low if a > 0 and not first.sentence_start else ""
    nxt = toks[b + 1].low if b + 1 < len(toks) and not last.sentence_end else ""
    wrapped = _comma_wrapped(first, last)
    if phrase == "like":
        if wrapped and (prev or nxt):
            return "filler", "set off by commas"
        if first.clause_start and "," in last.gap_after:
            return "filler", "starts a clause, then a comma"
        if prev in SUBJECTS or prev in VERB_BEFORE_LIKE or prev.endswith("'d"):
            return "not_filler", f"verb ('{prev} like')"
        if prev in PREP_BEFORE_LIKE and "," not in first.gap_before:
            return "not_filler", f"comparison ('{prev} like')"
        return "ambiguous", "needs context"
    if phrase in ("kind of", "sort of"):
        if prev in NOUN_BEFORE_KIND and "," not in first.gap_before:
            return "not_filler", f"noun ('{prev} {phrase}')"
        if nxt == "thing" or toks[b].low.endswith("s"):
            return "not_filler", "noun"
        return "filler", "softens the word after it"
    if phrase == "you know":
        if prev in NOT_BEFORE_YOU_KNOW and "," not in first.gap_before:
            return "not_filler", f"a real question or statement ('{prev} you know')"
        if nxt in OBJECT_AFTER_YOU_KNOW and "," not in last.gap_after:
            return "not_filler", f"knowing something ('you know {nxt}')"
        if wrapped or last.clause_end or "?" in last.gap_after:
            return "filler", "bridges or tags a thought"
        return "ambiguous", "needs context"
    if phrase == "right":
        if last.clause_end and "?" in last.gap_after and not nxt:
            return "filler", "tag question ('..., right?')"
        if first.sentence_start and "," in last.gap_after:
            return "filler", "opener ('Right, ...')"
        if nxt in RIGHT_NOT_NEXT or prev in RIGHT_NOT_PREV:
            return "not_filler", "direction or correctness"
        return "ambiguous", "needs context"
    if phrase == "i mean":
        if prev in I_MEAN_NOT_PREV and "," not in first.gap_before:
            return "not_filler", "says what something means"
        if first.clause_start or wrapped:
            return "filler", "restarts the sentence"
        return "ambiguous", "needs context"
    if phrase == "so":
        if is_opener(toks, a) and nxt not in SO_NOT_NEXT:
            return "filler", "sentence starter"
        return "not_filler", "means 'therefore' or 'very'"
    if phrase == "well":
        if is_opener(toks, a) and nxt not in WELL_NOT_NEXT:
            return "filler", "sentence starter"
        return "not_filler", "adverb"
    if phrase == "actually":
        if first.sentence_start and "," in last.gap_after:
            return "filler", "opener"
        return "ambiguous", "emphasis or correction"
    return "ambiguous", "needs context"


def position_rule(e: Entry, toks: list[Token], a: int, b: int) -> tuple[str, str]:
    phrase = " ".join(e.words)
    if e.rule == "always":
        return "filler", "on your list"
    if e.rule == "opener":
        nxt = toks[b + 1].low if b + 1 < len(toks) and not toks[b].sentence_end else ""
        skip = SO_NOT_NEXT if phrase == "so" else WELL_NOT_NEXT if phrase == "well" else set()
        if is_opener(toks, a):
            if nxt in skip:
                return "not_filler", f"'{phrase} {nxt}' is ordinary English"
            return "filler", "starts the sentence"
        return "not_filler", "not at the start of a sentence"
    if e.rule == "closer":
        if toks[b].clause_end and (toks[b].sentence_end or "?" in toks[b].gap_after or b == len(toks) - 1
                                   or "," in toks[b].gap_after):
            return "filler", "ends the thought"
        return "not_filler", "not at the end of a thought"
    return context_rule(phrase, toks, a, b)


# ---------------------------------------------------------------- matching
def _phrase_at(toks: list[Token], k: int, words: tuple[str, ...]) -> bool:
    if k + len(words) > len(toks):
        return False
    for j, w in enumerate(words):
        t = toks[k + j]
        if t.low != w:
            return False
        if j and t.gap_before.strip():           # "kind, of" is not "kind of"
            return False
    return True


def detect(text: str, lex: Lexicon) -> list[Hit]:
    toks = tokenize(text)
    entries = lex.active()
    hits: list[Hit] = []
    taken = [False] * len(toks)
    for k in range(len(toks)):
        if taken[k]:
            continue
        for e in entries:
            if _phrase_at(toks, k, e.words):
                b = k + len(e.words) - 1
                verdict, reason = position_rule(e, toks, k, b)
                hits.append(Hit("", toks[k].start, toks[b].end, text[toks[k].start:toks[b].end], e.text, e.category,
                                e.weight, e.rule, verdict, "rule", reason, 1.0, k))
                for j in range(k, b + 1):
                    taken[j] = True
                break
    if lex.repetition:
        # only real (or still-open) fillers are see-through: "it, so it" is not a repeat when "so" isn't a filler
        filler = [False] * len(toks)
        for h in hits:
            if h.verdict != "not_filler":
                for j, tk in enumerate(toks):
                    if h.start <= tk.start and tk.end <= h.end:
                        filler[j] = True
        hits += _repetitions(text, toks, taken, filler, lex)
    hits.sort(key=lambda h: h.start)
    for n, h in enumerate(hits, 1):
        h.id = f"h{n}"
    return hits


def _repetitions(text: str, toks: list[Token], taken: list[bool], filler: list[bool], lex: Lexicon) -> list[Hit]:
    """'the the', 'in, in', 'I-I-I', and Ruairi's "I've, uh, I've": a word said again straight away, with only
    pauses or filler between. The repeats after the first are the hit, so removing it keeps one copy."""
    out: list[Hit] = []
    words = [k for k in range(len(toks)) if not taken[k]]      # fillers are see-through for this check
    n = 0
    while n < len(words) - 1:
        k = words[n]
        t = toks[k]
        m = n
        while m + 1 < len(words):
            a, b = toks[words[m]], toks[words[m + 1]]
            between = text[a.end:b.start]
            skipped = words[m + 1] - words[m] - 1
            if (b.low != t.low or t.low.isdigit() or any(c in between for c in ".?!\n")
                    or (skipped and not all(filler[j] for j in range(words[m] + 1, words[m + 1])))):
                break
            m += 1
        if m > n and (t.low, t.low) not in lex.repetition_allow:
            last = toks[words[m]]
            adjacent = words[m] - k == m - n                   # nothing in between: "the the", "I-I-I"
            start = t.end if adjacent else toks[words[n + 1]].start
            out.append(Hit("", start, last.end, text[start:last.end], "repetition", "repetition", 1.0,
                           "repetition", "filler", "rule", f"'{t.text}' repeated", 1.0, words[n + 1]))
        n = m + 1
    return out


def counted(hits: list[Hit]) -> list[Hit]:
    return [h for h in hits if h.verdict in COUNTED]
