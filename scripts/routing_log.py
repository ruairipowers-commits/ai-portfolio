"""The local-vs-Claude run log lives on its own branch, `routing-log`, so every daily run counts, including the ones
whose post is never merged (the runs where the local draft lost).

  python scripts/routing_log.py merge     # union origin/routing-log into the checkout's log (site build, skill start)
  python scripts/routing_log.py publish   # push the checkout's rows to origin/routing-log (skill, after logging)

The checkout's file is projects/editorial-agents/metrics/routing-runs.jsonl. Rows are deduplicated on their whole
content, so running either command twice changes nothing. `publish` never touches main: it commits to `routing-log`
in a temporary worktree and pushes that branch only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "projects" / "editorial-agents" / "metrics" / "routing-runs.jsonl"
BRANCH, FILE = "routing-log", "routing-runs.jsonl"


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def rows(text: str) -> list[str]:
    return [json.dumps(json.loads(ln), sort_keys=True) for ln in text.splitlines() if ln.strip()]


def union(*texts: str) -> str:
    """Every distinct row, oldest first (by timestamp, then content)."""
    seen = {r for t in texts for r in rows(t)}
    ordered = sorted(seen, key=lambda r: (json.loads(r).get("ts", ""), r))
    return "".join(r + "\n" for r in ordered)


def remote_log() -> str | None:
    """The branch's log, or None when the branch doesn't exist (or there's no network)."""
    if git("fetch", "-q", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}", check=False).returncode:
        return None
    shown = git("show", f"origin/{BRANCH}:{FILE}", check=False)
    return shown.stdout if shown.returncode == 0 else ""


def merge() -> int:
    branch = remote_log()
    if branch is None:
        print(f"routing log: no origin/{BRANCH}; using the checkout's {len(rows(_local()))} rows")
        return 0
    merged = union(_local(), branch)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(merged)
    print(f"routing log: {len(rows(merged))} rows (checkout + origin/{BRANCH})")
    return 0


def publish() -> int:
    branch = remote_log()
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        if branch is None:   # first run: start the branch with no history of its own
            git("worktree", "add", "-q", "--detach", str(wt))
            git("checkout", "-q", "--orphan", BRANCH, cwd=wt)
            git("rm", "-rq", "--cached", ".", cwd=wt)
            for p in wt.iterdir():
                if p.name != ".git":
                    subprocess.run(["rm", "-rf", str(p)], check=True)
        else:
            git("worktree", "add", "-q", "-B", BRANCH, str(wt), f"origin/{BRANCH}")
        try:
            merged = union(branch or "", _local())
            (wt / FILE).write_text(merged)
            readme = wt / "README.md"
            if not readme.exists():
                readme.write_text("# routing-log\n\nOne row per daily post run, local-vs-Claude comparison. Written by "
                                  "`scripts/routing_log.py publish`; read by the site build. Not merged into main.\n")
            git("add", FILE, "README.md", cwd=wt)
            if not git("diff", "--cached", "--quiet", cwd=wt, check=False).returncode:
                print("routing log: nothing new")
                return 0
            added = len(rows(merged)) - len(rows(branch or ""))
            git("commit", "-q", "-m", f"routing log: +{added} run(s)\n\nCo-Authored-By: Claude <noreply@anthropic.com>", cwd=wt)
            git("push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=wt)
            print(f"routing log: pushed {added} new row(s) to {BRANCH} ({len(rows(merged))} total)")
        finally:
            git("worktree", "remove", "--force", str(wt), check=False)
    return 0


def _local() -> str:
    return LOG.read_text() if LOG.exists() else ""


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("merge", "publish"):
        sys.exit(__doc__)
    sys.exit(merge() if cmd == "merge" else publish())
