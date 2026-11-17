#!/usr/bin/env python3
"""Deterministic, seeded synthetic tick data. Writes data/ticks/default.parquet (+ a no-edge file and a CSV example).

    python scripts/generate_sample_data.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(os.getenv("BT_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT / "src"))
from event_backtester.data import synthetic_ticks  # noqa: E402


def main(out: Path | None = None) -> None:
    d = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())["dataset"]
    out = out or ROOT / "data" / "ticks"
    out.mkdir(parents=True, exist_ok=True)
    kw = dict(days=d["days"], ticks_per_day=d["ticks_per_day"], seed=d["seed"])
    t = synthetic_ticks(trend_strength=d["trend_strength"], **kw)
    t.to_parquet(out / "default.parquet", index=False)
    synthetic_ticks(trend_strength=0.0, **kw).to_parquet(out / "no_edge.parquet", index=False)
    t.head(5000)[["ts", "bid", "ask", "volume"]].to_csv(out / "upload_example.csv", index=False)
    print(f"wrote {len(t):,} ticks to {out / 'default.parquet'} (+ no_edge.parquet, upload_example.csv)")


if __name__ == "__main__":
    main()
