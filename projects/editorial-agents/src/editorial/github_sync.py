"""Close the loop from the blog repo, read-only and unauthenticated (the repo is public; the host holds no GitHub
write credentials, NFR-1).

A post's pull request carries `Topic: <id>` in its body and the label `draft-post` (waiting for the owner) or
`auto-published` (the daily writer merged it after every check passed).
  open PR      → topic drafted (or kept approved / archived: the owner's decision from the post's email; an approval
                 lapses back to drafted if the PR's head commit changed after he approved it)
  merged PR    → topic published
  closed, not merged → topic dismissed (the owner dropped it)
Each new open draft-post PR is also emailed to the owner once, with Approve / Archive links (postmail.py).
"""
from __future__ import annotations

import json
import re

from . import postmail
from .config import repo
from .sources import http_get
from .store import Store

LABELS = {"draft-post", "auto-published"}
TOPIC = re.compile(r"(?im)^\s*Topic:\s*`?([0-9a-f]{16})`?")


RANK = {"merged": 3, "open": 2, "closed": 1}      # a topic with several PRs follows the merged one, else the open one


def _pages(get, max_pages: int = 4) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = json.loads(get(f"https://api.github.com/repos/{repo()}/pulls?state=all&per_page=50&page={page}",
                              headers={"Accept": "application/vnd.github+json"}))
        out += rows
        if len(rows) < 50:
            break
    return out


def sync(store: Store, get=http_get, email: bool = True) -> dict:
    best: dict[str, dict] = {}
    for pr in _pages(get):
        if not any(lb.get("name") in LABELS for lb in pr.get("labels", [])):
            continue
        m = TOPIC.search(pr.get("body") or "")
        if not m or not store.topic(m.group(1)):
            continue
        kind = "merged" if pr.get("merged_at") else ("open" if pr.get("state") == "open" else "closed")
        old = best.get(m.group(1))
        if not old or (RANK[kind], pr.get("number", 0)) > (RANK[old[0]], old[1].get("number", 0)):
            best[m.group(1)] = (kind, pr)
    changed = {}
    for tid, (kind, pr) in best.items():
        cur = store.topic(tid)["status"]
        state = {"merged": "published", "open": "drafted", "closed": "dismissed"}[kind]
        sha = (pr.get("head") or {}).get("sha", "")
        info = {"number": pr.get("number"), "url": pr.get("html_url"), "title": pr.get("title", ""), "sha": sha}
        if state == "drafted" and cur in ("approved", "archived"):
            state = cur                                 # still open: the owner's decision stands until it's merged
            if cur == "approved" and sha and store.decision_sha(tid) not in ("", sha):
                state = "drafted"                       # changed since he approved it: he decides again
        if store.get_kv(f"pr:{tid}") != info:
            store.set_kv(f"pr:{tid}", info)
        if cur != state:
            store.set_status(tid, state, rank=None)
            store.action(tid, "approval_stale" if cur == "approved" and state == "drafted" else state, "github",
                         {"pr": pr.get("number"), "url": pr.get("html_url"), "sha": sha})
            changed[tid] = state
    open_posts = {tid: pr for tid, (kind, pr) in best.items()
                  if kind == "open" and any(lb.get("name") == "draft-post" for lb in pr.get("labels", []))}
    emailed = postmail.notify(store, open_posts, get) if email else []
    store.run("github_sync", "ok", {"changed": changed, "emailed": emailed})
    return changed
