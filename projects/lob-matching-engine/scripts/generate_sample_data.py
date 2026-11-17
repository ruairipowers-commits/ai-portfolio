#!/usr/bin/env python3
"""Deterministic, seeded synthetic sessions (fictional traders). Writes data/sessions/*.csv.

    python scripts/generate_sample_data.py            # default.csv (all four behaviours) + clean.csv + upload example
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(os.getenv("LOB_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT / "src"))
from lob_matching_engine import sessions  # noqa: E402


def main(out: Path | None = None) -> None:
    s = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())["session"]
    out = out or ROOT / "data" / "sessions"
    out.mkdir(parents=True, exist_ok=True)
    df = sessions.generate(seed=s["seed"], noise_commands=s["noise_commands"], behaviours=tuple(s["behaviours"]))
    df.to_csv(out / "default.csv", index=False)
    sessions.generate(seed=s["seed"], noise_commands=s["noise_commands"], behaviours=()).to_csv(out / "clean.csv", index=False)
    df.head(400).to_csv(out / "upload_example.csv", index=False)
    print(f"wrote {len(df):,} commands to {out / 'default.csv'} (+ clean.csv, upload_example.csv)")


if __name__ == "__main__":
    main()
