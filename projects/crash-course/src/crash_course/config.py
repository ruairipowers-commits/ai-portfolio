"""Paths and settings.

`root()` is the project folder (config, prompts, evals, bundled courses, sources). `data_dir()` is where anything
written at runtime goes: the learner database, generated course drafts, the email outbox and run outputs. Locally
both are the project folder; in the hosted demo `data_dir()` is the visitor's sandbox or the service's volume.
"""
from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parent
LEVELS = ("familiar", "beginner", "intermediate")


def root() -> Path:
    if os.getenv("COURSE_ROOT"):
        return Path(os.environ["COURSE_ROOT"])
    return PKG.parents[1]


def data_dir() -> Path:
    from . import demo
    if demo.current():
        return demo.current()
    return Path(os.getenv("COURSE_DATA", str(root())))


class Settings(dict):
    """config/settings.yaml as a dict, with a few helpers."""

    @classmethod
    def load(cls) -> "Settings":
        return cls(yaml.safe_load((root() / "config" / "settings.yaml").read_text()))

    def level(self, name: str) -> dict:
        return self["levels"][name]

    def next_level(self, name: str) -> str | None:
        i = LEVELS.index(name)
        return LEVELS[i + 1] if i + 1 < len(LEVELS) else None

    @cached_property
    def blocked(self) -> list[tuple[str, str, str]]:
        out = []
        path = root() / self["checks"]["banned_terms_file"]
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            term, cat, action = [p.strip() for p in line.split("|")]
            out.append((term.lower(), cat, action))
        return out
