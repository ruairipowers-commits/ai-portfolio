"""Reference data: the listed chain, the vol surface and the accounts (DATA-01). Read-only at run time."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class Market:
    raw: dict

    @classmethod
    def load(cls, path: Path) -> "Market":
        return cls(yaml.safe_load(Path(path).read_text()))

    @property
    def as_of(self) -> date:
        return date.fromisoformat(self.raw["as_of"])

    @property
    def spot(self) -> float:
        return float(self.raw["spot"])

    @property
    def r(self) -> float:
        return float(self.raw["rate"])

    @property
    def q(self) -> float:
        return float(self.raw["dividend_yield"])

    @property
    def multiplier(self) -> int:
        return int(self.raw["contract_multiplier"])

    @property
    def expiries(self) -> list[str]:
        return list(self.raw["expiries"])

    @property
    def strikes(self) -> list[float]:
        k = self.raw["strikes"]
        return [float(x) for x in range(int(k["min"]), int(k["max"]) + 1, int(k["step"]))]

    def years(self, expiry: str) -> float:
        return max((date.fromisoformat(expiry) - self.as_of).days, 0) / 365.0

    def forward(self, T: float) -> float:
        return self.spot * math.exp((self.r - self.q) * T)

    def vol(self, strike: float, expiry: str) -> float:
        v = self.raw["vol_surface"]
        T = max(self.years(expiry), 1 / 365)
        m = math.log(strike / self.forward(T))
        return max(0.05, v["atm"] + v["skew"] * m + v["smile"] * m * m + v["term"] * math.sqrt(T))

    def expiry_for_month(self, token: str) -> str | None:
        """Nearest listed expiry in the named month (e.g. 'Dec' → 2026-12-18)."""
        mo = MONTHS.get(token[:3].lower())
        if not mo:
            return None
        hits = [e for e in self.expiries if date.fromisoformat(e).month == mo and date.fromisoformat(e) > self.as_of]
        return hits[0] if hits else None

    def chain_summary(self) -> dict:
        return {"underlying": self.raw["underlying"], "as_of": self.raw["as_of"], "spot": self.spot,
                "expiries": self.expiries, "strikes": self.strikes}


def load_accounts(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())["accounts"]
