#!/usr/bin/env python3
"""Does the project's demo image have every library its code imports?

Tests run with the dev extras installed, so a library that only the tests pull in (httpx, say) can be missing
from the real image, and the app then crashes on start-up while CI stays green. This installs exactly what
Dockerfile.space installs (`pip install -e ".[extras]"`), in a fresh virtualenv, reads every import in the project's
package's modules at module level, i.e. what runs on start-up (without running any project code: some modules start
services when imported), and checks each library is installed there. Imports inside functions, under
`try/except ImportError` or `if TYPE_CHECKING:` are optional and skipped.

    python scripts/check_image_deps.py projects/governance-console
Exit 0: everything imported at module level is installed. Exit 1: names each missing library and file.
"""
from __future__ import annotations

import ast
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


def required_imports(project: Path) -> dict[str, list[str]]:
    """Third-party top-level names imported at module level in src/, mapped to the files importing them."""
    own = {p.parent.name for p in (project / "src").glob("*/__init__.py")}
    found: dict[str, list[str]] = {}

    def optional(handlers) -> bool:
        for h in handlers:
            names = [h.type] if not isinstance(h.type, ast.Tuple) else h.type.elts
            if h.type is None or any(isinstance(n, ast.Name) and n.id in ("ImportError", "ModuleNotFoundError",
                                                                          "Exception") for n in names):
                return True
        return False

    def walk(node, path: str, skip: bool) -> None:
        if isinstance(node, ast.Try):
            opt = skip or optional(node.handlers)
            for n in node.body:
                walk(n, path, opt)
            for n in node.handlers + node.orelse + node.finalbody:
                walk(n, path, skip)
            return
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return   # imported only when called (e.g. a real model provider instead of the offline mock)
        if not skip and isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if node.module and not node.level else [])
            for name in names:
                top = name.split(".")[0]
                if top not in own and top not in sys.stdlib_module_names:
                    found.setdefault(top, []).append(path)
        for child in ast.iter_child_nodes(node):
            walk(child, path, skip)

    for f in sorted((project / "src").rglob("*.py")):
        walk(ast.parse(f.read_text(), str(f)), str(f.relative_to(project)), False)
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    project = Path(argv[0]).resolve()
    spec, need = install_spec(project), required_imports(project)
    if not need:
        print(f"{project.name}: no third-party imports in src/, nothing to check")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        venv.create(tmp, with_pip=True)
        py = str(Path(tmp) / "bin" / "python")
        r = subprocess.run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", spec],
                           cwd=project, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])
            return 1
        code = ("import importlib.util, sys\n"
                "print(' '.join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))\n")
        r = subprocess.run([py, "-c", code, *sorted(need)], cwd=tmp, capture_output=True, text=True)
    missing = r.stdout.split()
    if r.returncode or missing:
        print(f"{project.name}: the image (pip install -e \"{spec}\") is missing libraries its code imports:")
        for m in missing:
            print(f"  {m}  (imported in {', '.join(sorted(set(need[m])))})")
        print(r.stderr[-1000:].strip())
        print("Add them to [project] dependencies (or the extra the Dockerfile installs) in pyproject.toml.")
        return 1
    print(f"{project.name}: all {len(need)} libraries the code imports are in the image ({spec})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
