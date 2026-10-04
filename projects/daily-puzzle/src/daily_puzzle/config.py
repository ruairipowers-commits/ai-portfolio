"""Settings, puzzle configuration and paths.

ROOT is the project folder (env PUZZLE_ROOT wins, so tests and the hosted demo can point elsewhere). In the hosted
demo each visitor of the operator app gets a private copy of the mutable folders (see demo.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parent
TRACKS = ("logic", "word", "numbers", "coding", "ai_ml")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TRACK_LABEL = {"logic": "Logic", "word": "Words", "numbers": "Numbers", "coding": "Coding", "ai_ml": "AI / ML"}


def root() -> Path:
    return Path(os.getenv("PUZZLE_ROOT") or PKG.parents[1]).resolve()


def data_dir() -> Path:
    """Where mutable state lives: the visitor's sandbox in the hosted operator demo, else the project root."""
    from . import demo
    return demo.current() or root()


@dataclass
class Settings:
    raw: dict
    puzzles: dict
    models_path: Path
    base: Path = field(default_factory=root)

    @classmethod
    def load(cls) -> "Settings":
        base = root()
        raw = yaml.safe_load((base / "config" / "settings.yaml").read_text())
        pz_path = data_dir() / "config" / "puzzles.yaml"          # the operator demo edits its own copy
        if not pz_path.exists():
            pz_path = base / "config" / "puzzles.yaml"
        puzzles = yaml.safe_load(pz_path.read_text())
        for env, key in (("PUZZLE_GENERATOR_MODEL", "generator_alias"), ("PUZZLE_SOLVER_MODEL", "solver_alias")):
            if os.getenv(env):                       # deploy-time switch, e.g. to the local Ollama models
                raw["llm"][key] = os.environ[env]
        return cls(raw, puzzles, base / "config" / "models.yaml", base)

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def database_url(self) -> str:
        url = os.getenv("DATABASE_URL") or self.raw["database_url"]
        if url.startswith("sqlite:///"):
            rel = url.removeprefix("sqlite:///")
            p = Path(rel) if rel.startswith("/") else data_dir() / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{p}"
        return url

    def path(self, rel: str) -> Path:
        return self.base / rel

    # -------------------------------------------------- puzzle config helpers
    def enabled_tracks(self) -> list[str]:
        return [t for t in TRACKS if (self.puzzles["tracks"].get(t) or {}).get("enabled")]

    def track(self, t: str) -> dict:
        return self.puzzles["tracks"][t]

    def is_sandbox_track(self, t: str) -> bool:
        return bool(self.track(t).get("sandbox"))


def validate_puzzles(cfg: dict) -> list[str]:
    """Problems with a puzzles.yaml (empty list = OK). Run by `puzzle config-check` and before every cycle."""
    from .puzzles import KINDS
    p: list[str] = []
    tracks = cfg.get("tracks") or {}
    if not any((tracks.get(t) or {}).get("enabled") for t in TRACKS):
        p.append("no track is enabled")
    for t, tc in tracks.items():
        if t not in TRACKS:
            p.append(f"unknown track '{t}' (known: {', '.join(TRACKS)})")
            continue
        for k in tc.get("kinds", []):
            if KINDS.get(k, {}).get("track") != t:
                p.append(f"track {t}: unknown kind '{k}' (known: {', '.join(x for x, v in KINDS.items() if v['track'] == t)})")
        if tc.get("enabled") and not tc.get("kinds"):
            p.append(f"track {t} is enabled but has no kinds")
    rot = cfg.get("rotation") or {}
    if rot.get("mode") not in ("weekday", "random"):
        p.append("rotation.mode must be weekday or random")
    for d, t in (rot.get("weekday") or {}).items():
        if d not in WEEKDAYS:
            p.append(f"rotation.weekday: unknown day '{d}'")
        elif t != "random" and t not in TRACKS:
            p.append(f"rotation.weekday.{d}: unknown track '{t}'")
    for d, lvl in ((cfg.get("difficulty") or {}).get("weekday") or {}).items():
        if lvl not in ("easy", "medium", "hard"):
            p.append(f"difficulty.weekday.{d}: '{lvl}' is not easy/medium/hard")
    sc = cfg.get("scoring") or {}
    if not (0 < float(sc.get("decay", 0.7)) <= 1):
        p.append("scoring.decay must be in (0, 1]")
    if int((cfg.get("attempts") or {}).get("max_per_puzzle", 6)) < 1:
        p.append("attempts.max_per_puzzle must be ≥ 1")
    bad_ft = [x for x in (cfg.get("data_sources") or {}).get("allowed_file_types", []) if x in (".bin", ".pt", ".pkl", ".ckpt", ".pth")]
    if bad_ft:
        p.append(f"data_sources.allowed_file_types must not include pickle formats: {bad_ft}")
    return p
