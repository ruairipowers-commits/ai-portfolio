"""govconsole CLI: serve the console, seed simulated history, import local spool files, inspect the catalog."""
from __future__ import annotations

import argparse
import json
import os

from . import catalog, metrics, simulate, spool
from .store import Store


def main(argv=None):
    p = argparse.ArgumentParser(prog="govconsole", description="AI governance console")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the console (http://localhost:8600)")
    s.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.getenv("PORT", 8600)))
    sd = sub.add_parser("seed", help="(re)generate the labelled simulated history; live events are kept")
    sd.add_argument("--days", type=int, default=metrics.load_settings()["simulation"]["days"])
    sp = sub.add_parser("import-spool", help="load events that local app runs wrote to the spool file")
    sp.add_argument("path", nargs="?")
    sub.add_parser("catalog", help="print the workflows and control coverage the console will govern")
    sub.add_parser("status", help="kill-switch state and 30-day spend per workflow")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        from .app import create_app

        # proxy headers: behind a reverse proxy / tunnel, request.url.scheme is https (so admin cookies get Secure)
        uvicorn.run(create_app(), host=a.host, port=a.port, log_level="info", proxy_headers=True,
                    forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))
    elif a.cmd == "seed":
        st = Store()
        cat = catalog.load()
        n = simulate.seed(st, [w["slug"] for w in cat["workflows"]], a.days,
                          metrics.load_settings()["simulation"]["seed"], cat)
        print(f"Seeded {n:,} simulated events over {a.days} days")
    elif a.cmd == "import-spool":
        from pathlib import Path

        print(f"Imported {spool.import_spool(Store(), Path(a.path) if a.path else None)} new events")
    elif a.cmd == "catalog":
        c = catalog.load()
        for w in c["workflows"]:
            n = len(w["controls"])
            print(f"{w['slug']:24s} {w['status']:14s} risk={w['risk_tier']:7s} controls mapped {n}/{len(c['controls'])}")
    elif a.cmd == "status":
        for r in metrics.workflow_table(Store(), catalog.load()):
            print(json.dumps({k: r[k] for k in ("slug", "enabled", "runs_30d", "cost_30d", "budget_pct", "registered")}))


if __name__ == "__main__":
    main()
