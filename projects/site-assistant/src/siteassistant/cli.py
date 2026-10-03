"""siteassist — run the service, (re)build the index, ask from the terminal, or send the engagement email.

    siteassist serve [--port 7860]
    siteassist index [--source URL|FILE]      # read the blog's search index now
    siteassist ask "Which projects use RAG?"  # one answer, printed (uses Ollama if reachable, else quotes)
    siteassist digest [--day YYYY-MM-DD] [--send]
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    ap = argparse.ArgumentParser(prog="siteassist", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.getenv("PORT", "8700")))
    i = sub.add_parser("index")
    i.add_argument("--source", default="")
    a = sub.add_parser("ask")
    a.add_argument("question")
    e = sub.add_parser("eval")
    e.add_argument("--source", default="")
    d = sub.add_parser("digest")
    d.add_argument("--day", default="")
    d.add_argument("--send", action="store_true")
    args = ap.parse_args()

    from . import app as A
    from . import digest, index, llm
    from .store import Store

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run(A.create_app(), host=args.host, port=args.port, log_level="info", proxy_headers=True,
                    forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))
        return
    store = Store()
    if args.cmd == "index":
        n = index.refresh(store, args.source or A.index_source(), A.site_url(), A.SETTINGS["index"]["min_words"])
        print(f"indexed {n} passages from {args.source or A.index_source()}")
    elif args.cmd == "ask":
        passages = index.context_for(store, args.question, A.site_url(), A.SETTINGS["chat"]["top_k"])
        for piece in llm.answer(args.question, passages, [], A.SETTINGS):
            if isinstance(piece, dict):
                print(f"\n\n[{piece['model']} · {piece['status']}]")
            else:
                sys.stdout.write(piece)
                sys.stdout.flush()
        for n, p in enumerate(passages, 1):
            print(f"  [{n}] {p['page_title']} — {p['url']}")
    elif args.cmd == "eval":
        import yaml
        if args.source:
            index.refresh(store, args.source, A.site_url(), A.SETTINGS["index"]["min_words"])
        g = yaml.safe_load((A.ROOT / "evals" / "golden_set.yaml").read_text())
        hits = 0
        for c in g["cases"]:
            urls = [p["url"] for p in index.context_for(store, c["q"], A.site_url(), g["k"])]
            ok = bool(urls) and (not c["expect"] or any(c["expect"] in u for u in urls))
            hits += ok
            print(f"{'✓' if ok else '✗'} {c['q']}  →  {urls[0] if urls else '—'}")
        rate = hits / len(g["cases"])
        print(f"hit@{g['k']}: {rate:.2f} (gate {g['gate']['hit_rate']})")
        sys.exit(0 if rate >= g["gate"]["hit_rate"] else 1)
    elif args.cmd == "digest":
        r = digest.run(store, A.SETTINGS, args.day or None, send_email=args.send)
        print(f"{r['day']}: {r['subject']} — {r['status']} {r['error']}")


if __name__ == "__main__":
    main()
