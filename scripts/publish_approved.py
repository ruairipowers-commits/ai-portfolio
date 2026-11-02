"""Publish the posts Ruairi approved from their emails: one a day, oldest approval first.

    GITHUB_TOKEN=… GITHUB_REPOSITORY=owner/name EDITORIAL_URL=https://… python3 scripts/publish_approved.py [--dry-run]

Run by .github/workflows/publish-approved.yml. The editorial service emails each post and records each Approve / Archive click (signed,
single-use links, HITL-02) and serves them at /api/decisions; it holds no GitHub credentials. This script, with the
workflow's own token:
  1. labels the open draft-post PRs `approved` or `archived` to match his decisions (and clears both for the rest),
  2. from PUBLISH_FROM_HOUR (UTC) on, merges the oldest approved PR if fewer than PUBLISH_PER_DAY draft posts were
     merged today (UTC), so a delayed or skipped scheduled run is caught up by the next hourly one,
  3. starts the site build (a merge made with the workflow token doesn't trigger `on: push` workflows).
It only merges a PR that is labelled draft-post, targets the default branch, comes from a branch of this repo, adds
exactly one file under site/blog/posts/, and whose head commit is the one he approved (the merge is pinned to that
commit, so GitHub refuses it if the branch moved). A post changed after approval goes back to waiting.
Nothing approved: a warning. Approved posts but none merged: the run fails, so GitHub emails about it.
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
TOPIC = re.compile(r"(?im)^\s*Topic:\s*`?([0-9a-f]{16})`?")
POST_FILE = re.compile(r"^site/blog/posts/[^/]+\.md$")
LABELS = {"approved": ("2e7d32", "Ruairi approved it from the email; publishes in turn"),
          "archived": ("90a4ae", "Ruairi archived it; approve later from the email to publish")}


def http(method: str, url: str, body: dict | None = None, token: str = "") -> tuple[int, object]:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "publish-approved")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as ex:
        raw = ex.read()
        try:
            return ex.code, json.loads(raw)
        except ValueError:
            return ex.code, raw.decode(errors="replace")


class GitHub:
    def __init__(self, repo: str, token: str, dry: bool):
        self.repo, self.token, self.dry = repo, token, dry

    def get(self, path: str):
        code, data = http("GET", f"{API}/repos/{self.repo}{path}", token=self.token)
        if code != 200:
            raise RuntimeError(f"GET {path}: {code} {data}")
        return data

    def write(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        if self.dry:
            print(f"[dry-run] {method} {path} {json.dumps(body) if body else ''}")
            return 200, {}
        return http(method, f"{API}/repos/{self.repo}{path}", body if body is not None else {}, self.token)


def plan(decisions: dict, prs: list[dict], repo: str, base: str = "main") -> dict:
    """Pure: which labels to set and which PRs may be merged (number, approved commit), in order. Unit-tested."""
    ours = {}
    for pr in sorted(prs, key=lambda p: p["number"]):           # two open PRs for one topic: the newest counts
        names = {lb["name"] for lb in pr.get("labels", [])}
        m = TOPIC.search(pr.get("body") or "")
        if ("draft-post" in names and m and (pr.get("head") or {}).get("repo", {}).get("full_name") == repo
                and (pr.get("base") or {}).get("ref") == base):
            ours[m.group(1)] = pr
    state = {}
    for kind in ("approved", "archived", "waiting"):
        for d in decisions.get(kind, []):
            pr = ours.get(d.get("topic_id"))
            if not pr or d.get("pr") not in (None, pr["number"]):
                continue
            if kind == "approved" and d.get("sha") != pr["head"].get("sha"):
                kind_here = "waiting"                           # changed since he approved it, or no commit recorded
            else:
                kind_here = kind
            state.setdefault(pr["number"], kind_here)
    labels = {}
    for pr in ours.values():
        want = state.get(pr["number"], "waiting")
        have = {lb["name"] for lb in pr.get("labels", [])} & set(LABELS)
        add = {want} - have if want in LABELS else set()
        labels[pr["number"]] = {"add": sorted(add), "remove": sorted(have - {want})}
    order = [(ours[d["topic_id"]]["number"], d["sha"]) for d in decisions.get("approved", [])
             if d.get("topic_id") in ours and state.get(ours[d["topic_id"]]["number"]) == "approved"]
    return {"labels": labels, "merge_order": order}


def merged_today(prs_closed: list[dict]) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for pr in prs_closed if (pr.get("merged_at") or "").startswith(today)
               and "draft-post" in {lb["name"] for lb in pr.get("labels", [])})


def only_adds_one_post(files: list[dict]) -> bool:
    return len(files) == 1 and files[0].get("status") == "added" and bool(POST_FILE.match(files[0].get("filename", "")))


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_TOKEN", "")
    base = os.environ.get("EDITORIAL_URL", "").rstrip("/")
    per_day = int(os.environ.get("PUBLISH_PER_DAY") or 1)
    from_hour = int(os.environ.get("PUBLISH_FROM_HOUR") or 13)
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if not manual and datetime.now(timezone.utc).hour < from_hour:
        per_day = 0                                             # labels only before the publishing hour
    if not base:
        print("::error::EDITORIAL_URL secret is not set; can't read Ruairi's decisions")
        return 1
    try:
        code, decisions = http("GET", f"{base}/api/decisions")
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        print(f"::error::editorial service not reachable ({ex}); nothing changed")
        return 1
    if code != 200 or not isinstance(decisions, dict):
        print(f"::error::editorial service /api/decisions answered {code}; nothing changed")
        return 1
    gh = GitHub(repo, token, dry)
    prs = gh.get("/pulls?state=open&per_page=100")
    p = plan(decisions, prs, repo, os.environ.get("DEFAULT_BRANCH") or "main")

    for name, (color, desc) in LABELS.items():
        if http("GET", f"{API}/repos/{repo}/labels/{name}", token=token)[0] == 404:
            gh.write("POST", "/labels", {"name": name, "color": color, "description": desc})
    for n, ch in p["labels"].items():
        if ch["add"]:
            gh.write("POST", f"/issues/{n}/labels", {"labels": ch["add"]})
        for lb in ch["remove"]:
            gh.write("DELETE", f"/issues/{n}/labels/{lb}")

    room = per_day - merged_today(gh.get("/pulls?state=closed&sort=updated&direction=desc&per_page=50"))
    merged = []
    for n, sha in p["merge_order"]:
        if room <= 0:
            break
        if not only_adds_one_post(gh.get(f"/pulls/{n}/files")):
            print(f"::warning::PR #{n} is approved but doesn't add exactly one post file; not merging it")
            continue
        code, out = gh.write("PUT", f"/pulls/{n}/merge", {"merge_method": "merge", "sha": sha})
        if code == 200:
            merged.append(n)
            room -= 1
            print(f"merged #{n}")
        else:
            print(f"::warning::PR #{n} is approved but GitHub refused the merge ({code}: {out}); trying the next one")
    if merged:
        code, out = gh.write("POST", "/actions/workflows/site.yml/dispatches", {"ref": "main"})
        if code not in (200, 204):
            print(f"::warning::couldn't start the site build ({code}: {out}); the daily 15:40 UTC build will publish it")
    summary = (f"Approved: {len(p['merge_order'])} · merged now: {', '.join(f'#{n}' for n in merged) or 'none'} · "
               f"waiting for Ruairi: {len(decisions.get('waiting', []))} · archived: {len(decisions.get('archived', []))}")
    if not p["merge_order"] and room > 0:
        print("::warning::Nothing approved, so nothing published today. Approve a post from its email.")
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")
    if p["merge_order"] and room > 0 and not merged:
        print("::error::approved posts are waiting but none could be merged (see the warnings above)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
