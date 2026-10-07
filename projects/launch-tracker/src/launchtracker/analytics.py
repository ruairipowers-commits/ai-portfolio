"""Every number on the dashboards, as SQL. Nothing here calls a model (NFR-3)."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import reference
from .config import Settings
from .db import rows, scalar

UNCLASSIFIED = "Unclassified (no mission type)"
FILTER_COLS = {"provider": "provider", "country": "country", "rocket": "rocket", "family": "rocket_family",
               "orbit": "orbit_abbrev", "mission_type": "mission_type", "industry": "industry", "outcome": "outcome",
               "pad": "location"}


# ---------------------------------------------------------------- filters (explorer and dashboards share them)
def where(f: dict | None) -> tuple[str, list]:
    """Build a parameterised WHERE clause from a filter dict. Unknown keys are ignored, values never interpolated."""
    f = f or {}
    clauses, params = ["outcome <> 'pending'"] if not f.get("include_pending") else ["true"], []
    if f.get("year_from"):
        clauses.append("year(net) >= ?"); params.append(int(f["year_from"]))
    if f.get("year_to"):
        clauses.append("year(net) <= ?"); params.append(int(f["year_to"]))
    for key, col in FILTER_COLS.items():
        vals = f.get(key)
        if vals:
            vals = [vals] if isinstance(vals, str) else list(vals)
            if col == "industry" and UNCLASSIFIED in vals:
                clauses.append(f"(industry in ({','.join('?' * len(vals))}) or industry is null)")
            else:
                clauses.append(f"{col} in ({','.join('?' * len(vals))})")
            params += vals
    if f.get("crewed") is not None:
        clauses.append("crewed = ?"); params.append(bool(f["crewed"]))
    if f.get("reused_booster"):
        clauses.append("launch_id in (select launch_id from stages where reused)")
    if f.get("landing_type"):
        clauses.append("launch_id in (select launch_id from stages where landing_type = ?)"); params.append(f["landing_type"])
    if f.get("text"):
        clauses.append("(name ilike ? or mission_name ilike ?)"); params += [f"%{f['text']}%"] * 2
    return " and ".join(clauses), params


def options(con) -> dict[str, list]:
    out = {}
    for key, col in FILTER_COLS.items():
        out[key] = [r[0] for r in con.execute(f"select distinct {col} from launches where {col} is not null order by 1").fetchall()]
    out["industry"] = out["industry"] + [UNCLASSIFIED]
    out["years"] = [r[0] for r in con.execute("select distinct year(net) from launches order by 1").fetchall()]
    out["landing_type"] = [r[0] for r in con.execute("select distinct landing_type from stages where landing_type is not null order by 1").fetchall()]
    return out


def explorer(con, f: dict | None = None, limit: int = 500) -> list[dict]:
    w, p = where(f)
    return rows(con, f"""select launch_id, net, name, provider, country, rocket, location, orbit_abbrev as orbit,
            mission_type, coalesce(industry, '{UNCLASSIFIED}') as industry, outcome, crewed
            from launches where {w} order by net desc limit {int(limit)}""", p)


def summary_by(con, dim: str, f: dict | None = None) -> list[dict]:
    """Launches, successes and failures grouped by one category (FR-3)."""
    col = {"year": "year(net)", **FILTER_COLS}.get(dim)
    if not col:
        raise ValueError(f"unknown dimension {dim}")
    if col == "industry":
        col = f"coalesce(industry, '{UNCLASSIFIED}')"
    w, p = where(f)
    return rows(con, f"""select {col} as {dim if dim != 'year' else 'yr'}, count(*) as launches,
            count(*) filter (where outcome = 'success') as successes,
            count(*) filter (where outcome = 'failure') as failures,
            count(*) filter (where outcome = 'partial') as partial,
            round(100.0 * count(*) filter (where outcome = 'success') / count(*), 1) as success_pct,
            count(*) filter (where crewed) as crewed
            from launches where {w} group by 1 order by 2 desc""", p)


# ---------------------------------------------------------------- dashboard (FR-4)
def per_year(con, f: dict | None = None, by: str | None = None) -> list[dict]:
    w, p = where(f)
    if by:
        col = FILTER_COLS[by] if by != "industry" else f"coalesce(industry, '{UNCLASSIFIED}')"
        return rows(con, f"select year(net) as yr, {col} as grp, count(*) as n from launches where {w} "
                         f"group by 1, 2 order by 1, 2", p)
    return rows(con, f"""select year(net) as yr, count(*) as launches,
            count(*) filter (where outcome = 'success') as successes,
            count(*) filter (where outcome = 'failure') as failures,
            count(*) filter (where outcome = 'partial') as partial
            from launches where {w} group by 1 order by 1""", p)


def success_by_rocket(con, f: dict | None = None, min_launches: int = 5) -> list[dict]:
    w, p = where(f)
    return rows(con, f"""select rocket, count(*) as launches,
            count(*) filter (where outcome = 'success') as successes,
            count(*) filter (where outcome in ('failure', 'partial')) as failures,
            round(100.0 * count(*) filter (where outcome = 'success') / count(*), 1) as success_pct,
            min(year(net)) as first_year, max(year(net)) as last_year
            from launches where {w} group by 1 having count(*) >= {int(min_launches)} order by launches desc""", p)


def failures(con, f: dict | None = None) -> list[dict]:
    w, p = where(f)
    return rows(con, f"""select net, name, rocket, provider, outcome, failreason from launches
            where {w} and outcome in ('failure', 'partial') order by net desc""", p)


def retirements(con, settings: Settings) -> list[dict]:
    cutoff = settings.now() - timedelta(days=30.4 * settings["analytics"]["retired_after_months"])
    return rows(con, """select rocket, family, provider, year(first_launch) as first_year, year(last_launch) as retired_year,
            launches from vehicles where last_launch < ? order by last_launch desc""", [cutoff])


def reuse(con) -> dict:
    by_year = rows(con, """select year(l.net) as yr,
            count(*) filter (where s.landing_attempt) as landing_attempts,
            count(*) filter (where s.landing_success) as landings,
            count(*) filter (where s.reused) as reflights
            from stages s join launches l using (launch_id) where l.outcome <> 'pending' group by 1 order by 1""")
    record = rows(con, "select serial, max(flight_number) as flights from stages group by 1 order by 2 desc limit 1")
    turnaround = scalar(con, "select median(turnaround_days) from stages where reused and turnaround_days is not null")
    splash = rows(con, """select l.net, l.name, c.name as spacecraft, c.landing_location, c.landing_success
            from spacecraft c join launches l using (launch_id) where c.splashdown order by l.net desc""")
    return {"by_year": by_year, "record_booster": record[0] if record else None,
            "median_turnaround_days": round(turnaround, 1) if turnaround else None, "splashdowns": splash}


def slips(con, launch_id: str | None = None) -> list[dict]:
    """Delays measured from target-time snapshots: first target seen vs the latest (or actual) time."""
    flt = "where s.launch_id = ?" if launch_id else ""
    return rows(con, f"""with s as (
              select launch_id, min(seen_at) as first_seen, arg_min(net, seen_at) as first_net,
                     arg_max(net, seen_at) as last_net, count(distinct net) - 1 as changes
              from net_snapshots group by 1)
            select s.launch_id, l.name, l.outcome, s.first_seen, s.first_net,
                   case when l.outcome = 'pending' then s.last_net else l.net end as current_net, s.changes,
                   round(epoch(case when l.outcome = 'pending' then s.last_net else l.net end - s.first_net) / 86400, 2) as slip_days
            from s join launches l using (launch_id) {flt} order by slip_days desc""", [launch_id] if launch_id else [])


def delay_stats(con) -> dict:
    r = slips(con)
    if not r:
        return {"tracked": 0}
    days = sorted(x["slip_days"] for x in r)
    slipped = [d for d in days if d > 0]
    return {"tracked": len(r), "slipped": len(slipped), "slipped_pct": round(100 * len(slipped) / len(r), 1),
            "median_slip_days": days[len(days) // 2], "max_slip_days": days[-1],
            "changes_per_launch": round(sum(x["changes"] for x in r) / len(r), 2)}


def costs(con, settings: Settings) -> list[dict]:
    """Published costs with their launches and, where both are known, cost per kg to orbit."""
    out = []
    for e in reference.cost_entries(con, settings):
        fam = e.get("applies_to", {}).get("rocket_family")
        n, mass = con.execute("select count(*), avg(payload_mass_kg) from launches where lower(rocket_family) = lower(?) "
                              "and outcome = 'success'", [fam]).fetchone()
        per_kg = e["amount_usd"] / mass if e["unit"] == "per_launch" and mass else (e["amount_usd"] if e["unit"] == "per_kg" else None)
        out.append({**e, "launches": n, "avg_payload_kg": round(mass) if mass else None,
                    "usd_per_kg": round(per_kg) if per_kg else None})
    return out


def headline(con, settings: Settings) -> dict:
    now = settings.now()
    y = now.year
    return {
        "launches_this_year": scalar(con, "select count(*) from launches where year(net) = ? and outcome <> 'pending'", [y]),
        "launches_last_year": scalar(con, "select count(*) from launches where year(net) = ? and outcome <> 'pending'", [y - 1]),
        "success_pct_12m": scalar(con, """select round(100.0 * count(*) filter (where outcome = 'success') / nullif(count(*), 0), 1)
                                          from launches where net > ? and net <= ? and outcome <> 'pending'""",
                                  [now - timedelta(days=365), now]),
        "upcoming": scalar(con, "select count(*) from launches where outcome = 'pending'"),
        "crewed_this_year": scalar(con, "select count(*) from launches where crewed and year(net) = ? and outcome <> 'pending'", [y]),
        "reflights_this_year": scalar(con, """select count(*) from stages s join launches l using (launch_id)
                                              where s.reused and year(l.net) = ? and l.outcome <> 'pending'""", [y]),
        "in_orbit": scalar(con, "select count(*) from satcat where decay_date is null"),
    }


# ---------------------------------------------------------------- upcoming and one launch (FR-2)
def upcoming(con, settings: Settings) -> list[dict]:
    now = settings.now()
    out = rows(con, """select launch_id, net, net_precision, window_start, window_end, status, status_abbrev, name,
            provider, rocket, location, mission_type, orbit_abbrev, crewed from launches
            where outcome = 'pending' and net >= ? order by net""", [now - timedelta(hours=6)])
    slip = {s["launch_id"]: s for s in slips(con)}
    for r in out:
        r["seconds_to_go"] = int((r["net"] - now).total_seconds())
        r["slip_days"] = slip.get(r["launch_id"], {}).get("slip_days")
        r["changes"] = slip.get(r["launch_id"], {}).get("changes")
    return out


def launch(con, settings: Settings, launch_id: str) -> dict | None:
    rec = rows(con, "select * from launches where launch_id = ?", [launch_id])
    if not rec:
        return None
    L = rec[0]
    return {"launch": L,
            "stages": rows(con, "select * from stages where launch_id = ?", [launch_id]),
            "spacecraft": rows(con, "select * from spacecraft where launch_id = ?", [launch_id]),
            "crew": rows(con, "select name, role, agency, nationality from crew where launch_id = ?", [launch_id]),
            "slips": rows(con, "select seen_at, net, status_abbrev from net_snapshots where launch_id = ? order by seen_at",
                          [launch_id]),
            "discrepancies": rows(con, "select field, ll2_value, gcat_value from discrepancies where launch_id = ?", [launch_id]),
            "cost": reference.cost_for(con, settings, L),
            "image": image_decision(L, settings)}


def image_decision(L: dict, settings: Settings) -> dict:
    """No licence, no image (DATA-04): an unlicensed image becomes a link to its source, never displayed."""
    url, lic = L.get("image_url"), (L.get("image_licence") or "").strip()
    if not url:
        return {"show": False, "reason": "no image"}
    if lic and lic in settings["images"]["allowed_licences"]:
        return {"show": True, "url": url, "credit": L.get("image_credit"), "licence": lic}
    return {"show": False, "link": url if settings["images"]["show_unknown_licence_as_link"] else None,
            "reason": f"licence {'unknown' if not lic or lic == 'Unknown' else repr(lic) + ' not on the allowed list'}"}


def industry_by_year(con, f: dict | None = None) -> list[dict]:
    return per_year(con, f, by="industry")
