"""Regenerate projects/governance-console/catalog/workflows.json from the portfolio (projects, specs, mappings).

The console reads the portfolio live when it runs inside this repo; the bundled JSON is what a published or
hosted console uses. CI runs this with --check so the bundled copy can't drift.
    python scripts/build_catalog.py [--check]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "projects" / "governance-console" / "src"))
from govconsole import catalog  # noqa: E402


def main(check: bool) -> int:
    if check:
        live = catalog.build_from_portfolio(ROOT)
        live["generated_from"] = "catalog/workflows.json (scripts/build_catalog.py)"
        same = catalog.BUNDLED.exists() and json.loads(catalog.BUNDLED.read_text()) == json.loads(json.dumps(live))
        print("governance catalog:", "OK" if same else "out of date (run scripts/build_catalog.py)")
        return 0 if same else 1
    p = catalog.write_bundled(ROOT)
    c = json.loads(p.read_text())
    print(f"Wrote {p.relative_to(ROOT)}: {len(c['workflows'])} workflows × {len(c['controls'])} controls")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
