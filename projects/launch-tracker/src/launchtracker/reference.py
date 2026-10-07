"""Cited reference tables (costs, market projections, sectors, orbit findings) and their human approval.

A cost row is used only once a person has approved it (settings.costs.require_approval). Approvals live in the
database (reference_reviews), so the YAML stays the source and the review is the audit trail (HITL-03).
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import ROOT, Settings, utcnow

REF = ROOT / "data" / "reference"


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    return yaml.safe_load((REF / f"{name}.yaml").read_text())


def industries() -> dict[str, str]:
    return load("industries")["mission_types"]


def cost_entries(con, settings: Settings) -> list[dict]:
    """Every cost row with its effective status (the latest review wins over the file's status)."""
    reviews = {r[0]: r[1] for r in con.execute(
        "select entry_id, decision from (select *, row_number() over (partition by entry_id order by reviewed_at desc) rn "
        "from reference_reviews where table_name = 'costs') where rn = 1").fetchall()}
    out = []
    for e in load("costs")["entries"]:
        if e.get("fixture") and settings.mode != "fixture":
            continue
        e = dict(e)
        e["status"] = reviews.get(e["id"], e.get("status", "pending"))
        out.append(e)
    return out


def review(con, entry_id: str, decision: str, reviewer: str, note: str = "", table: str = "costs") -> None:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    if not reviewer.strip():
        raise ValueError("a named reviewer is required")
    con.execute("insert into reference_reviews values (?, ?, ?, ?, ?, ?)",
                [entry_id, table, decision, reviewer.strip(), note, utcnow()])


def cost_for(con, settings: Settings, launch: dict) -> dict:
    """The approved published cost that applies to this launch, or NOT_PUBLIC. Never estimated."""
    for e in cost_entries(con, settings):
        if settings["costs"]["require_approval"] and e["status"] != "approved":
            continue
        a = e.get("applies_to", {})
        if a.get("rocket_family") and a["rocket_family"].lower() != (launch.get("rocket_family") or "").lower():
            continue
        if a.get("mission_type") and a["mission_type"] != launch.get("mission_type"):
            continue
        return {"status": "PUBLIC", "entry": e}
    pending = [e["id"] for e in cost_entries(con, settings) if e["status"] == "pending"
               and (e.get("applies_to", {}).get("rocket_family") or "").lower() == (launch.get("rocket_family") or "").lower()]
    return {"status": "NOT_PUBLIC", "pending_review": pending}
