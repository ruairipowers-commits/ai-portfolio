"""What's new: dated updates per course, collected by a daily scan.

Where items come from (`news.scanner` in config/settings.yaml):
  claude   the daily Claude task (skill `course-news`) researches each technology and writes items
  feeds    `course news-scan` reads release feeds (config/feeds.yaml) and summarises them with `course-news`
Both write through `merge()`, so every item is validated the same way whoever found it.

Where items live: one JSON line per item in `news/items.jsonl`. The scan publishes that file to the `course-news`
branch (scripts/course_news.py), never to main; the site build merges the branch in, and the live service reads it
from `COURSE_NEWS_URL` (refreshed every `news.refresh_minutes`). News is factual and links to its source, so it
shows without an approval. What does need the owner:
  - a status badge (deprecated / replaced / declining / retired) is the tech page's front matter, changed only by a
    pull request the owner merges; an item's `status` is just the scan's proposal
  - an item marked `material` lists the levels it may make out of date; the owner page shows it until reviewed
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from .config import LEVELS, data_dir
from .schemas import Strict
from .store import approval, now, rows

KINDS = ("release", "feature", "deprecation", "retirement", "security", "pricing", "other")
STATUSES = ("active", "deprecated", "replaced", "declining", "retired")
STATUS_LABEL = {"deprecated": "Deprecated", "replaced": "Replaced", "declining": "Less used", "retired": "Retired"}
SLUG = r"^[a-z0-9][a-z0-9-]{0,40}$"


class NewsItem(Strict):
    course: str = Field(pattern=SLUG)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")          # when the update happened (release date), not today
    title: str = Field(min_length=4, max_length=160)
    summary: str = Field(min_length=10, max_length=400)          # one or two sentences, in our own words
    url: str = Field(max_length=500)                             # the source: release notes, changelog, announcement
    kind: Literal[KINDS] = "release"
    material: bool = False                                       # may make a published level out of date
    affects: list[Literal[LEVELS]] = []                          # which levels, when material
    reason: str = Field(default="", max_length=300)              # why it is material, for the owner
    status: Literal[STATUSES] | None = None                      # a proposed course status (needs a merged PR)
    replaced_by: str = Field(default="", max_length=60)
    source: Literal["claude", "feeds", "manual"] = "manual"

    @field_validator("url")
    @classmethod
    def _https(cls, v):
        if not re.match(r"^https://[^\s<>\"']+$", v):
            raise ValueError("url must be an https link")
        return v

    @field_validator("date")
    @classmethod
    def _real_date(cls, v):
        d = date.fromisoformat(v)
        if d > datetime.now(timezone.utc).date():
            raise ValueError("date is in the future")
        return v

    @field_validator("title", "summary", "reason")
    @classmethod
    def _plain(cls, v):
        if re.search(r"<[a-z/!]", v, re.I):                     # no markup: shown as text everywhere
            raise ValueError("no HTML in news text")
        return v.strip()

    @property
    def id(self) -> str:
        return item_id(self.course, self.url, self.title)


def item_id(course: str, url: str, title: str) -> str:
    return hashlib.sha256(f"{course}|{url}|{title.strip().lower()}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------- the file
def items_path() -> Path:
    return data_dir() / "warehouse" / "news" / "items.jsonl"


_cache: dict[str, tuple[float, list[dict]]] = {}


def load(path: Path | None = None) -> list[dict]:
    """Every item, newest first, each with its `id`. Bad lines are skipped (the file is validated on write)."""
    p = Path(path or items_path())
    if not p.exists():
        return []
    key, mtime = str(p), p.stat().st_mtime
    if key in _cache and _cache[key][0] == mtime:
        return _cache[key][1]
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            collected = raw.pop("collected_at", "")
            it = NewsItem.model_validate(raw)
        except (ValueError, ValidationError):
            continue
        out.append({**it.model_dump(), "id": it.id, "collected_at": collected})
    out.sort(key=lambda r: (r["date"], r["collected_at"], r["id"]), reverse=True)
    _cache[key] = (mtime, out)
    return out


def merge(new: list[dict], path: Path | None = None, known_courses: set[str] | None = None) -> dict:
    """Validate and add items; duplicates (same course, link and title) are skipped. Returns counts and errors."""
    p = Path(path or items_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    have = {r["id"] for r in load(p)}
    added, skipped, errors, lines = 0, 0, [], []
    for i, raw in enumerate(new):
        try:
            it = NewsItem.model_validate({k: v for k, v in raw.items() if k not in ("id", "collected_at")})
            if known_courses is not None and it.course not in known_courses:
                raise ValueError(f"unknown course {it.course!r}")
            if it.material and not it.affects:
                raise ValueError("a material item must name the levels it affects")
        except ValidationError as e:
            errors.append(f"item {i}: " + "; ".join(f"{'.'.join(map(str, x['loc'])) or 'item'}: {x['msg']}"
                                                    for x in e.errors())[:300])
            continue
        except ValueError as e:
            errors.append(f"item {i}: {str(e)[:300]}")
            continue
        if it.id in have:
            skipped += 1
            continue
        have.add(it.id)
        lines.append(json.dumps({**it.model_dump(exclude_defaults=False), "collected_at": now()}, sort_keys=True))
        added += 1
    if lines:
        with p.open("a") as f:
            f.write("".join(ln + "\n" for ln in lines))
    return {"added": added, "skipped": skipped, "errors": errors}


def sync(s, force: bool = False) -> str:
    """Live service: refresh the local copy from COURSE_NEWS_URL (the course-news branch's raw file)."""
    url = os.getenv("COURSE_NEWS_URL") or (s.get("news") or {}).get("remote_url") or ""
    if not url:
        return "no remote set"
    p = items_path()
    age_s = time.time() - p.stat().st_mtime if p.exists() else 1e9
    if not force and age_s < (s.get("news") or {}).get("refresh_minutes", 60) * 60:
        return "fresh"
    if not url.startswith("https://"):
        return "remote must be https"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crash-course-news/1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read(5_000_000).decode()
    except Exception as e:  # noqa: BLE001 — keep serving the old copy
        return f"kept old copy ({type(e).__name__})"
    good = []
    for line in text.splitlines():
        try:
            raw = json.loads(line)
            NewsItem.model_validate({k: v for k, v in raw.items() if k != "collected_at"})
            good.append(json.dumps(raw, sort_keys=True))
        except (ValueError, ValidationError):
            continue
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(g + "\n" for g in good))
    tmp.replace(p)
    return f"{len(good)} items"


# ---------------------------------------------------------------- views
def latest_by_course(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:                         # newest first, so the first per course wins
        out.setdefault(it["course"], it)
    return out


def for_course(items: list[dict], slug: str, n: int = 5) -> list[dict]:
    return [it for it in items if it["course"] == slug][:n]


# ---------------------------------------------------------------- learners: seen marks
def seen_ids(conn, learner_id: int) -> set[str]:
    return {r["item_id"] for r in rows(conn, "SELECT item_id FROM news_seen WHERE learner_id=?", learner_id)}


def mark_seen(conn, learner_id: int, ids: list[str]) -> int:
    ids = [i for i in dict.fromkeys(ids) if re.fullmatch(r"[0-9a-f]{12}", i)][:500]
    for i in ids:
        conn.execute("INSERT OR IGNORE INTO news_seen (learner_id, item_id, seen_at) VALUES (?,?,?)",
                     (learner_id, i, now()))
    return len(ids)


def completed_courses(conn, learner_id: int) -> set[str]:
    """Courses where the learner has completed at least one level: the ones whose news they most want."""
    return {r["course"] for r in rows(conn, "SELECT DISTINCT course FROM progress WHERE learner_id=? "
                                            "AND completed_at IS NOT NULL", learner_id)}


def unseen_count(conn, learner_id: int, items: list[dict]) -> int:
    done, seen = completed_courses(conn, learner_id), seen_ids(conn, learner_id)
    return sum(1 for it in items if it["course"] in done and it["id"] not in seen)


# ---------------------------------------------------------------- owner: material items to review
def to_review(conn, items: list[dict]) -> list[dict]:
    done = {r["item_id"] for r in rows(conn, "SELECT item_id FROM news_reviews")}
    return [it for it in items if (it["material"] or it["status"]) and it["id"] not in done]


def review(conn, item_id_: str, decision: str, actor: str, note: str = "") -> None:
    if decision not in ("reviewed", "dismissed"):
        raise ValueError("decision must be reviewed or dismissed")
    conn.execute("INSERT OR REPLACE INTO news_reviews (item_id, decision, actor, at, note) VALUES (?,?,?,?,?)",
                 (item_id_, decision, actor, now(), note[:300]))
    approval(conn, actor, "news", item_id_, decision, note[:300])
