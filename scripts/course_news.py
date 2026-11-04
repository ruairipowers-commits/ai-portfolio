"""The crash course's "What's new" items live on their own branch, `course-news`, so the daily scan never touches main
and news shows without a merge (it is factual and links its source; status badges still need a merged PR).

  python scripts/course_news.py pull      # union origin/course-news into the checkout's file (site build, scan start)
  python scripts/course_news.py publish   # push the checkout's items to origin/course-news (scan end)

The checkout's file is projects/crash-course/warehouse/news/items.jsonl: the course app's default news file when
COURSE_DATA is unset, git-ignored on main. Items are keyed on course + link + title, so running either command twice
changes nothing. `publish` commits to `course-news` in a temporary worktree and pushes that branch only.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "projects" / "crash-course" / "warehouse" / "news" / "items.jsonl"
BRANCH, FILE = "course-news", "items.jsonl"


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def key(row: dict) -> str:
    """Same identity as crash_course.news.item_id."""
    return hashlib.sha256(f"{row.get('course')}|{row.get('url')}|{str(row.get('title', '')).strip().lower()}"
                          .encode()).hexdigest()[:12]


def union(*texts: str) -> str:
    """One line per item (the first copy seen wins), ordered by date then id."""
    seen: dict[str, dict] = {}
    for t in texts:
        for ln in t.splitlines():
            if ln.strip():
                row = json.loads(ln)
                seen.setdefault(key(row), row)
    ordered = sorted(seen.items(), key=lambda kv: (kv[1].get("date", ""), kv[0]))
    return "".join(json.dumps(r, sort_keys=True) + "\n" for _, r in ordered)


def remote() -> str | None:
    """The branch's file, or None when the branch doesn't exist (or there's no network)."""
    if git("fetch", "-q", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}", check=False).returncode:
        return None
    shown = git("show", f"origin/{BRANCH}:{FILE}", check=False)
    return shown.stdout if shown.returncode == 0 else ""


def _local() -> str:
    return LOCAL.read_text() if LOCAL.exists() else ""


def pull() -> int:
    branch = remote()
    if branch is None:
        print(f"course news: no origin/{BRANCH}; using the checkout's file")
        return 0
    merged = union(_local(), branch)
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text(merged)
    print(f"course news: {merged.count(chr(10))} items (checkout + origin/{BRANCH})")
    return 0


def publish() -> int:
    branch = remote()
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
                readme.write_text("# course-news\n\nThe crash course's \"What's new\" items, one JSON line each. "
                                  "Written by the daily scan (`scripts/course_news.py publish`); read by the site build "
                                  "and the live course service (COURSE_NEWS_URL). Not merged into main.\n")
            git("add", FILE, "README.md", cwd=wt)
            if not git("diff", "--cached", "--quiet", cwd=wt, check=False).returncode:
                print("course news: nothing new")
                return 0
            added = merged.count("\n") - (branch or "").count("\n")
            git("commit", "-q", "-m", f"course news: +{added} item(s)\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                cwd=wt)
            git("push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=wt)
            print(f"course news: pushed +{added} item(s) to {BRANCH} ({merged.count(chr(10))} total)")
        finally:
            git("worktree", "remove", "--force", str(wt), check=False)
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        sys.exit(pull())
    if cmd == "publish":
        sys.exit(publish())
    sys.exit(__doc__)
