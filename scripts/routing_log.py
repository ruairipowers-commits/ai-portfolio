"""The local-vs-Claude run log lives on its own branch, `routing-log`, so every daily run counts, including the ones
whose post is never merged (the runs where the local draft lost).

  python scripts/routing_log.py merge     # union origin/routing-log into the checkout's log (site build, skill start)
  python scripts/routing_log.py publish   # push the checkout's rows to origin/routing-log (skill, after logging)
  python scripts/routing_log.py save-queue FILE   # keep a copy of the topic queue on routing-log (skill, step 1)
  python scripts/routing_log.py queue     # print that copy and its age, for a run that can't reach the EVO-X1

The checkout's file is projects/editorial-agents/metrics/routing-runs.jsonl. Rows are deduplicated on their whole
content, so running either command twice changes nothing. `publish` never touches main: it commits to `routing-log`
in a temporary worktree and pushes that branch only.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "projects" / "editorial-agents" / "metrics" / "routing-runs.jsonl"
BRANCH, FILE = "routing-log", "routing-runs.jsonl"
QUEUE = "queue.md"
QUEUE_MAX_DAYS = 7      # an older copy is too stale to pick a topic from


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


def publish(queue: str | None = None) -> int:
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
            files = [FILE, "README.md"]
            if queue is not None:   # the topic queue as the EVO-X1 served it, with when it was read
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                (wt / QUEUE).write_text(f"<!-- saved {stamp} -->\n{queue}")
                files.append(QUEUE)
            git("add", *files, cwd=wt)
            if not git("diff", "--cached", "--quiet", cwd=wt, check=False).returncode:
                print("routing log: nothing new")
                return 0
            added = len(rows(merged)) - len(rows(branch or ""))
            what = f"+{added} run(s)" + (", topic queue" if queue is not None else "")
            git("commit", "-q", "-m", f"routing log: {what}\n\nCo-Authored-By: Claude <noreply@anthropic.com>", cwd=wt)
            git("push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=wt)
            print(f"routing log: pushed {what} to {BRANCH} ({len(rows(merged))} rows total)")
        finally:
            git("worktree", "remove", "--force", str(wt), check=False)
    return 0


def saved_queue(now: datetime | None = None) -> tuple[str, float] | None:
    """The last saved topic queue and its age in days, or None if there's none (or no network)."""
    if git("fetch", "-q", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}", check=False).returncode:
        return None
    shown = git("show", f"origin/{BRANCH}:{QUEUE}", check=False)
    if shown.returncode:
        return None
    m = re.match(r"<!-- saved (\S+) -->\n", shown.stdout)
    if not m:
        return None
    age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(m.group(1))).total_seconds() / 86400
    return shown.stdout[m.end():], age


def queue() -> int:
    got = saved_queue()
    if got is None:
        print(f"no saved topic queue on {BRANCH}", file=sys.stderr)
        return 1
    text, age = got
    if age > QUEUE_MAX_DAYS:
        print(f"the saved topic queue is {age:.1f} days old (more than {QUEUE_MAX_DAYS}); too stale to use",
              file=sys.stderr)
        return 1
    print(f"<!-- saved topic queue, {age:.1f} days old -->")
    print(text, end="")
    return 0


def _local() -> str:
    return LOG.read_text() if LOG.exists() else ""


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "merge":
        sys.exit(merge())
    if cmd == "publish":
        sys.exit(publish())
    if cmd == "save-queue" and len(sys.argv) == 3:
        sys.exit(publish(queue=Path(sys.argv[2]).read_text()))
    if cmd == "queue":
        sys.exit(queue())
    sys.exit(__doc__)
