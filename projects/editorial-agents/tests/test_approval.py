"""Approve / archive from each post's email; the publish workflow merges the oldest approval, one a day.

Covers the service side (post email, links, /act, /api/decisions, GitHub sync, digest) and the repo script that acts on
the decisions: scripts/publish_approved.py (labels and merges).
"""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from editorial import digest, github_sync, links, postmail
from editorial.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


publish = _script("publish_approved")


def _pr(n, tid, state="open", merged=None, labels=("draft-post",), repo="o/ai-portfolio", sha=None, base="main"):
    return {"number": n, "state": state, "merged_at": merged, "title": f"Post {n}", "html_url": f"https://gh/pr/{n}",
            "labels": [{"name": x} for x in labels], "body": f"Topic: `{tid}`", "base": {"ref": base},
            "head": {"repo": {"full_name": repo}, "sha": sha or f"sha{n}"}}


def _sync(store, prs):
    return github_sync.sync(store, get=lambda url, **kw: json.dumps(prs))


@pytest.fixture()
def drafted(scouted):
    """Three queue topics with open draft-post PRs, as the 30-minute GitHub sync would see them."""
    store, _ = scouted
    q = store.queue()[:3]
    prs = [_pr(10 + i, t["id"]) for i, t in enumerate(q)]
    github_sync.sync(store, get=lambda url, **kw: json.dumps(prs))
    return store, [t["id"] for t in q], prs


def _click(c, tid, action):
    tok = links.sign(tid, action)
    assert c.get(f"/act?t={tok}").status_code == 200
    return c.post("/act", data={"t": tok}).text


POST_MD = ("---\ndate: 2026-11-02\n---\n# A title\n\nFirst **para** with [a link](https://x.org).\n\n<!-- more -->\n\n"
           "## Later\n\n- one\n- two\n\nLast para.\n")


def test_post_email_carries_the_whole_post_and_working_links(scouted):
    store, _ = scouted
    tid = store.queue()[0]["id"]
    pr = {**_pr(12, tid, labels=("draft-post", "needs-work")), "body": f"Topic: `{tid}`\n<!-- scorecard -->\n"
          "| check | result |\n|---|---|\n| sources | 3 |\n<!-- /scorecard -->"}
    mail = postmail.compose(tid, pr, postmail.parse_post(POST_MD, "x"))
    assert mail["subject"] == "Draft needs work: A title"
    assert "Last para." in mail["text"] and "<li>one</li>" in mail["html"] and '<a href="https://x.org">a link</a>' \
        in mail["html"] and "<b>para</b>" in mail["html"] and ">sources<" in mail["html"]
    tok = mail["text"].split("Approve: ")[1].split()[0].split("/act?t=")[1]
    assert links.verify(tok)["action"] == "approve" and links.verify(tok)["topic_id"] == tid


def test_sync_emails_each_new_post_once(scouted):
    store, _ = scouted
    q = store.queue()
    prs = [_pr(20, q[0]["id"]), _pr(21, q[1]["id"])]
    files = {20: [{"filename": "site/blog/posts/a.md", "status": "added"}],
             21: [{"filename": "scripts/x.py", "status": "added"}]}
    seen = []

    def get(url, **kw):
        seen.append(url)
        if url.endswith("/files"):
            return json.dumps(files[int(url.split("/")[-2])])
        if "raw.githubusercontent.com" in url:
            assert "/sha20/site/blog/posts/a.md" in url            # the PR's head commit, not a branch name
            return POST_MD
        return json.dumps(prs)

    github_sync.sync(store, get=get)
    outbox = sorted((Path(store.path).parent / "outbox").glob("*.eml"))
    assert len(outbox) == 1 and "draft-ready-a-title" in outbox[0].name
    assert store.get_kv("emailed:21") == {"skipped": "no new post file"}
    github_sync.sync(store, get=get)
    assert len(list((Path(store.path).parent / "outbox").glob("*.eml"))) == 1     # once per PR


def test_approve_and_archive_from_the_post_email(drafted):
    store, (a, b, c3), _ = drafted
    c = TestClient(create_app(store, background=False))
    tok = links.sign(b, "approve")
    assert "Approve this post" in c.get(f"/act?t={tok}").text and store.topic(b)["status"] == "drafted"
    assert "approved" in c.post("/act", data={"t": tok}).text
    assert "approved" in _click(c, a, "approve")
    assert "archived" in _click(c, c3, "archive")
    d = c.get("/api/decisions").json()
    assert [x["topic_id"] for x in d["approved"]] == [b, a]           # oldest approval publishes first
    assert d["approved"][0]["pr"] == 11 and [x["topic_id"] for x in d["archived"]] == [c3]
    assert "already approved" in _click(c, b, "approve")
    assert "approved" in _click(c, c3, "approve")                      # an archived post can be approved later
    acts = store.query("select action, actor from actions where action in ('approve', 'archive')")
    assert len(acts) == 4 and all(x["actor"] == "owner (signed email link)" for x in acts)


def test_sync_keeps_decisions_while_open_and_publishes_on_merge(drafted):
    store, (a, b, _c3), prs = drafted
    c = TestClient(create_app(store, background=False))
    _click(c, a, "approve")
    _click(c, b, "archive")
    github_sync.sync(store, get=lambda url, **kw: json.dumps(prs))
    assert store.topic(a)["status"] == "approved" and store.topic(b)["status"] == "archived"
    prs[0].update(state="closed", merged_at="2026-11-03T13:20:00Z")
    github_sync.sync(store, get=lambda url, **kw: json.dumps(prs))
    assert store.topic(a)["status"] == "published"
    assert "already published" in c.get(f"/act?t={links.sign(a, 'archive')}").text


def test_post_link_before_the_sync_saw_the_pr_syncs_once(scouted, monkeypatch):
    store, _ = scouted
    tid = store.queue()[0]["id"]
    calls = []
    monkeypatch.setattr(github_sync, "sync", lambda s: calls.append(1) or s.set_status(tid, "drafted"))
    c = TestClient(create_app(store, background=False))
    assert "approved" in _click(c, tid, "approve") and calls


def test_digest_shows_the_publishing_line_and_warns_when_nothing_is_approved(drafted):
    store, (a, b, _c3), _ = drafted
    mail = digest.render(store)
    assert mail["subject"].startswith("0 approved, 3 waiting")
    assert "nothing publishes tomorrow" in mail["html"] and "Waiting for your decision (3)" in mail["text"]
    c = TestClient(create_app(store, background=False))
    _click(c, a, "approve")
    _click(c, b, "archive")
    mail = digest.render(store)
    assert "nothing publishes" not in mail["html"] and "Archived (1)" in mail["text"]
    tok = mail["text"].split("Archived (1):")[1].split("Approve: ")[1].split("/act?t=")[1].split()[0]
    assert links.verify(tok) == {"topic_id": b, "action": "approve", "nonce": links.verify(tok)["nonce"]}


def test_publish_plan_orders_approvals_and_ignores_prs_that_are_not_ours():
    repo = "o/ai-portfolio"
    prs = [_pr(1, "a" * 16, labels=("draft-post", "archived")), _pr(2, "b" * 16), _pr(3, "c" * 16),
           _pr(4, "d" * 16, repo="fork/ai-portfolio"), _pr(5, "e" * 16, labels=()), _pr(6, "f" * 16, base="other"),
           _pr(7, "9" * 16)]
    ap = lambda t, n, sha=None: {"topic_id": t * 16, "pr": n, "sha": sha or f"sha{n}"}
    decisions = {"approved": [ap("c", 3), ap("a", 1), ap("d", 4), ap("e", 5), ap("f", 6),
                              ap("b", 99),                      # wrong PR number: not trusted
                              ap("9", 7, sha="older")],         # changed since he approved it
                 "archived": [], "waiting": [{"topic_id": "b" * 16, "pr": 2}]}
    p = publish.plan(decisions, prs, repo)
    assert p["merge_order"] == [(3, "sha3"), (1, "sha1")]          # pinned to the approved commits
    assert p["labels"][1] == {"add": ["approved"], "remove": ["archived"]}
    assert p["labels"][2] == {"add": [], "remove": []} and p["labels"][7] == {"add": [], "remove": []}
    assert not {4, 5, 6} & set(p["labels"])


def test_an_approval_lapses_if_the_post_changes_after_it(drafted):
    store, (a, _b, _c3), prs = drafted
    c = TestClient(create_app(store, background=False))
    _click(c, a, "approve")
    assert c.get("/api/decisions").json()["approved"][0]["sha"] == "sha10"
    _sync(store, prs)
    assert store.topic(a)["status"] == "approved"
    prs[0]["head"]["sha"] = "pushed-later"
    _sync(store, prs)
    assert store.topic(a)["status"] == "drafted"                    # he decides again, on what will be merged
    assert store.query("select action from actions where topic_id = ? order by rowid desc limit 1", (a,))[0]["action"] \
        == "approval_stale"
    assert "approved" in _click(c, a, "approve")
    assert c.get("/api/decisions").json()["approved"][0]["sha"] == "pushed-later"


def test_old_topic_links_cant_undo_a_post_decision(drafted):
    store, (a, _b, _c3), _ = drafted
    c = TestClient(create_app(store, background=False))
    _click(c, a, "approve")
    for act in ("pick", "unpick", "dismiss"):
        assert "already has a post" in _click(c, a, act)
    assert store.topic(a)["status"] == "approved"


def test_a_topic_with_an_old_closed_pr_follows_its_open_one(drafted):
    store, (a, _b, _c3), prs = drafted
    c = TestClient(create_app(store, background=False))
    _click(c, a, "approve")
    old = _pr(2, a, state="closed")
    for _ in range(2):
        _sync(store, [*prs, old])
        assert store.topic(a)["status"] == "approved" and store.get_kv(f"pr:{a}")["number"] == 10


def test_publish_only_merges_a_pr_that_adds_one_post():
    ok = [{"filename": "site/blog/posts/x.md", "status": "added"}]
    assert publish.only_adds_one_post(ok)
    assert not publish.only_adds_one_post(ok + [{"filename": "scripts/x.py", "status": "added"}])
    assert not publish.only_adds_one_post([{"filename": "site/blog/posts/x.md", "status": "modified"}])
    assert not publish.only_adds_one_post([{"filename": "site/blog/posts/x.py", "status": "added"}])
