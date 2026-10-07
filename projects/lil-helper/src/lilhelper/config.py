"""Settings, the household file, stores and money: loaded once per run, all plain YAML anyone can edit."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(os.getenv("LILHELPER_ROOT") or Path(__file__).resolve().parents[2])
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MEALS = ["breakfast", "lunch", "dinner"]


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def work_root() -> Path:
    """Where runs write (output, logs, warehouse): the visitor's sandbox in the hosted demo, else the project."""
    from . import demo
    return demo.current() or ROOT


@dataclass
class Person:
    id: str
    name: str
    age_band: str
    portion: float = 1.0
    age: int | None = None
    allergies: list[str] = field(default_factory=list)
    diet: list[str] = field(default_factory=list)
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    home: list[str] = field(default_factory=lambda: list(DAYS))
    can_cook: bool = False
    email: str | None = None            # adults only: where the sign-in link goes

    @property
    def is_kid(self) -> bool:
        return self.age_band == "kid"

    @property
    def years(self) -> int:
        return self.age if self.age is not None else (18 if not self.is_kid else 8)

    def label(self, share_names: bool) -> str:
        """What a model sees: never a child's name unless the household opts in (DATA-03)."""
        if share_names:
            return self.name
        return f"kid ({self.age})" if self.is_kid and self.age else ("kid" if self.is_kid else "adult")


@dataclass
class Pet:
    id: str
    name: str
    species: str
    weight_kg: float
    food: dict
    treats_per_day: int
    kcal_per_day: float
    extras: bool
    vet_notes: str = ""


@dataclass
class Household:
    raw: dict
    people: dict[str, Person]
    pets: dict[str, Pet]

    @property
    def info(self) -> dict:
        return self.raw["household"]

    @property
    def meals(self) -> dict:
        return self.raw["meals"]

    def eaters(self, meal: str) -> list[Person]:
        e = self.meals.get(meal, {}).get("eaters", "all")
        return list(self.people.values()) if e == "all" else [self.people[p] for p in e]

    def slots(self) -> list[tuple[str, str]]:
        """(day, meal) pairs to plan, in calendar order, excluding special nights."""
        special = self.meals.get("special_nights", {}) or {}
        out = []
        for day in DAYS:
            for meal in MEALS:
                cfg = self.meals.get(meal)
                if cfg and day in cfg.get("days", []) and not (meal == "dinner" and day in special):
                    out.append((day, meal))
        return out

    def special_nights(self) -> dict[str, str]:
        return dict(self.meals.get("special_nights", {}) or {})

    def prep_limit(self, day: str) -> int:
        return int(self.raw.get("prep_minutes", {}).get(day, 60))


def load_household(path: Path | None = None) -> Household:
    s = Settings.load()
    p = path or ROOT / s["household_file"]
    if not p.exists():
        p = ROOT / "config" / "household.example.yaml"
    raw = _read(p)
    validate_household(raw, s)
    people = {pid: Person(id=pid, **{k: v for k, v in d.items() if k in Person.__dataclass_fields__})
              for pid, d in raw["people"].items()}
    pets = {pid: Pet(id=pid, name=d["name"], species=d["species"], weight_kg=d.get("weight_kg", 0), food=d["food"],
                     treats_per_day=d.get("treats_per_day", 0), kcal_per_day=d.get("kcal_per_day", 0),
                     extras=d.get("extras", False), vet_notes=d.get("vet_notes", "") or "")
            for pid, d in (raw.get("pets") or {}).items()}
    return Household(raw, people, pets)


class HouseholdError(ValueError):
    pass


def validate_household(raw: dict, s: "Settings") -> None:
    """Refuse a household file that holds card numbers, or meals for people who don't exist."""
    pat = re.compile(s["privacy"]["card_number_pattern"])
    for c in raw.get("cards", []) or []:
        if pat.search(str(c)):
            raise HouseholdError("A card field looks like a card number. Use a name you'd recognise, never the number.")
    people = set(raw.get("people", {}))
    for meal, cfg in (raw.get("meals") or {}).items():
        if isinstance(cfg, dict) and isinstance(cfg.get("eaters"), list):
            unknown = set(cfg["eaters"]) - people
            if unknown:
                raise HouseholdError(f"{meal}: unknown eaters {sorted(unknown)}")


class Settings(dict):
    @classmethod
    def load(cls) -> "Settings":
        return cls(_read(ROOT / "config" / "settings.yaml"))


def stores() -> dict:
    return _read(ROOT / "config" / "stores.yaml")


def money() -> dict:
    return _read(ROOT / "config" / "money.yaml")
