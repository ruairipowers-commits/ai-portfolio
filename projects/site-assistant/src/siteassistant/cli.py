"""siteassist — run the service, (re)build the index, ask from the terminal, or send the engagement email.

    siteassist serve [--port 7860]
    siteassist index [--source URL|FILE]      # read the blog's search index now
    siteassist ask "Which projects use RAG?"  # one answer, printed (uses Ollama if reachable, else quotes)
    siteassist eval [--source FILE]           # retrieval golden set (EVAL-01/02)
    siteassist bench MODEL [MODEL …]          # compare Ollama models here: load, first word, tok/s, answers
    siteassist digest [--day YYYY-MM-DD] [--send]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


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
    b = sub.add_parser("bench", help="compare Ollama models on this machine: speed and the answers they give")
    b.add_argument("models", nargs="+", help="Ollama model names, e.g. qwen3.5:9b gemma4:e4b llama3.1:8b")
    b.add_argument("--out", default="bench-answers.md", help="where to write the answers for a side-by-side read")
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
            # the profile card is in every context; score what retrieval found
            urls = [p["url"] for p in index.context_for(store, c["q"], A.site_url(), g["k"]) if not p.get("profile")]
            ok = bool(urls) and (not c["expect"] or any(c["expect"] in u for u in urls))
            hits += ok
            print(f"{'✓' if ok else '✗'} {c['q']}  →  {urls[0] if urls else '—'}")
        rate = hits / len(g["cases"])
        print(f"hit@{g['k']}: {rate:.2f} (gate {g['gate']['hit_rate']})")
        sys.exit(0 if rate >= g["gate"]["hit_rate"] else 1)
    elif args.cmd == "bench":
        bench(store, args.models, args.out)
    elif args.cmd == "digest":
        r = digest.run(store, A.SETTINGS, args.day or None, send_email=args.send)
        print(f"{r['day']}: {r['subject']} — {r['status']} {r['error']}")


BENCH_QUESTIONS = [
    "Would Ruairi be a good fit for a head of AI role at a small investment firm?",
    "Does Ruairi have experience with Kubernetes and Rust?",           # a gap: should be framed as a chance to grow
    "How does the governance console's kill switch work?",
]


def bench(store, models: list[str], out: str) -> None:
    """For each model: pull it if needed, load it, then ask the same questions twice (the second time the prompt
    prefix is cached). Prints load time, time to first word, reading and writing speed; writes every answer to
    `out` so you can judge quality side by side. Run it where the assistant runs, e.g.
        docker compose … exec site-assistant siteassist bench qwen3.5:9b gemma4:e4b llama3.1:8b"""
    import os
    import time

    from . import app as A
    from . import index, llm

    if not llm.ollama_url():
        sys.exit("OLLAMA_URL isn't set: run this inside the site-assistant container")
    if not store.passage_count():
        index.refresh(store, A.index_source(), A.site_url(), A.SETTINGS["index"]["min_words"], A.corpus_source())
    rows, md = [], ["# Model comparison", ""]
    for model in models:
        os.environ["OLLAMA_MODEL"] = model
        os.environ.setdefault("OLLAMA_THINK", "false")
        if not llm.ollama_ready(model):
            print(f"pulling {model} …", flush=True)
            import httpx
            httpx.post(f"{llm.ollama_url()}/api/pull", json={"model": model, "stream": False}, timeout=None)
        t0 = time.perf_counter()
        card = index.profile_passage(store, A.site_url())
        llm.warm_up(A.SETTINGS, [card] if card else [])
        load_s = time.perf_counter() - t0
        md += [f"## {model}", "", f"Load + read the profile card: {load_s:.1f} s", ""]
        for rnd in (1, 2):
            for q in BENCH_QUESTIONS:
                passages = index.context_for(store, q, A.site_url(), A.SETTINGS["chat"]["top_k"])
                t0, first, text, meta = time.perf_counter(), None, [], {}
                for piece in llm.answer(q, passages, [], A.SETTINGS):
                    if isinstance(piece, dict):
                        meta = piece
                    else:
                        first = first or time.perf_counter() - t0
                        text.append(piece)
                total = time.perf_counter() - t0
                pe, ev = meta.get("prompt_eval") or 0, meta.get("eval") or 0
                rows.append((model, rnd, q[:38], first or 0, total, meta.get("input_tokens", 0) / pe if pe else 0,
                             meta.get("output_tokens", 0) / ev if ev else 0, meta.get("status", "")))
                if rnd == 1:
                    md += [f"**{q}**", "", "".join(text).strip(), ""]
    print(f"\n{'model':<22}{'run':>4}  {'question':<40}{'first word':>11}{'total':>8}{'read tok/s':>11}"
          f"{'write tok/s':>12}  status")
    for r in rows:
        print(f"{r[0]:<22}{r[1]:>4}  {r[2]:<40}{r[3]:>10.1f}s{r[4]:>7.1f}s{r[5]:>11.0f}{r[6]:>12.1f}  {r[7]}")
    print("\nRun 2 reuses the cached prompt prefix (rules + profile card), so 'first word' should drop.")
    Path(out).write_text("\n".join(md))
    print(f"Answers written to {out}")


if __name__ == "__main__":
    main()
