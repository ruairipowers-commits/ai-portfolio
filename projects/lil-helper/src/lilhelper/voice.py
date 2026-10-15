"""Spoken (or typed) requests → what to do. Used by the app's microphone button and by Alexa.

Understanding is by rules, not a model, so it's predictable and private: a few dozen phrasings per request. Each
request returns what to say back, and where the app should go (if anywhere). Requests that change something are
small and undoable (a portion count, how much was left, a star rating); planning a week still needs an adult.

  "what's for dinner (tomorrow)"                → the meal, and who's cooking
  "what's on the shopping list"                 → the next trip's list
  "what are my jobs"                            → today's jobs for the person asking
  "I have chicken, rice and broccoli"           → Cook from what I've got, top idea
  "I've got 30 minutes and want something cozy" → Vibe cooking
  "surprise me"                                 → anything from the book
  "we have 3 portions of overnight oats left"   → weekly buffet count
  "dinner was all gone / lots left"             → how much was left
  "rate dinner 5 stars"                         → rating
  "plan next week"                              → drafts it (adults)
"""
from __future__ import annotations

import datetime as dt
import re

from .config import DAYS

NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "sixty": 60,
       "half": 0.5, "a": 1, "an": 1, "zero": 0, "none": 0, "no": 0}
MOOD_WORDS = {"quick": "quick", "fast": "quick", "comfort": "comfort", "cozy": "cozy", "cosy": "cozy", "light": "light",
              "healthy": "light", "veggie": "veggie", "vegetarian": "veggie", "kids": "kid_pleaser", "fresh": "fresh",
              "different": "adventurous", "adventurous": "adventurous", "new": "adventurous", "party": "party",
              "special": "special", "fancy": "special"}


def _num(text: str) -> float | None:
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if m:
        return float(m.group(1))
    for w, n in sorted(NUM.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{w}\b", text):
            return float(n)
    return None


def _day(text: str, today: dt.date) -> tuple[str, str]:
    if "tomorrow" in text:
        d = today + dt.timedelta(days=1)
        return DAYS[d.weekday()], "tomorrow"
    for i, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
        if name in text:
            return DAYS[i], name.title()
    return DAYS[today.weekday()], "today"


def _meal(text: str, default: str = "dinner") -> str:
    for m in ("breakfast", "lunch", "dinner"):
        if m in text:
            return m
    return "dinner" if "tonight" in text or "supper" in text else default


def parse(text: str, today: dt.date) -> dict:
    """Text → {intent, slots}. Order matters: the most specific patterns first."""
    t = " " + re.sub(r"[^a-z0-9.,' ]+", " ", (text or "").lower()) + " "
    t = re.sub(r"\s+", " ", t)
    day, when = _day(t, today)
    if re.search(r"\b(portions?|servings?) (of )?.* left\b|\bleft of\b", t) and _num(t) is not None:
        what = re.sub(r".*\b(portions?|servings?) (of )?", "", t)
        what = re.sub(r"\b(left|remaining|in the fridge)\b.*", "", what).strip()
        return {"intent": "buffet_count", "count": _num(t), "item": what}
    if re.search(r"\b(all gone|ate it all|finished it|nothing left|some left|lots left|a lot left|plenty left)\b", t):
        eaten = "all" if re.search(r"all gone|ate it all|finished|nothing left", t) else (
            "lots_left" if re.search(r"lots|a lot|plenty", t) else "some_left")
        return {"intent": "eaten", "eaten": eaten, "meal": _meal(t), "day": day}
    m = re.search(r"\brate (?:the )?(breakfast|lunch|dinner)?.*?(\d|one|two|three|four|five)\s*stars?", t)
    if m:
        return {"intent": "rate", "rating": int(_num(m.group(2)) or 0), "meal": m.group(1) or "dinner", "day": day}
    if re.search(r"\b(i have|i've got|ive got|we have|we've got|in the fridge|make with|cook with|use up)\b", t) and \
            not re.search(r"\bminutes?\b|\bhours?\b", t):
        have = re.sub(r".*\b(i have|i've got|ive got|we have|we've got|make with|cook with|use up)\b", "", t)
        have = re.sub(r"\b(what can i make|in the fridge|left over|leftover)\b", "", have).strip(" .")
        return {"intent": "cook_with", "have": have, "meal": _meal(t), "day": day}
    if re.search(r"\bminutes?\b|\bhours?\b|\bmood\b|\bfeel like\b|\bin the mood\b", t):
        n = _num(t) or 45
        minutes = int(n * 60) if re.search(r"\bhours?\b", t) and n < 10 else int(n)
        moods = sorted({v for k, v in MOOD_WORDS.items() if re.search(rf"\b{k}\b", t)})
        return {"intent": "vibe", "minutes": minutes, "moods": moods, "meal": _meal(t)}
    if re.search(r"\bsurprise\b|\banything\b|\brandom\b", t):
        return {"intent": "surprise", "meal": _meal(t), "day": day}
    if re.search(r"\bshopping\b|\bgrocer|\bthe list\b|\bbuy\b", t):
        return {"intent": "shopping"}
    if re.search(r"\b(my jobs|my chores|what do i do|my tasks|whose turn|who'?s (on )?(dishes|cooking))\b", t):
        return {"intent": "jobs", "day": day}
    if re.search(r"\bplan (the |next |this )?week\b|\bmake a plan\b", t):
        return {"intent": "plan", "next": "next" in t}
    if re.search(r"\bwhat'?s for|\bwhat are we (having|eating)|\bwhat'?s cooking|\bwhat'?s (the )?(dinner|lunch|breakfast)", t):
        return {"intent": "whats_for", "meal": _meal(t), "day": day, "when": when}
    return {"intent": "unknown"}
