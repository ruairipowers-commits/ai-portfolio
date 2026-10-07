"""CelesTrak SATCAT: every catalogued object — payloads, rocket bodies, debris — with owner and orbit.

Read from CelesTrak's published bulk CSV at most once a day (their usage policy). Columns are matched by name; if
CelesTrak changes them the load stops and prints the real header rather than guessing.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

REQUIRED = ["OBJECT_NAME", "OBJECT_ID", "NORAD_CAT_ID", "OBJECT_TYPE", "OPS_STATUS_CODE", "OWNER", "LAUNCH_DATE",
            "DECAY_DATE", "PERIOD", "INCLINATION", "APOGEE", "PERIGEE"]
ACTIVE = {"+", "P", "B", "S", "X"}           # operational, partially, backup, spare, extended mission


class FormatChanged(ValueError):
    pass


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _d(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def parse(text: str, fetched_at: datetime) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise FormatChanged(f"SATCAT columns changed; missing {missing}. Header is: {reader.fieldnames}")
    out = []
    for r in reader:
        try:
            norad = int(r["NORAD_CAT_ID"])
        except ValueError:
            continue
        out.append({"norad": norad, "designator": r["OBJECT_ID"], "name": r["OBJECT_NAME"],
                    "object_type": r["OBJECT_TYPE"], "ops_status": r["OPS_STATUS_CODE"] or "?", "owner": r["OWNER"],
                    "launch_date": _d(r["LAUNCH_DATE"]), "decay_date": _d(r["DECAY_DATE"]),
                    "period_min": _f(r["PERIOD"]), "inclination": _f(r["INCLINATION"]),
                    "apogee_km": _f(r["APOGEE"]), "perigee_km": _f(r["PERIGEE"]), "rcs": _f(r.get("RCS")),
                    "fetched_at": fetched_at})
    return out
