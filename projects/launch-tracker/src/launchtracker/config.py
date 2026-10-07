"""Settings, paths and clocks. One place decides where data lives and what "now" is."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import demo


def _find_root() -> Path:
    if os.getenv("LAUNCHES_ROOT"):
        return Path(os.environ["LAUNCHES_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


def workspace() -> Path:
    """Where mutable data lives: the project root, or this visitor's sandbox in the hosted demo."""
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

    @property
    def mode(self) -> str:
        """What the data actually is when known (`_data_mode`, from the last load), else what is configured."""
        return self.raw.get("_data_mode") or os.getenv("LAUNCHES_MODE", self.raw.get("mode", "fixture"))

    def for_data(self, data_mode: str | None) -> "Settings":
        """A copy whose clock and labels follow the data that was loaded (live config + sample data = sample)."""
        raw = dict(self.raw)
        if data_mode:
            raw["_data_mode"] = data_mode
        return Settings(raw)

    @property
    def db_path(self) -> Path:
        return workspace() / os.getenv("DUCKDB_PATH", self.raw["duckdb_path"])

    def now(self) -> datetime:
        """The fixture runs on a fixed clock so countdowns and 'upcoming' are reproducible; live uses the real one."""
        if self.mode == "fixture":
            return datetime.fromisoformat(self.raw["fixture_clock"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
