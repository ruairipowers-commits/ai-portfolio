"""Settings, paths and the per-visitor workspace (hosted demo)."""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from functools import cached_property
from pathlib import Path

import yaml

from . import demo


def _find_root() -> Path:
    if os.getenv("DLP_ROOT"):
        return Path(os.environ["DLP_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


def workspace() -> Path:
    """Where mutable data lives: the project root, or this visitor's sandbox in the hosted demo."""
    return demo.current() or ROOT


class Settings:
    def __init__(self, raw: dict):
        self.raw = raw

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        return cls(yaml.safe_load((path or ROOT / "config" / "settings.yaml").read_text()))

    def __getitem__(self, k):
        return self.raw[k]

    def get(self, k, default=None):
        return self.raw.get(k, default)

    @cached_property
    def as_of(self) -> date:
        return date.fromisoformat(str(os.getenv("DLP_AS_OF") or self.raw["as_of_date"]))

    def path(self, key: str) -> Path:
        """A mutable path from settings.paths, inside the current workspace."""
        return workspace() / self.raw["paths"][key]

    def layer(self, key: str) -> Path:
        """A read-only layer definition file (ontology, vocabulary, shapes, semantic project)."""
        return ROOT / self.raw["layers"][key]


def sha(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode()
    return hashlib.sha256(text).hexdigest()[:16]


def now() -> datetime:
    return datetime.now(timezone.utc)
