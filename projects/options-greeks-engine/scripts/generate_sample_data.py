#!/usr/bin/env python3
"""Deterministic sample requests (fictional accounts and underlying). Writes data/requests.yaml for the app's
"pick an example" list and the CLI's `all` command.

    python scripts/generate_sample_data.py
"""
from __future__ import annotations

import os
import random
from pathlib import Path

import yaml

ROOT = Path(os.getenv("OPT_ROOT") or Path(__file__).resolve().parents[1])

FIXED = [
    ("Defined-risk call spread", "Buy 20 Dec 105/115 call spreads, max debit 3.10", "DR-02"),
    ("Protective put spread", "Buy 30 Mar 95/85 put spreads for 2.40 debit", "DR-02"),
    ("Long straddle", "Buy 50 Jan 100 straddles", "FL-03"),
    ("Short strangle (unlimited loss)", "Sell 10 Feb 90/110 strangles for a 3.50 credit", "FL-03"),
    ("Naked short call, long-only", "Sell 15 Dec 120 calls", "LO-01"),
    ("Missing expiry", "Buy 10 105 calls", "FL-03"),
    ("Unlisted strike", "Buy 10 Dec 107 calls", "FL-03"),
]


def main(out: Path | None = None, seed: int = 7) -> None:
    rng = random.Random(seed)
    extra = []
    for i in range(5):
        lo = rng.choice([90, 95, 100, 105])
        n = rng.choice([5, 10, 20, 40])
        mo = rng.choice(["Jan", "Feb", "Mar", "Jun"])
        extra.append((f"Random call spread {i + 1}", f"Buy {n} {mo} {lo}/{lo + 10} call spreads", "DR-02"))
    out = out or ROOT / "data"
    out.mkdir(parents=True, exist_ok=True)
    (out / "requests.yaml").write_text(yaml.safe_dump(
        {"requests": [{"name": a, "request": b, "account": c} for a, b, c in FIXED + extra]}, sort_keys=False))
    print(f"wrote {len(FIXED) + len(extra)} sample requests to {out / 'requests.yaml'}")


if __name__ == "__main__":
    main()
