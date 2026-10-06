"""Customers acquire data (FR-5) and integrate it (FR-6).

register()   free / openly licensed data: allowed straight away when the licence permits the uses; otherwise the
             registration waits for a legal decision.
subscribe()  paid data: a draft contract with term, notice, price, seats, permitted use and AI-processing terms. It
             becomes active only when a named approver signs it off (HITL-02). Entitlements follow from it.
feeds        scheduled pulls or downloads, refused unless the customer is entitled to the dataset right now.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from sqlmodel import select

from . import licensing, marketplaces, store, telemetry
from .config import ROOT, Settings, now


class NotEntitled(PermissionError):
    pass


def register(settings: Settings, customer_id: str, dataset_id: str, uses: list[str], actor: str) -> dict:
    with store.session(settings) as s:
        ds = s.get(store.Dataset, dataset_id)
        if ds is None:
            raise KeyError(dataset_id)
        if ds.price_model != "free":
            raise ValueError(f"{ds.title} is paid; it needs a contract (subscribe)")
        verdicts = {u: licensing.assess(s, settings, dataset_id, u) for u in uses}
        blocked = [u for u, v in verdicts.items() if v.verdict == licensing.BLOCKED]
        if blocked:
            raise ValueError(f"Licence does not allow: {', '.join(blocked)}")
        review = [u for u, v in verdicts.items() if v.verdict == licensing.LEGAL_REVIEW]
        reg = store.Registration(id=store.new_id("reg"), customer_id=customer_id, dataset_id=dataset_id, use=uses,
                                 registered=settings.as_of, status="active")
        s.add(reg)
        s.commit()
    out = {"registration_id": reg.id, "verdicts": {u: v.verdict for u, v in verdicts.items()}}
    if review:
        from .catalog import request_licence_review
        out["legal_review"] = request_licence_review(settings, dataset_id, review, actor, customer_id).id
    telemetry.record("register", actor=actor, items=1, flags=["legal_review"] if review else [])
    return out


def subscribe(settings: Settings, customer_id: str, dataset_ids: list[str], start: date, end: date, price_usd: float,
              permitted_use: list[str], actor: str, notice_days: int = 30, auto_renew: bool = False, seats: int = 1,
              billing: str = "annual", redistribution: bool = False) -> dict:
    if end <= start:
        raise ValueError("A contract must end after it starts")
    if price_usd <= 0:
        raise ValueError("A paid subscription needs a price")
    with store.session(settings) as s:
        for d in dataset_ids:
            if s.get(store.Dataset, d) is None:
                raise KeyError(d)
        c = store.Contract(id=store.new_id("c"), customer_id=customer_id, datasets=dataset_ids, start=start, end=end,
                           price_usd=price_usd, billing=billing, auto_renew=auto_renew, notice_days=notice_days,
                           seats=seats, permitted_use=permitted_use, redistribution=redistribution,
                           status="pending_approval")
        s.add(c)
        a = store.Approval(id=store.new_id("ap"), kind="contract", subject_id=c.id, customer_id=customer_id,
                           payload={"datasets": dataset_ids, "price_usd": price_usd, "start": start.isoformat(),
                                    "end": end.isoformat(), "permitted_use": permitted_use}, requested_by=actor)
        s.add(a)
        s.commit()
    telemetry.record("subscribe", actor=actor, items=1)
    return {"contract_id": c.id, "approval_id": a.id, "status": "pending_approval"}


def contracts_for(settings: Settings, customer_id: str) -> list[dict]:
    with store.session(settings) as s:
        return store.rows(store.tenant(s, store.Contract, customer_id))


# ---------------------------------------------------------------- feeds and downloads
FEED_KINDS = ("huggingface", "http", "file", "s3", "sftp", "snowflake_share")


def check_entitled(settings: Settings, customer_id: str, dataset_id: str, use: str = "v:InternalResearch") -> None:
    with store.session(settings) as s:
        v = licensing.assess(s, settings, dataset_id, use, customer_id)
    if not v.allowed:
        raise NotEntitled(f"{customer_id} may not use {dataset_id}: {'; '.join(v.reasons)}")


def create_feed(settings: Settings, customer_id: str, dataset_id: str, kind: str, config: dict, actor: str,
                schedule: str = "daily") -> store.Feed:
    if kind not in FEED_KINDS:
        raise ValueError(f"kind must be one of {FEED_KINDS}")
    check_entitled(settings, customer_id, dataset_id)
    with store.session(settings) as s:
        f = store.Feed(id=store.new_id("feed"), customer_id=customer_id, dataset_id=dataset_id, kind=kind,
                       config=config, schedule=schedule)
        s.add(f)
        s.commit()
    telemetry.record("feed_create", actor=actor, items=1, detail={"kind": kind})
    return f


def run_feed(settings: Settings, feed_id: str, customer_id: str, live: bool = False) -> dict:
    """Pull one delivery into the customer's landing folder. Entitlement is re-checked on every run (a contract
    can expire between runs)."""
    with store.session(settings) as s:
        f = s.get(store.Feed, feed_id)
        if f is None or f.customer_id != customer_id:
            raise KeyError(feed_id)                      # never reveal another firm's feed
    check_entitled(settings, customer_id, f.dataset_id)
    dest = settings.path("landing") / "deliveries" / customer_id / f"{f.dataset_id}_{now():%Y%m%d%H%M%S}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if f.kind == "huggingface" and live:
        marketplaces.HuggingFace(live=True).download(f.config["hub_id"], dest, max_rows=f.config.get("max_rows", 5000))
    elif f.kind in ("file", "huggingface"):
        src = Path(f.config.get("path") or settings.path("landing") / "options_iv.parquet")
        if not src.is_absolute():
            src = ROOT / src
        shutil.copy2(src, dest)
    elif f.kind == "http" and live:
        import urllib.request
        urllib.request.urlretrieve(f.config["url"], dest)          # noqa: S310 - URL comes from the operator's feed config
    else:
        raise NotImplementedError(f"{f.kind} feeds are adapters documented in docs/aws-native.md; not run offline")
    import pandas as pd
    rows = len(pd.read_parquet(dest)) if dest.suffix == ".parquet" else 0
    with store.session(settings) as s:
        f = s.get(store.Feed, feed_id)
        f.last_run, f.last_rows = now(), rows
        s.add(f)
        s.commit()
    telemetry.record("feed_run", items=rows, detail={"kind": f.kind})
    return {"feed_id": feed_id, "path": str(dest), "rows": rows}
