"""Close the loop from the blog repo, read-only and unauthenticated (the repo is public; the host holds no GitHub
write credentials, NFR-1).

A draft post's pull request carries `Topic: <id>` in its body and the label `draft-post`.
  open PR      → topic drafted
  merged PR    → topic published
  closed, not merged → topic dismissed (the owner dropped it)
"""
from __future__ import annotations

import json
import re

from .config import repo
from .sources import http_get
from .store import Store

TOPIC = re.compile(r"(?im)^\s*Topic:\s*`?([0-9a-f]{16})`?")


def sync(store: Store, get=http_get) -> dict:
    prs = json.loads(get(f"https://api.github.com/repos/{repo()}/pulls?state=all&per_page=50",
                         headers={"Accept": "application/vnd.github+json"}))
    changed = {}
    for pr in prs:
        if not any(lb.get("name") == "draft-post" for lb in pr.get("labels", [])):
            continue
        m = TOPIC.search(pr.get("body") or "")
        if not m or not store.topic(m.group(1)):
            continue
        tid = m.group(1)
        state = "published" if pr.get("merged_at") else ("drafted" if pr.get("state") == "open" else "dismissed")
        if store.topic(tid)["status"] != state:
            store.set_status(tid, state, rank=None)
            store.action(tid, state, "github", {"pr": pr.get("number"), "url": pr.get("html_url")})
            changed[tid] = state
    store.run("github_sync", "ok", {"changed": changed})
    return changed
