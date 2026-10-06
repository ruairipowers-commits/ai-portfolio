"""Licence rules engine and entitlements (DATA-04, FR-5).

Deterministic: no model decides usage rights. For a dataset, a use case and (optionally) a customer it returns one of
  PERMITTED     the licence or an active contract allows it
  CONDITIONAL   allowed with conditions (attribution, share-alike) that the result lists
  LEGAL_REVIEW  rights are unclear (no licence declared, vendor text contradicts the licence tag, injected text) —
                a named person in legal decides, and that decision is recorded as an approval
  BLOCKED       not allowed (no contract for paid data, the contract excludes the use, non-commercial licence)
Entitlements are what the context layer and downloads check: a customer may use a dataset for a use only when
the verdict is PERMITTED or CONDITIONAL *for that customer*.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, select

from . import store
from .config import Settings
from .guardrails import scan_injection

PERMITTED, CONDITIONAL, LEGAL_REVIEW, BLOCKED = "PERMITTED", "CONDITIONAL", "LEGAL_REVIEW", "BLOCKED"
USES = ("v:InternalResearch", "v:AIProcessing", "v:Redistribution", "v:CommercialProduct")
_COMMERCIAL_CLAIM = re.compile(r"commercial use|free for any use|no restrictions|public domain|apache|mit licen", re.I)


@dataclass
class Verdict:
    dataset_id: str
    use: str
    customer_id: str | None
    verdict: str
    reasons: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    source: str = ""                 # licence | contract c-001 | registration | legal decision a-…

    @property
    def allowed(self) -> bool:
        return self.verdict in (PERMITTED, CONDITIONAL)


def _licence_only(ds: store.Dataset, use: str, settings: Settings) -> Verdict:
    lic = settings["licensing"]
    v = Verdict(ds.id, use, None, LEGAL_REVIEW, source="licence")
    licence = (ds.licence or "none").lower()
    if licence in ("none", "unknown", ""):
        v.reasons.append("No licence declared by the publisher")
        return v
    if licence == "proprietary":
        v.verdict = BLOCKED
        v.reasons.append("Proprietary data: rights come only from a signed contract")
        return v
    if licence in lic["non_commercial"]:
        v.verdict = BLOCKED if use in ("v:CommercialProduct", "v:Redistribution") else LEGAL_REVIEW
        v.reasons.append(f"{licence} is non-commercial; use inside an investment firm needs legal sign-off")
        return v
    if licence in lic["open_licences"] or licence in lic["share_alike"]:
        if use in ("v:InternalResearch", "v:AIProcessing"):
            v.verdict = PERMITTED
            v.reasons.append(f"{licence} permits internal use, including processing by third-party AI providers")
        else:
            v.verdict = CONDITIONAL
            v.conditions.append(f"Keep the {licence} licence text and attribution with anything shared")
            if licence in lic["share_alike"]:
                v.conditions.append("Share-alike: derived data must carry the same licence")
        return v
    v.reasons.append(f"Licence '{licence}' is not in the rules table")
    return v


def assess(s: Session, settings: Settings, dataset_id: str, use: str, customer_id: str | None = None,
           as_of: date | None = None) -> Verdict:
    ds = s.get(store.Dataset, dataset_id)
    if ds is None:
        raise KeyError(dataset_id)
    as_of = as_of or settings.as_of
    v = _licence_only(ds, use, settings)

    # Vendor text that contradicts the licence tag, or tries to instruct us, goes to legal (never auto-permitted).
    lic = settings["licensing"]
    claim = ds.card_claims or ""
    if claim:
        if scan_injection(claim):
            v.verdict, v.source = LEGAL_REVIEW, "licence"
            v.reasons.append("Vendor text contains instruction-like content; rights must be checked by a person")
        elif lic["card_claim_conflict_requires_legal_review"] and _COMMERCIAL_CLAIM.search(claim) and \
                (ds.licence or "none") in ("none", "unknown", "proprietary"):
            v.verdict = LEGAL_REVIEW
            v.reasons.append(f"Vendor text claims '{claim.strip()[:80]}' but the licence tag is '{ds.licence}'")

    # A recorded legal decision for this dataset and use overrides LEGAL_REVIEW (both ways).
    if v.verdict == LEGAL_REVIEW:
        dec = s.exec(select(store.Approval).where(store.Approval.kind == "licence",
                                                  store.Approval.subject_id == dataset_id,
                                                  store.Approval.status != "pending")).all()
        for a in sorted(dec, key=lambda a: a.decided_at or a.requested_at):
            if use in a.payload.get("uses", []):
                v.verdict = PERMITTED if a.status == "approved" else BLOCKED
                v.reasons.append(f"Legal decision by {a.decided_by}: {a.note or a.status}")
                v.source = f"legal decision {a.id}"

    if customer_id is None:
        return v
    v.customer_id = customer_id

    # Customer-specific: paid data needs an active contract that names the use.
    if ds.price_model != "free" or ds.licence == "proprietary":
        active = [c for c in store.tenant(s, store.Contract, customer_id)
                  if dataset_id in c.datasets and c.status == "active" and c.start <= as_of <= c.end]
        if not active:
            expired = [c for c in store.tenant(s, store.Contract, customer_id) if dataset_id in c.datasets]
            v.verdict = BLOCKED
            v.reasons = ["No active contract" + (f" (contract {expired[0].id} ended {expired[0].end})" if expired else "")]
            v.source = "contract"
            return v
        c = active[0]
        v.source = f"contract {c.id}"
        if use in c.permitted_use:
            v.verdict, v.reasons = PERMITTED, [f"Contract {c.id} permits {use.split(':')[1]} until {c.end}"]
        elif use == "v:Redistribution" and c.redistribution:
            v.verdict, v.reasons = PERMITTED, [f"Contract {c.id} permits redistribution"]
        else:
            v.verdict, v.reasons = BLOCKED, [f"Contract {c.id} does not permit {use.split(':')[1]}"]
        return v

    # Free data: the customer must have registered it (and the licence verdict applies).
    regs = [r for r in store.tenant(s, store.Registration, customer_id) if r.dataset_id == dataset_id
            and r.status == "active"]
    if not regs:
        v.verdict = BLOCKED
        v.reasons = ["Not registered by this customer"]
        v.source = "registration"
        return v
    if use not in regs[0].use and v.allowed:
        v.verdict = BLOCKED
        v.reasons.append(f"Registered for {', '.join(u.split(':')[1] for u in regs[0].use)} only")
    v.source = v.source if v.source.startswith("legal") else "registration + licence"
    return v


def entitlements(s: Session, settings: Settings, customer_id: str, use: str | None = None) -> list[Verdict]:
    """Every dataset this customer may use, per use case (PERMITTED / CONDITIONAL only)."""
    out = []
    for ds in s.exec(select(store.Dataset)).all():
        for u in ([use] if use else USES):
            v = assess(s, settings, ds.id, u, customer_id)
            if v.allowed:
                out.append(v)
    return out


def matrix(s: Session, settings: Settings, customer_id: str | None = None) -> list[dict]:
    rows = []
    for ds in s.exec(select(store.Dataset).order_by(store.Dataset.id)).all():
        row = {"dataset_id": ds.id, "title": ds.title, "licence": ds.licence}
        for u in USES:
            v = assess(s, settings, ds.id, u, customer_id)
            not_registered = v.reasons == ["Not registered by this customer"]
            row[u.split(":")[1]] = (assess(s, settings, ds.id, u).verdict + " · register") if not_registered else v.verdict
        rows.append(row)
    return rows


def renewals(s: Session, settings: Settings, customer_id: str | None = None) -> list[dict]:
    """Contracts whose notice deadline falls within the alert window (FR-7)."""
    from datetime import timedelta

    as_of = settings.as_of
    window = settings["contracts"]["renewal_alert_days"]
    q = select(store.Contract) if customer_id is None else select(store.Contract).where(
        store.Contract.customer_id == customer_id)
    out = []
    for c in s.exec(q).all():
        if c.status != "active":
            continue
        deadline = c.end - timedelta(days=c.notice_days)
        days = (deadline - as_of).days
        if days <= window:
            out.append({"contract_id": c.id, "customer_id": c.customer_id, "datasets": c.datasets, "end": c.end.isoformat(),
                        "notice_deadline": deadline.isoformat(), "days_to_deadline": days, "auto_renew": c.auto_renew,
                        "price_usd": c.price_usd})
    return sorted(out, key=lambda r: r["days_to_deadline"])
