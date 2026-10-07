"""What is in orbit, and where it is crowded — counted from the SATCAT, set beside ESA's published findings."""
from __future__ import annotations

from .config import Settings
from .db import rows, scalar
from .sources.satcat import ACTIVE

REGIME = """case
    when apogee_km is null or perigee_km is null then 'Unknown'
    when apogee_km < 2000 then 'LEO'
    when perigee_km >= 35586 and apogee_km <= 35986 then 'GEO'
    when perigee_km >= 2000 and apogee_km < 35586 then 'MEO'
    else 'HEO / other' end"""
ACTIVE_SQL = "ops_status in (" + ",".join(f"'{c}'" for c in sorted(ACTIVE)) + ")"
TYPES = "case object_type when 'PAY' then 'Payload' when 'R/B' then 'Rocket body' when 'DEB' then 'Debris' else 'Unknown' end"


def overview(con) -> dict:
    total = scalar(con, "select count(*) from satcat where decay_date is null")
    return {"in_orbit": total,
            "active_payloads": scalar(con, f"select count(*) from satcat where decay_date is null and object_type = 'PAY' and {ACTIVE_SQL}"),
            "decayed_total": scalar(con, "select count(*) from satcat where decay_date is not null"),
            "by_type": rows(con, f"select {TYPES} as kind, count(*) as n from satcat where decay_date is null group by 1 order by 2 desc"),
            "by_regime": rows(con, f"""select {REGIME} as regime, {TYPES} as kind, count(*) as n from satcat
                                       where decay_date is null group by 1, 2 order by 1, 2"""),
            "by_owner": rows(con, f"""select owner, count(*) as n, count(*) filter (where object_type = 'PAY' and {ACTIVE_SQL}) as active
                                      from satcat where decay_date is null group by 1 order by 2 desc limit 15""")}


def shells(con, settings: Settings) -> list[dict]:
    """Objects per altitude shell in LEO (mean of perigee and apogee), split payload-active / payload-dead / R/B / debris."""
    w, top = settings["analytics"]["shell_km"], settings["analytics"]["leo_max_km"]
    return rows(con, f"""select cast(floor((perigee_km + apogee_km) / 2 / {w}) * {w} as integer) as shell_km,
            count(*) filter (where object_type = 'PAY' and {ACTIVE_SQL}) as active_payloads,
            count(*) filter (where object_type = 'PAY' and not {ACTIVE_SQL}) as dead_payloads,
            count(*) filter (where object_type = 'R/B') as rocket_bodies,
            count(*) filter (where object_type = 'DEB') as debris,
            count(*) as total
            from satcat where decay_date is null and apogee_km < {top} and perigee_km > 100
            group by 1 order by 1""")


def crowding(con, settings: Settings) -> dict:
    """The busiest shell, and how debris compares with active satellites there (ESA's 550 km finding, measured here)."""
    s = shells(con, settings)
    if not s:
        return {}
    busiest = max(s, key=lambda r: r["total"])
    ratio = round((busiest["debris"] + busiest["rocket_bodies"] + busiest["dead_payloads"]) / busiest["active_payloads"], 2) \
        if busiest["active_payloads"] else None
    leo_total = sum(r["total"] for r in s)
    return {"busiest_shell_km": busiest["shell_km"], "busiest_total": busiest["total"],
            "busiest_share_of_leo_pct": round(100 * busiest["total"] / leo_total, 1) if leo_total else None,
            "busiest_inactive_per_active": ratio, "shell_width_km": settings["analytics"]["shell_km"]}


def constellations(con, min_size: int = 50) -> list[dict]:
    """Payload families by name prefix (e.g. 'SKYMESH-…'): who owns how much of the sky."""
    return rows(con, f"""select regexp_extract(name, '^([A-Z]+)', 1) as family, count(*) as n,
            count(*) filter (where {ACTIVE_SQL}) as active
            from satcat where object_type = 'PAY' and decay_date is null group by 1 having count(*) >= {min_size}
            order by 2 desc""")


def reentries_per_year(con) -> list[dict]:
    return rows(con, f"""select year(decay_date) as yr, {TYPES} as kind, count(*) as n from satcat
            where decay_date is not null group by 1, 2 order by 1, 2""")
