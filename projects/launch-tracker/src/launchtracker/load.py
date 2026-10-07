"""Load the three sources into DuckDB and reconcile them (FR-1).

Launch Library 2 gives detail (stages, crews, images, upcoming); GCAT gives the complete history and is the reference
for outcomes; SATCAT gives what is in orbit. LL2 and GCAT rows for the same launch are matched by international
designator, or failing that by time (within a day) and rocket family. A matched launch keeps the LL2 row with the
GCAT tag attached; any disagreement is written to `discrepancies` and shown, never silently overwritten.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from . import reference
from .config import ROOT, Settings, utcnow
from .db import DATA_TABLES
from .sources import gcat, ll2, satcat

LAUNCH_COLS = ["launch_id", "ll2_id", "gcat_tag", "designator", "name", "net", "net_precision", "window_start",
               "window_end", "status", "status_abbrev", "outcome", "orbital", "category", "provider", "provider_type",
               "country", "rocket", "rocket_family", "rocket_variant", "pad", "location", "pad_lat", "pad_lon",
               "mission_name", "mission_type", "industry", "mission_description", "orbit", "orbit_abbrev",
               "destination", "payload_mass_kg", "crewed", "failreason", "program", "image_url", "image_credit",
               "image_licence", "source", "source_updated", "fetched_at"]


def _insert(con, table: str, rows: list[dict], cols: list[str] | None = None) -> int:
    if not rows:
        return 0
    import pandas as pd

    cols = cols or list(rows[0].keys())
    frame = pd.DataFrame([[r.get(c) for c in cols] for r in rows], columns=cols).astype(object)
    frame = frame.where(frame.notna(), None)
    con.register("_incoming", frame)
    try:
        con.execute(f"insert into {table} ({','.join(cols)}) select {','.join(cols)} from _incoming")
    finally:
        con.unregister("_incoming")
    return len(rows)


def _family_key(s: str | None) -> str:
    """'Taiga-2' / 'Taiga' / 'Condor 9' / 'Condor' → 'taiga' / 'condor': the leading word, letters only."""
    m = re.match(r"[a-z]+", (s or "").lower())
    return m.group(0) if m else ""


def reconcile(ll2_rows: list[dict], gcat_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge the two launch lists. Returns (launch rows, discrepancies)."""
    by_desig = {g["designator"]: g for g in gcat_rows if g["designator"]}
    by_tag = {g["gcat_tag"]: g for g in gcat_rows}
    by_day: dict[str, list[dict]] = {}
    for g in gcat_rows:
        by_day.setdefault(g["net"].date().isoformat(), []).append(g)
    used, notes, out = set(), [], []
    now = utcnow()
    for r in ll2_rows:
        g = by_desig.get(r.get("designator") or "")
        if g is None and r["net"]:
            cands = []
            for k in (-1, 0, 1):
                cands += by_day.get((r["net"] + timedelta(days=k)).date().isoformat(), [])
            cands = [c for c in cands if c["launch_id"] not in used
                     and _family_key(c["rocket"]) == _family_key(r["rocket_family"] or r["rocket"])
                     and abs((c["net"] - r["net"]).total_seconds()) < 86400]
            g = min(cands, key=lambda c: abs((c["net"] - r["net"]).total_seconds())) if cands else None
        if g is not None and g["launch_id"] not in used:
            used.add(g["launch_id"])
            r["gcat_tag"] = g["gcat_tag"]
            r["designator"] = r["designator"] or g["designator"]
            r["payload_mass_kg"] = g["payload_mass_kg"]
            if r["outcome"] in ("success", "failure", "partial") and g["outcome"] != r["outcome"]:
                notes.append({"launch_id": r["launch_id"], "field": "outcome", "ll2_value": r["outcome"],
                              "gcat_value": g["outcome"], "noted_at": now})
            if abs((g["net"] - r["net"]).total_seconds()) > 3600:
                notes.append({"launch_id": r["launch_id"], "field": "net", "ll2_value": r["net"].isoformat(),
                              "gcat_value": g["net"].isoformat(), "noted_at": now})
        out.append(r)
    # Learn GCAT code → LL2 name from the matched pairs, and apply it to launches only GCAT has (older history).
    pairs = {(g["provider"], g["location"]): r for r in out if r.get("gcat_tag")
             for g in [by_tag[r["gcat_tag"]]] if g}
    prov = {k[0]: r["provider"] for k, r in pairs.items()}
    site = {k[1]: r for k, r in pairs.items()}
    for g in gcat_rows:
        if g["launch_id"] in used:
            continue
        if g["provider"] in prov:
            g["provider"] = prov[g["provider"]]
        s = site.get(g["location"])
        if s:
            g.update({"location": s["location"], "country": s["country"], "pad_lat": s["pad_lat"], "pad_lon": s["pad_lon"]})
        out.append(g)
    return out, notes


def _vehicles(con, settings: Settings) -> None:
    con.execute("delete from vehicles")
    con.execute("""insert into vehicles
        select rocket, any_value(rocket_family), mode(provider), min(net), max(net), count(*), null
        from launches where rocket is not null and outcome <> 'pending' group by rocket""")


def load_all(con, settings: Settings, fetch_live: bool | None = None) -> dict:
    """Rebuild the data tables from the sources. Fixture mode reads data/fixture; live mode fetches (politely)."""
    started = utcnow()
    live = settings.mode == "live" if fetch_live is None else fetch_live
    inds = reference.industries()
    fx = ROOT / "data" / "fixture"
    if not live and not (fx / "gcat_launch.tsv").exists():
        import runpy
        runpy.run_path(str(ROOT / "scripts" / "generate_sample_data.py"), run_name="__main__")
    fetched = utcnow()
    requests, note = 0, ""
    if live:
        records, requests, note = ll2.live_pages(con, settings)
        cache = _cache_dir()
        merged = _merge_cache(cache / "ll2.json", records)
        gcat_text = _download_daily(settings, "gcat", settings["sources"]["gcat"]["launch_url"])
        sat_text = _download_daily(settings, "satcat", settings["sources"]["satcat"]["url"])
    else:
        merged = ll2.fixture_pages(ROOT)
        gcat_text = (fx / "gcat_launch.tsv").read_text()
        sat_text = (fx / "satcat.csv").read_text()
    parsed = [ll2.parse_launch(d, inds, fetched) for d in merged]
    if not settings.get("include_suborbital"):
        parsed = [p for p in parsed if p["launch"]["orbital"]]
    g_rows = gcat.parse(gcat_text, settings.get("include_suborbital", False), fetched)
    rows, notes = reconcile([p["launch"] for p in parsed], g_rows)

    for t in DATA_TABLES:
        con.execute(f"delete from {t}")
    n = _insert(con, "launches", rows, LAUNCH_COLS)
    _insert(con, "stages", [s for p in parsed for s in p["stages"]])
    _insert(con, "spacecraft", [s for p in parsed for s in p["spacecraft"]])
    _insert(con, "crew", [s for p in parsed for s in p["crew"]])
    _insert(con, "discrepancies", notes)
    _insert(con, "satcat", satcat.parse(sat_text, fetched))
    _vehicles(con, settings)
    _snapshot(con, settings, live)
    detail = json.dumps({"note": note, "ll2_records": len(merged), "gcat_rows": len(g_rows)})
    con.execute("insert into source_runs values ('all', ?, ?, ?, ?, ?, 'ok', ?)",
                [started, utcnow(), "live" if live else "fixture", n, requests, detail])
    return {"launches": n, "ll2_records": len(merged), "gcat_rows": len(g_rows), "discrepancies": len(notes),
            "satcat": con.execute("select count(*) from satcat").fetchone()[0], "requests": requests, "note": note}


def _snapshot(con, settings: Settings, live: bool) -> None:
    """Record every upcoming launch's target time now, so slips can be measured later. The fixture ships a history."""
    if not live:
        if con.execute("select count(*) from net_snapshots").fetchone()[0] == 0:
            snaps = json.loads((ROOT / "data" / "fixture" / "net_snapshots.json").read_text())
            con.executemany("insert into net_snapshots values (?, ?, ?, ?)",
                            [[s["launch_id"], s["seen_at"], s["net"], s["status_abbrev"]] for s in snaps])
        return
    con.execute("""insert into net_snapshots
        select launch_id, ?, net, status_abbrev from launches where outcome = 'pending' and source = 'll2'""",
                [utcnow()])


# ---------------------------------------------------------------- live helpers
def _cache_dir():
    from .config import workspace
    d = workspace() / "warehouse" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merge_cache(path, records: list[dict]) -> list[dict]:
    """LL2 history arrives a page at a time across runs; keep every record seen, newest version wins."""
    old = json.loads(path.read_text()) if path.exists() else {}
    for r in records:
        old[r["id"]] = r
    path.write_text(json.dumps(old))
    return list(old.values())


def _download_daily(settings: Settings, name: str, url: str) -> str:
    """Bulk files are fetched at most once per refresh_hours; otherwise the cached copy is used."""
    import httpx

    path = _cache_dir() / f"{name}.txt"
    hours = settings["sources"][name]["refresh_hours"]
    if path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < hours * 3600:
        return path.read_text()
    r = httpx.get(url, headers={"User-Agent": settings["sources"]["user_agent"]}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    path.write_text(r.text)
    return r.text
