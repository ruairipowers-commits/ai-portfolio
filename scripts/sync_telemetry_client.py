"""Keep every workflow's telemetry client identical to the console's reference copy.

    python scripts/sync_telemetry_client.py          # write projects/<slug>/src/<pkg>/telemetry.py for every workflow
    python scripts/sync_telemetry_client.py --check  # CI: fail if any copy drifted

Only the PROJECT line differs between copies. Platform projects (spec `kind: platform`) are skipped.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "projects" / "governance-console" / "clients" / "python" / "telemetry.py"


def targets() -> list[tuple[str, Path]]:
    out = []
    for proj in sorted(p for p in (ROOT / "projects").iterdir() if p.is_dir()):
        spec = ROOT / "specs" / f"{proj.name}.yaml"
        if spec.exists() and (yaml.safe_load(spec.read_text()) or {}).get("kind") == "platform":
            continue
        pkgs = [d for d in (proj / "src").glob("*") if (d / "__init__.py").exists()] if (proj / "src").exists() else []
        if len(pkgs) == 1:
            out.append((proj.name, pkgs[0] / "telemetry.py"))
    return out


def render(slug: str) -> str:
    return re.sub(r'(?m)^PROJECT = ".*"$', f'PROJECT = "{slug}"', REFERENCE.read_text(), count=1)


def main(check: bool) -> int:
    drift = []
    for slug, path in targets():
        want = render(slug)
        if not path.exists() or path.read_text() != want:
            if check:
                drift.append(str(path.relative_to(ROOT)))
            else:
                path.write_text(want)
                print("wrote", path.relative_to(ROOT))
    for d in drift:
        print("✗ out of date:", d)
    if check:
        print("telemetry clients:", "OK" if not drift else f"{len(drift)} out of date (run scripts/sync_telemetry_client.py)")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
