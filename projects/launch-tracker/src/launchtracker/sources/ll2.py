"""Launch Library 2 (The Space Devs): upcoming and recent launches, stages and reuse, crews, spacecraft, images.

The free tier allows 15 requests an hour without a key. `RequestBudget` counts every request in the database and
refuses the next one before it is sent (NFR-2), so a refresh loop, a visitor clicking Refresh and a backfill all share
one budget. The history backfill is resumable: it stores its offset and picks up where the budget stopped it.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import Settings, utcnow

STATUS_OUTCOME = {"Success": "success", "Failure": "failure", "Partial Failure": "partial"}
SPLASH = re.compile(r"ocean|sea|gulf|bay", re.I)


class BudgetExhausted(RuntimeError):
    pass


class RequestBudget:
    def __init__(self, con, per_hour: int):
        self.con, self.per_hour = con, per_hour

    def used(self, now: datetime | None = None) -> int:
        since = (now or utcnow()) - timedelta(hours=1)
        return self.con.execute("select count(*) from ll2_requests where ts > ?", [since]).fetchone()[0]

    def remaining(self) -> int:
        return max(0, self.per_hour - self.used())

    def take(self, url: str) -> None:
        if self.remaining() <= 0:
            raise BudgetExhausted(f"Launch Library 2 budget used: {self.per_hour} requests in the last hour")
        self.con.execute("insert into ll2_requests values (?, ?, null)", [utcnow(), url])

    def record_status(self, url: str, status: int) -> None:
        self.con.execute("update ll2_requests set status = ? where url = ? and status is null", [status, url])


def get_json(con, settings: Settings, path: str, params: dict) -> dict:
    """One budgeted GET. The only function in this module that touches the network."""
    import httpx

    src = settings["sources"]["ll2"]
    base = os.getenv("LL2_BASE_URL", src["base_url"]).rstrip("/")
    url = f"{base}/{path.strip('/')}/"
    full = str(httpx.URL(url, params=params))
    budget = RequestBudget(con, src["max_requests_per_hour"])
    budget.take(full)
    headers = {"User-Agent": settings["sources"]["user_agent"]}
    if os.getenv("LL2_API_KEY"):                                   # SEC-01: from the environment only
        headers["Authorization"] = f"Token {os.environ['LL2_API_KEY']}"
    r = httpx.get(full, headers=headers, timeout=60)
    budget.record_status(full, r.status_code)
    if r.status_code == 429:
        raise BudgetExhausted("Launch Library 2 says the rate limit is reached (HTTP 429)")
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- parsing (same code for live and fixture)
def _ts(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None


def _name(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _days(iso_duration: str | None) -> float | None:
    """'P230DT4H54M10S' → 230.2"""
    if not iso_duration:
        return None
    m = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso_duration)
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return round(d + h / 24 + mi / 1440 + s / 86400, 2)


def parse_launch(d: dict, industries: dict, fetched_at: datetime) -> dict:
    """One LL2 launch record → rows for launches, stages, spacecraft, crew."""
    lid = f"ll2:{d['id']}"
    rocket = d.get("rocket") or {}
    conf = rocket.get("configuration") or {}
    mission = d.get("mission") or {}
    pad = d.get("pad") or {}
    loc = pad.get("location") or {}
    lsp = d.get("launch_service_provider") or {}
    orbit_abbrev = _name(mission, "orbit", "abbrev")
    status_name = _name(d, "status", "name") or ""
    status_abbrev = _name(d, "status", "abbrev") or ""
    outcome = STATUS_OUTCOME.get(status_abbrev) or STATUS_OUTCOME.get(status_name) or \
        ("pending" if status_abbrev in ("Go", "TBD", "TBC", "Hold", "In Flight") else "unknown")
    image = d.get("image") or {}
    countries = lsp.get("country") or []
    country = (countries[0].get("name") if isinstance(countries, list) and countries
               else _name(loc, "country", "name"))
    stages, craft, crew = [], [], []
    for st in rocket.get("launcher_stage") or []:
        landing = st.get("landing") or {}
        stages.append({
            "launch_id": lid, "stage_type": st.get("type"), "serial": _name(st, "launcher", "serial_number"),
            "reused": st.get("reused"), "flight_number": st.get("launcher_flight_number"),
            "turnaround_days": _days(st.get("turn_around_time")),
            "landing_attempt": landing.get("attempt"), "landing_success": landing.get("success"),
            "landing_type": _name(landing, "type", "abbrev"),
            "landing_location": _name(landing, "landing_location", "name"), "fetched_at": fetched_at})
    scs = rocket.get("spacecraft_stage") or []
    for sc in scs if isinstance(scs, list) else [scs]:
        landing = sc.get("landing") or {}
        where = _name(landing, "landing_location", "name") or ""
        craft.append({
            "launch_id": lid, "serial": _name(sc, "spacecraft", "serial_number"), "name": _name(sc, "spacecraft", "name"),
            "config": _name(sc, "spacecraft", "spacecraft_config", "name"), "destination": sc.get("destination"),
            "landing_success": landing.get("success"), "landing_type": _name(landing, "type", "name"),
            "landing_location": where or None, "splashdown": bool(SPLASH.search(where)), "fetched_at": fetched_at})
        for c in sc.get("launch_crew") or []:
            nat = _name(c, "astronaut", "nationality")
            crew.append({
                "launch_id": lid, "name": _name(c, "astronaut", "name"), "role": _name(c, "role", "role"),
                "agency": _name(c, "astronaut", "agency", "name"),
                "nationality": nat[0].get("nationality_name") if isinstance(nat, list) and nat else None,
                "fetched_at": fetched_at})
    mtype = mission.get("type")
    families = conf.get("families") or []
    launch = {
        "launch_id": lid, "ll2_id": d["id"], "gcat_tag": None, "designator": d.get("launch_designator"),
        "name": d.get("name"), "net": _ts(d.get("net")), "net_precision": _name(d, "net_precision", "name"),
        "window_start": _ts(d.get("window_start")), "window_end": _ts(d.get("window_end")),
        "status": status_name, "status_abbrev": status_abbrev, "outcome": outcome,
        "orbital": orbit_abbrev != "Sub", "category": "suborbital" if orbit_abbrev == "Sub" else "orbital",
        "provider": lsp.get("name"), "provider_type": lsp.get("type") if isinstance(lsp.get("type"), str)
        else _name(lsp, "type", "name"), "country": country,
        "rocket": conf.get("full_name") or conf.get("name"),
        "rocket_family": families[0].get("name") if families else conf.get("family"),
        "rocket_variant": conf.get("variant"),
        "pad": pad.get("name"), "location": loc.get("name"), "pad_lat": _float(pad.get("latitude")),
        "pad_lon": _float(pad.get("longitude")),
        "mission_name": mission.get("name"), "mission_type": mtype,
        "industry": industries.get(mtype or "", "other"), "mission_description": mission.get("description"),
        "orbit": _name(mission, "orbit", "name"), "orbit_abbrev": orbit_abbrev,
        "destination": next((c["destination"] for c in craft if c["destination"]), None),
        "payload_mass_kg": None, "crewed": bool(crew), "failreason": d.get("failreason") or None,
        "program": ", ".join(p.get("name", "") for p in d.get("program") or []) or None,
        "image_url": image.get("image_url"), "image_credit": image.get("credit"),
        "image_licence": _name(image, "license", "name"),
        "source": "ll2", "source_updated": _ts(d.get("last_updated")), "fetched_at": fetched_at,
    }
    return {"launch": launch, "stages": stages, "spacecraft": craft, "crew": crew}


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- loading
def fixture_pages(root: Path) -> list[dict]:
    """The offline sample: the same JSON shape the API returns ({"results": [...]})."""
    out = []
    for name in ("ll2_previous.json", "ll2_upcoming.json"):
        out += json.loads((root / "data" / "fixture" / name).read_text())["results"]
    return out


def live_pages(con, settings: Settings, max_requests: int | None = None) -> tuple[list[dict], int, str]:
    """Upcoming launches, plus launches updated recently, plus the next page of the history backfill — as far as the
    hourly budget allows. Returns (records, requests used, note)."""
    src = settings["sources"]["ll2"]
    size = src["page_size"]
    out, used, notes = [], 0, []
    cap = max_requests if max_requests is not None else src["max_requests_per_hour"]

    def page(path, params):
        nonlocal used
        if used >= cap:
            raise BudgetExhausted("this run's request cap reached")
        used += 1
        return get_json(con, settings, path, params)

    try:
        d = page("launches/upcoming", {"mode": "detailed", "limit": size})
        out += d["results"]
        since = (utcnow() - timedelta(days=src["history_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        d = page("launches/previous", {"mode": "detailed", "limit": size, "last_updated__gte": since})
        out += d["results"]
        # resumable backfill of the whole history, oldest first
        offset = con.execute("select coalesce(max(cast(detail as integer)), 0) from source_runs "
                             "where source = 'll2-backfill' and status = 'ok'").fetchone()[0]
        while True:
            d = page("launches/previous", {"mode": "detailed", "limit": size, "offset": offset, "ordering": "net"})
            out += d["results"]
            offset += len(d["results"])
            con.execute("insert into source_runs values ('ll2-backfill', ?, ?, 'live', ?, 1, 'ok', ?)",
                        [utcnow(), utcnow(), len(d["results"]), str(offset)])
            if not d.get("next"):
                notes.append("history backfill complete")
                break
    except BudgetExhausted as e:
        notes.append(f"stopped: {e}")
    return out, used, "; ".join(notes)
