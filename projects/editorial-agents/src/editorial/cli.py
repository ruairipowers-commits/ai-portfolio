"""editorial — the scout, the owner's email, the editor's checklist, the eval gate and the service.

    editorial all                  offline end to end: scout on fixtures, topic email to the outbox, eval gate
    editorial scout [--fixtures]   refill and re-rank the queue
    editorial queue                print the queue
    editorial digest               email the ranked list to the owner (outbox file without SMTP settings)
    editorial sync                 mark topics drafted / published from the blog repo's pull requests
    editorial review POST.md [--sources DIR] [--corpus PATH|URL] [--json]
    editorial eval [--alias ALIAS] the golden-set gate
    editorial serve                the web service (queue page, pick / dismiss, scheduler)
    editorial gate POST --editor EDITOR.json [--sources DIR] [--corpus …]
                                   the auto-publish decision (exit 0 = publish, 1 = hold for the owner)
    editorial routing log …        record one routed post run (claude-only or local-review) for the comparison
    editorial routing table        the comparison table the metrics post shows
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import digest, evals, github_sync, review, scout, telemetry
from .config import ROOT
from .store import Store


def _print_queue(store: Store) -> None:
    for i, t in enumerate(store.queue(), 1):
        a, sc = t.get("analysis") or {}, t.get("scores") or {}
        mark = "★" if t["status"] == "picked" else " "
        print(f"{i:>2}{mark} {sc.get('score', 0):.3f}  {t['title'][:70]:<70}  {', '.join(a.get('sectors', [])[:3])}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="editorial", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scout")
    sc.add_argument("--fixtures", action="store_true")
    sub.add_parser("queue")
    sub.add_parser("digest")
    sub.add_parser("sync")
    rv = sub.add_parser("review")
    rv.add_argument("post")
    rv.add_argument("--sources")
    rv.add_argument("--corpus")
    rv.add_argument("--json", action="store_true")
    ev = sub.add_parser("eval")
    ev.add_argument("--alias")
    sub.add_parser("serve")
    sub.add_parser("all")
    ro = sub.add_parser("routing").add_subparsers(dest="routing_cmd", required=True)
    lg = ro.add_parser("log")
    lg.add_argument("--arm", required=True, choices=["claude-only", "local-review"])
    lg.add_argument("--topic", required=True)
    lg.add_argument("--slug", required=True)
    lg.add_argument("--final", required=True, help="the post as it stands after Claude's review")
    lg.add_argument("--local-draft", help="what the local model wrote (local-review)")
    lg.add_argument("--review", nargs="*", default=[], help="everything Claude wrote besides the post: brief, review notes")
    lg.add_argument("--read", nargs="*", default=[], help="every file Claude read for this run")
    lg.add_argument("--local-model", default="")
    lg.add_argument("--local-seconds", type=float, default=0.0)
    lg.add_argument("--checks-first-pass", action="store_true")
    lg.add_argument("--defects", type=int, default=0)
    lg.add_argument("--rewritten", action="store_true")
    lg.add_argument("--editor-min", type=int)
    lg.add_argument("--published", action="store_true")
    lg.add_argument("--note", default="")
    ro.add_parser("table")
    ro.add_parser("paired")
    gt = sub.add_parser("gate")
    gt.add_argument("post")
    gt.add_argument("--editor", required=True, help="the editor subagent's JSON verdict")
    gt.add_argument("--sources")
    gt.add_argument("--corpus")
    a = p.parse_args(argv)
    telemetry.set_actor(os.getenv("USER", "cli"))

    if a.cmd == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8810")),
                    proxy_headers=True, forwarded_allow_ips="*")
        return 0
    if a.cmd == "gate":
        published = scout.published_texts(a.corpus) if (a.corpus or os.getenv("EDITORIAL_CORPUS")
                                                        or os.getenv("PORTFOLIO_SITE_URL")) else \
            scout.published_texts(str(ROOT / "fixtures" / "corpus.json"))
        g = review.gate(a.post, json.loads(open(a.editor).read()), a.sources, published)
        print(review.scorecard_md(g["review"]))
        print("\nDECISION:", "PUBLISH" if g["publish"] else "HOLD for the owner")
        for why in g["reasons"]:
            print(" -", why)
        return 0 if g["publish"] else 1
    if a.cmd == "review":
        published = scout.published_texts(a.corpus) if (a.corpus or os.getenv("EDITORIAL_CORPUS")
                                                        or os.getenv("PORTFOLIO_SITE_URL")) else \
            scout.published_texts(str(ROOT / "fixtures" / "corpus.json"))
        r = review.review(a.post, a.sources, published)
        print(json.dumps(r, indent=2) if a.json else review.scorecard_md(r))
        return 0 if r["passed"] else 1
    if a.cmd == "routing":
        from . import routing
        if a.routing_cmd == "table":
            print(routing.table_md())
            return 0
        if a.routing_cmd == "paired":
            print(routing.summary(routing.load())["paired"]["topics"])
            return 0
        row = routing.record(a.arm, a.topic, a.slug, a.final, local_draft=a.local_draft, review_notes=a.review,
                             read=a.read, local_model=a.local_model, local_seconds=a.local_seconds,
                             checks_first_pass=a.checks_first_pass, defects=a.defects, rewritten=a.rewritten,
                             editor_min=a.editor_min, published=a.published, note=a.note)
        print(json.dumps(row, indent=2))
        return 0
    if a.cmd == "eval":
        r = evals.run(a.alias)
        for x in r["results"]:
            print(f"{'✓' if x['passed'] else '✗'} {x['id']:<16} {x['kind']:<7} got {x['got']}  ({x['why']})")
        print("GATE:", "PASS" if r["passed"] else "FAIL")
        return 0 if r["passed"] else 1

    store = Store()
    if a.cmd == "scout":
        r = scout.run(store, scout.fixture_getter() if a.fixtures else scout.http_get,
                      corpus=str(ROOT / "fixtures" / "corpus.json") if a.fixtures else None,
                      now=scout.FIXTURE_NOW if a.fixtures else None)
        print(json.dumps(r, indent=2))
        _print_queue(store)
    elif a.cmd == "queue":
        _print_queue(store)
    elif a.cmd == "digest":
        print(digest.send(store))
    elif a.cmd == "sync":
        print(github_sync.sync(store))
    elif a.cmd == "all":
        r = scout.run(store, scout.fixture_getter(), corpus=str(ROOT / "fixtures" / "corpus.json"), now=scout.FIXTURE_NOW)
        print(json.dumps({k: v for k, v in r.items() if k != "sources"}))
        _print_queue(store)
        print("topic email:", digest.send(store))
        g = evals.run()
        print("eval gate:", "PASS" if g["passed"] else "FAIL",
              f"({sum(x['passed'] for x in g['results'])}/{len(g['results'])})")
        telemetry.flush()
        return 0 if g["passed"] else 1
    telemetry.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
