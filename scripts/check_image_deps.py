#!/usr/bin/env python3
"""Does the project's demo image have every library its code imports?

Tests run with the dev extras installed, so a library that only the tests pull in (httpx, say) can be missing
from the real image, and the app then crashes on start-up while CI stays green. This installs exactly what
Dockerfile.space installs (`pip install -e ".[extras]"`), in a fresh virtualenv, and imports every module of the
project's package.

    python scripts/check_image_deps.py projects/governance-console
Exit 0: every module imports. Exit 1: names the module and the missing library.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def install_spec(project: Path) -> str:
    dockerfile = project / "Dockerfile.space"
    m = re.search(r"pip install[^\n]*?-e\s+(\"[^\"]+\"|'[^']+'|\S+)", dockerfile.read_text()) if dockerfile.exists() else None
    return m.group(1).strip("\"'") if m else "."


def modules(project: Path) -> list[str]:
    out = []
    for pkg in sorted((project / "src").glob("*/__init__.py")):
        root = pkg.parent
        for f in sorted(root.rglob("*.py")):
            rel = f.relative_to(root.parent).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts[-1] != "__main__":
                out.append(".".join(parts))
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    project = Path(argv[0]).resolve()
    spec, mods = install_spec(project), modules(project)
    if not mods:
        print(f"{project.name}: no src/<package>, nothing to check")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        venv.create(tmp, with_pip=True)
        py = str(Path(tmp) / "bin" / "python")
        r = subprocess.run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", spec],
                           cwd=project, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])
            return 1
        code = ("import importlib, sys\nbad = []\nfor m in sys.argv[1:]:\n    try:\n        importlib.import_module(m)\n"
                "    except ModuleNotFoundError as e:\n        bad.append(f'{m}: missing {e.name}')\n"
                "print('\\n'.join(bad))\nsys.exit(1 if bad else 0)\n")
        r = subprocess.run([py, "-c", code, *mods], cwd=project, capture_output=True, text=True,
                           env={"GOVERNANCE_TELEMETRY": "off", "PATH": "/usr/bin:/bin"})
    if r.returncode:
        print(f"{project.name}: the image (pip install -e \"{spec}\") is missing libraries its code imports:")
        print(r.stdout.strip() or r.stderr[-2000:])
        print("Add them to [project] dependencies (or the extra the Dockerfile installs) in pyproject.toml.")
        return 1
    print(f"{project.name}: {len(mods)} modules import with the image's dependencies ({spec})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
