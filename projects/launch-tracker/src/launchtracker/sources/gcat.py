"""GCAT launch list (Jonathan McDowell, CC-BY-4.0): the authoritative record of every launch since 1957.

Columns are read by name from the header line (it starts with '#'). LaunchCode's first letter is the category
(O orbital, D deep space, S/Y/N suborbital kinds, …) and its second the outcome (S success, F failure, U unknown,
E pad explosion; two digits are a partial-success percentage). Only orbital and deep-space launches are kept unless
`include_suborbital` is on.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

REQUIRED = ["Launch_Tag", "Launch_Date", "LV_Type", "Launch_Site", "Launch_Pad", "Launch_Agency", "LaunchCode"]
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                      "Dec"], 1)}
ORBITAL = {"O": "orbital", "D": "deep space"}
SUBORBITAL = {"S": "suborbital", "Y": "suborbital", "N": "suborbital"}


class FormatChanged(ValueError):
    pass


def parse_date(s: str) -> datetime | None:
    """'2024 Jan  3 1234:56' or '1957 Oct  4' (uncertainty marks like '?' are dropped) → UTC datetime."""
    s = s.replace("?", "").strip()
    m = re.match(r"(\d{4})\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{2})(\d{2})(?::(\d{2}))?)?", s)
    if not m:
        return None
    y, mon, d, hh, mm, ss = m.groups()
    return datetime(int(y), MONTHS[mon], int(d), int(hh or 0), int(mm or 0), int(float(ss or 0)), tzinfo=timezone.utc)


def outcome(code: str) -> str:
    c = (code or "")[1:]
    if c[:1] == "S":
        return "success"
    if c[:1] in ("F", "E"):
        return "failure"
    if c[:2].isdigit():
        return "partial"
    return "unknown"


def parse(text: str, include_suborbital: bool, fetched_at: datetime) -> list[dict]:
    lines = [l for l in text.splitlines() if l.strip()]
    header = lines[0].lstrip("#").strip().split("\t")
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise FormatChanged(f"GCAT launch.tsv columns changed; missing {missing}. Header is: {header}")
    out = []
    for rec in csv.DictReader(io.StringIO("\n".join(lines[1:])), fieldnames=header, delimiter="\t"):
        code = (rec.get("LaunchCode") or "").strip()
        kind = ORBITAL.get(code[:1]) or (SUBORBITAL.get(code[:1]) if include_suborbital else None)
        if not kind or code[1:2] == "A":            # 'A' = pad abort: nothing left the pad
            continue
        when = parse_date(rec.get("Launch_Date", ""))
        if not when:
            continue
        tag = rec["Launch_Tag"].strip()
        lv = (rec.get("LV_Type") or "").strip()
        mass = (rec.get("Orbital Payload") or rec.get("Orbital_Payload") or "").strip().rstrip("?")
        out.append({
            "launch_id": f"gcat:{tag}", "ll2_id": None, "gcat_tag": tag,
            "designator": tag if re.match(r"^\d{4}-\d{3}$", tag) else None,
            "name": f"{lv} | {(rec.get('Mission') or rec.get('Flight') or '').strip() or tag}",
            "net": when, "net_precision": None, "window_start": None, "window_end": None,
            "status": None, "status_abbrev": None, "outcome": outcome(code),
            "orbital": kind != "suborbital", "category": kind,
            "provider": (rec.get("Launch_Agency") or "").strip() or None, "provider_type": None, "country": None,
            "rocket": lv, "rocket_family": lv.split()[0] if lv else None,
            "rocket_variant": (rec.get("LV_Variant") or "").strip() or None,
            "pad": (rec.get("Launch_Pad") or "").strip() or None, "location": (rec.get("Launch_Site") or "").strip(),
            "pad_lat": None, "pad_lon": None,
            "mission_name": (rec.get("Mission") or "").strip() or None, "mission_type": None, "industry": None,
            "mission_description": None, "orbit": None, "orbit_abbrev": None,
            "destination": (rec.get("Destination") or "").strip() or None,
            "payload_mass_kg": float(mass) if re.match(r"^\d+(\.\d+)?$", mass) else None,
            "crewed": False, "failreason": None, "program": None,
            "image_url": None, "image_credit": None, "image_licence": None,
            "source": "gcat", "source_updated": None, "fetched_at": fetched_at,
        })
    return out
