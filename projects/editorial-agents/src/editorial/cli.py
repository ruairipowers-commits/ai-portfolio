"""editorial — the scout, the owner's email, the editor's checklist, the eval gate and the service.

    editorial all                  offline end to end: scout on fixtures, topic email to the outbox, eval gate
    editorial scout [--fixtures]   refill and re-rank the queue
    editorial queue                print the queue
    editorial digest               email the ranked list to the owner (outbox file without SMTP settings)
    editorial sync                 mark topics drafted / published from the blog repo's pull requests
    editorial review POST.md [--sources DIR] [--corpus PATH|URL] [--json]
    editorial eval [--alias ALIAS] the golden-set gate
    editorial serve                the web service (queue page, pick / dismiss, scheduler)
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
    a = p.parse_args(argv)
    telemetry.set_actor(os.getenv("USER", "cli"))

    if a.cmd == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8810")),
                    proxy_headers=True, forwarded_allow_ips="*")
        return 0
    if a.cmd == "review":
        published = scout.published_texts(a.corpus) if (a.corpus or os.getenv("EDITORIAL_CORPUS")
                                                        or os.getenv("PORTFOLIO_SITE_URL")) else \
            scout.published_texts(str(ROOT / "fixtures" / "corpus.json"))
        r = review.review(a.post, a.sources, published)
        print(json.dumps(r, indent=2) if a.json else review.scorecard_md(r))
        return 0 if r["passed"] else 1
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
