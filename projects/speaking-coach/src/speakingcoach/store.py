"""Settings, the run log (OBS-01) and opt-in progress history.

Privacy by default (DATA-03, NFR-5): the run log holds hashes and counts only — never transcript text or the word
list. History (SQLite, stdlib) is written only when privacy.save_history is on, and holds per-run numbers and the
top crutch words for that speaker, nothing else.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import demo


def _find_root() -> Path:
    if os.getenv("SPEAKINGCOACH_ROOT"):
        return Path(os.environ["SPEAKINGCOACH_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


def workspace() -> Path:
    """Where anything mutable goes: the project root, or this visitor's sandbox in the hosted demo."""
    return demo.current() or ROOT


@dataclass
class Settings:
    raw: dict

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        return cls(yaml.safe_load((path or ROOT / "config" / "settings.yaml").read_text()))

    def __getitem__(self, k):
        return self.raw[k]

    def get(self, k, default=None):
        return self.raw.get(k, default)


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_path() -> Path:
    return workspace() / "logs" / "runs.jsonl"


def log_run(entry: dict) -> None:
    """One line per run: hashes, counts, model calls. Asserted text-free by tests."""
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def read_runs() -> list[dict]:
    p = log_path()
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


# ---------------------------------------------------------------- opt-in history
def _history(settings: Settings) -> sqlite3.Connection:
    p = workspace() / settings["privacy"]["history_path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("""create table if not exists runs (ts text, speaker text, words int, fillers int,
                   rate real, grade text, top text, run_id text)""")
    return con


def save_history(settings: Settings, speaker: str, run_id: str, score) -> None:
    con = _history(settings)
    with con:
        con.execute("insert into runs values (?,?,?,?,?,?,?,?)",
                    (now(), speaker or "me", score.words, score.fillers, score.rate_per_100, score.grade,
                     json.dumps(score.top), run_id))
    con.close()


def history(settings: Settings, speaker: str | None = None) -> list[dict]:
    p = workspace() / settings["privacy"]["history_path"]
    if not p.exists():
        return []
    con = sqlite3.connect(p)
    q = "select ts, speaker, words, fillers, rate, grade, top from runs"
    rows = con.execute(q + (" where speaker = ?" if speaker else "") + " order by ts",
                       (speaker,) if speaker else ()).fetchall()
    con.close()
    return [dict(zip(("ts", "speaker", "words", "fillers", "rate", "grade", "top"), r)) for r in rows]
