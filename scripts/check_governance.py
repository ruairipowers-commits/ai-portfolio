"""Fail if any project's docs/governance.md does not map every control in governance/controls.md.

Usage: python scripts/check_governance.py [project-slug ...]
Run in CI on the portfolio repo and inside each published project repo (it only needs
the controls file and the project folder).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"\b((?:DATA|SEC|COST|MODEL|EVAL|OBS|HITL)-\d{2})\b")
STATUS = re.compile(r"(✅|🟡|⚪|🔷)")


def control_ids() -> list[str]:
    text = (ROOT / "governance" / "controls.md").read_text()
    return [m.group(1) for line in text.splitlines() if line.startswith("| ") and (m := ID.search(line))]


def check(slug: str, ids: list[str]) -> list[str]:
    path = ROOT / "projects" / slug / "docs" / "governance.md"
    if not path.exists():
        return [f"{slug}: missing docs/governance.md"]
    rows = {}
    for line in path.read_text().splitlines():
        if line.startswith("| ") and (m := ID.search(line.split("|")[1])):
            rows[m.group(1)] = line
    problems = [f"{slug}: {cid} not mapped" for cid in ids if cid not in rows]
    problems += [f"{slug}: {cid} has no status marker" for cid, line in rows.items() if not STATUS.search(line)]
    problems += [f"{slug}: {cid} is not in the standard (renamed/removed?)" for cid in rows if cid not in ids]
    return problems


def main(argv: list[str]) -> int:
    ids = control_ids()
    slugs = argv or sorted(p.name for p in (ROOT / "projects").iterdir() if p.is_dir())
    problems = [p for s in slugs for p in check(s, ids)]
    for p in problems:
        print("✗", p)
    print(f"{len(ids)} controls × {len(slugs)} project(s): {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
