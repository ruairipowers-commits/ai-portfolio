#!/usr/bin/env python3
"""Make each project's licence files match portfolio.yaml `access` (and the repo's own, for the root).

    python scripts/apply_access.py            # rewrite what's out of date, and say what changed
    python scripts/apply_access.py --check    # CI: exit 1 if anything doesn't match the config

Per project (projects/<slug>/): LICENSE, NOTICE, the pyproject `license`, and the README's licence line.
  open                 Apache-2.0 + the credit NOTICE
  all-rights-reserved  an all-rights-reserved notice (the NOTICE stays, so credit is still clear)
  private / hidden     the same files as all-rights-reserved; the site, the Ask corpus, the demos and
                       publish_project.sh read the level themselves
Root: LICENSE and LICENSE-CONTENT follow access.repo (open: Apache-2.0 + CC BY 4.0; or all-rights-reserved).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_config import access, check_access, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIC = ROOT / "factory" / "licenses"
OPEN_LINE = ("Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you "
             "reuse it (see [NOTICE](NOTICE)).")
ARR_LINE = ("All rights reserved, by Ruairi Powers, built with Claude: the code is here to read, not to reuse without "
            "his permission (see [LICENSE](LICENSE)).")
LINE_RE = re.compile(r"^(Apache-2\.0, by Ruairi Powers, built with Claude:|All rights reserved, by Ruairi Powers, "
                     r"built with Claude:)[^\n]*?\((see \[(NOTICE|LICENSE)\]\((NOTICE|LICENSE)\))\)\.", re.M)


def arr(what: str) -> str:
    return (LIC / "all-rights-reserved.txt").read_text().replace("{what}", what)


def notice(slug: str) -> str:
    root = (ROOT / "NOTICE").read_text() if (ROOT / "NOTICE").exists() else ""
    base = root.replace("AI Workflow Portfolio\n", f"{slug} — part of the AI Workflow Portfolio\n", 1)
    return base.replace("Code: Apache License 2.0 (LICENSE). Writing, the governance standard and other site content:\n"
                        "Creative Commons Attribution 4.0 International (LICENSE-CONTENT).",
                        "Code: Apache License 2.0 (LICENSE). Docs and prose: Creative Commons Attribution 4.0\n"
                        "International (https://creativecommons.org/licenses/by/4.0/).")


def wanted(c: dict) -> dict[Path, str]:
    """Every file this script owns, with the content the config calls for."""
    out: dict[Path, str] = {}
    repo_open = access(None, c) == "open"
    out[ROOT / "LICENSE"] = (LIC / "apache-2.0.txt").read_text() if repo_open else arr("This repository")
    out[ROOT / "LICENSE-CONTENT"] = (LIC / "content-cc-by-4.0.txt").read_text() if repo_open else \
        arr("The writing on this site (site/, governance/, factory/)")
    for proj in sorted(p for p in (ROOT / "projects").iterdir() if p.is_dir() and (p / "pyproject.toml").exists()):
        level = access(proj.name, c)
        is_open = level == "open"
        out[proj / "LICENSE"] = (LIC / "apache-2.0.txt").read_text() if is_open else arr(f"The {proj.name} project")
        if (ROOT / "NOTICE").exists():
            out[proj / "NOTICE"] = notice(proj.name)
        py = (proj / "pyproject.toml").read_text()
        text = "Apache-2.0" if is_open else "All rights reserved"
        out[proj / "pyproject.toml"] = re.sub(r'(?m)^license = \{text = "[^"]*"\}', f'license = {{text = "{text}"}}', py)
        readme = proj / "README.md"
        if readme.exists():
            r = readme.read_text()
            line = OPEN_LINE if is_open else ARR_LINE
            r = LINE_RE.sub(line, r, count=1) if LINE_RE.search(r) else r.rstrip() + f"\n\n## License\n\n{line}\n"
            out[readme] = r
    return out


def main(argv: list[str]) -> int:
    c = resolve()
    check_access(c)
    stale = [p for p, text in wanted(c).items() if not p.exists() or p.read_text() != text]
    if "--check" in argv:
        for p in stale:
            print(f"out of date with portfolio.yaml access: {p.relative_to(ROOT)}  (run: python scripts/apply_access.py)")
        if not stale:
            print("licence files match portfolio.yaml access")
        return 1 if stale else 0
    for p in stale:
        p.write_text(wanted(c)[p])
        print(f"updated {p.relative_to(ROOT)}")
    levels = {s: access(s, c) for s in c["projects"]}
    print(f"repo: {access(None, c)}; projects: " + ", ".join(f"{s}={v}" for s, v in levels.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
