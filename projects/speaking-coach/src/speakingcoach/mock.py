"""The offline mock model's two roles. Deterministic, no keys, $0 — and deliberately not identical to the code rules,
so the eval measures something and the guard is exercised exactly as it would be with a real model."""
from __future__ import annotations

import re

from .rewrite import strip_marked

NUM = re.compile(r"^\s*(?:about\s+|around\s+)?(\d|a\s+(hundred|few|couple|dozen|thousand|million)|"
                 r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b)", re.I)
BE = {"was", "is", "were", "be", "i'm", "he's", "she's", "they're", "we're", "you're", "'s", "am", "are", "it's"}
VERBISH_AFTER_JUST = {"want", "need", "think", "wanted", "needed", "got", "get", "had", "have", "said", "say"}


def _last(s: str) -> str:
    w = re.findall(r"[A-Za-z']+", s.lower())
    return w[-1] if w else ""


def disambiguate(payload: dict) -> dict:
    out = []
    for o in payload.get("occurrences", []):
        word, before, after = o.get("word", "").lower(), o.get("before", ""), o.get("after", "")
        prev = _last(before)
        filler, conf, why = False, 0.6, "unclear"
        if word == "like":
            if NUM.match(after):
                filler, conf, why = True, 0.85, "stands in for 'about'"
            elif prev in BE and (after.lstrip().startswith((",", "\"", "“", "'")) or prev in ("was", "is")):
                filler, conf, why = True, 0.8, "quotative"
            elif before.rstrip().endswith(",") or after.lstrip().startswith(","):
                filler, conf, why = True, 0.8, "set off by a pause"
            elif prev == "just" and not after.lstrip().lower().startswith(("that", "this", "it", "a ", "the ")):
                filler, conf, why = True, 0.75, "tic after 'just'"
            elif after.lstrip().lower().startswith(("a ", "an ", "the ", "this", "that", "my ", "your ", "it ")):
                filler, conf, why = False, 0.8, "comparison"
        elif word == "you know":
            if after.lstrip().startswith((",", "?", ".")) or before.rstrip().endswith(","):
                filler, conf, why = True, 0.8, "bridge"
            elif after.lstrip().lower().startswith("that"):
                filler, conf, why = False, 0.75, "knowing a fact"
        elif word == "right":
            filler, conf, why = after.lstrip().startswith(("?", ",")), 0.75, "tag" if after.lstrip()[:1] in "?," else "meaning"
        elif word == "just":
            nxt = (re.findall(r"[A-Za-z']+", after.lower()) or [""])[0]
            filler, conf, why = (nxt in VERBISH_AFTER_JUST or after.lstrip().startswith(",")), 0.75, "softener"
        elif word == "actually":
            filler, conf, why = before.rstrip().endswith(","), 0.7, "emphasis"
        else:
            filler, conf, why = before.rstrip().endswith(",") and after.lstrip().startswith(","), 0.65, "pause-like"
        out.append({"id": o["id"], "is_filler": bool(filler), "confidence": conf, "reason": why})
    return {"verdicts": out}


TIPS = {
    "filler sound": (0, "Pause for a beat instead of filling the silence"),
    "sentence starter": (1, "Start with the point itself"),
    "hedging phrase": (None, "Say it plainly; if you're unsure, say how unsure once"),
    "closing crutch": (None, "End on your point, then stop"),
    "filler word": (1, "Let a short pause do the job"),
    "repetition": (2, "Slow down slightly so the next word is ready"),
}


def coach(payload: dict) -> dict:
    stats = payload.get("stats", {})
    plan = payload.get("plan", [])
    cats = sorted(stats.get("by_category", {}).items(), key=lambda kv: -kv[1])
    pos = stats.get("by_position", {})
    where = max(pos, key=pos.get) if pos and any(pos.values()) else "throughout"
    by_cat_top = stats.get("top_by_category", {})
    patterns = []
    for cat, n in cats[:3]:
        idx, fallback = TIPS.get(cat, (None, "Notice it, then pause instead"))
        tip = plan[idx] if idx is not None and idx < len(plan) else fallback
        words = [w for w, _ in by_cat_top.get(cat, []) if w != "repetition"][:2]
        title = f"{cat.capitalize()} ({n}×" + (f": {', '.join(words)}" if words else "") + ")"
        patterns.append({"title": title, "where": f"most often in the {where}" if cat == cats[0][0] else "spread out",
                         "tip": tip})
    rewrites = [{"passage_id": p["id"], "rewrite": strip_marked(p["marked"]),
                 "note": f"removed {p['marked'].count('⟦')} flagged word(s)"} for p in payload.get("passages", [])]
    return {"patterns": patterns, "rewrites": rewrites}
