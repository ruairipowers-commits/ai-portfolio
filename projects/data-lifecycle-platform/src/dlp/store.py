"""Operational store: the managed catalog (vendors, datasets, custom fields), buyer firms, contracts, registrations,
approvals, feeds, data-owner submissions and the AI audit log.

This is the system of record people edit. It is mirrored into the knowledge graph (graph.py) and exported to the
semantic layer (semantic.py); neither of those is ever edited directly.
SQLite locally; Postgres via DLP_DATABASE_URL. Every customer-owned table carries customer_id and is only read
through `tenant()` so one firm never sees another's contracts, notes or usage (NFR-3).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from typing import Any, Iterable, Optional

import yaml
from sqlalchemy import JSON, Column, event
from sqlmodel import Field, Session, SQLModel, create_engine, select

from .config import ROOT, Settings, now

# ---------------------------------------------------------------- catalog


class CustomFieldDef(SQLModel, table=True):
    id: str = Field(primary_key=True)
    entity: str                                   # vendor | dataset
    key: str
    label: str
    type: str                                     # text | number | date | enum | url | bool
    options: list = Field(default_factory=list, sa_column=Column(JSON))
    bind_to: Optional[str] = None                 # ontology property or concept (e.g. "v:Ticker")


class Vendor(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    website: Optional[str] = None
    docs_url: Optional[str] = None
    api_base_url: Optional[str] = None
    hq: Optional[str] = None
    status: str = "prospect"                      # prospect | active | inactive
    source: str = "manual"                        # manual | huggingface | snowflake | aws_data_exchange | databricks | extraction
    marketplace_listings: list = Field(default_factory=list, sa_column=Column(JSON))
    custom: dict = Field(default_factory=dict, sa_column=Column(JSON))
    provenance: dict = Field(default_factory=dict, sa_column=Column(JSON))   # field → source URL (OBS-02)
    notes: Optional[str] = None
    synthetic: bool = False
    updated_at: datetime = Field(default_factory=now)


class Dataset(SQLModel, table=True):
    id: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", index=True)
    title: str
    description: str = ""
    hub_id: Optional[str] = None
    category: str = "v:ReferenceData"
    licence: str = "none"                          # SPDX-style id, "proprietary" or "none"
    card_claims: Optional[str] = None             # what the vendor's own text says about rights (untrusted)
    delivery: str = "file"                        # file | api | share
    formats: list = Field(default_factory=list, sa_column=Column(JSON))
    frequency: Optional[str] = None
    price_model: str = "free"                     # free | subscription | usage
    list_price_usd: Optional[float] = None
    coverage: dict = Field(default_factory=dict, sa_column=Column(JSON))
    identifiers: list = Field(default_factory=list, sa_column=Column(JSON))
    listed_on: list = Field(default_factory=list, sa_column=Column(JSON))
    substitute_for: list = Field(default_factory=list, sa_column=Column(JSON))
    dictionary: list = Field(default_factory=list, sa_column=Column(JSON))    # [{name,type,description,concept}]
    custom: dict = Field(default_factory=dict, sa_column=Column(JSON))
    provenance: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "listed"                        # listed | active | retired
    synthetic: bool = False
    updated_at: datetime = Field(default_factory=now)


# ---------------------------------------------------------------- buyers and commercial


class Customer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    kind: str = ""
    budget_usd: float = 0


class Team(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    name: str


class Member(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    team_id: str
    name: str


class Contract(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    datasets: list = Field(default_factory=list, sa_column=Column(JSON))
    start: date
    end: date
    price_usd: float
    billing: str = "annual"
    auto_renew: bool = False
    notice_days: int = 30
    seats: int = 1
    permitted_use: list = Field(default_factory=list, sa_column=Column(JSON))
    redistribution: bool = False
    status: str = "draft"                         # draft | pending_approval | active | expired | terminated
    signed_by: Optional[str] = None
    notes: Optional[str] = None


class Registration(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    dataset_id: str = Field(foreign_key="dataset.id")
    use: list = Field(default_factory=list, sa_column=Column(JSON))
    registered: date
    status: str = "active"


class Dependency(SQLModel, table=True):
    dataset_id: str = Field(primary_key=True)
    consumers: list = Field(default_factory=list, sa_column=Column(JSON))
    reports: list = Field(default_factory=list, sa_column=Column(JSON))


class Feed(SQLModel, table=True):
    id: str = Field(primary_key=True)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    dataset_id: str
    kind: str                                     # huggingface | http | file | s3 | sftp | snowflake_share
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    schedule: str = "daily"
    status: str = "active"
    last_run: Optional[datetime] = None
    last_rows: int = 0


# ---------------------------------------------------------------- human steps and audit


class Approval(SQLModel, table=True):
    """Every consequential write waits here for a named human (HITL-02)."""
    id: str = Field(primary_key=True)
    kind: str                                     # extraction | contract | licence | listing | retirement
    subject_id: str
    customer_id: Optional[str] = None
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    flags: list = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "pending"                       # pending | approved | rejected
    requested_by: str = "system"
    requested_at: datetime = Field(default_factory=now)
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    note: Optional[str] = None


class OwnerSubmission(SQLModel, table=True):
    id: str = Field(primary_key=True)
    company: str
    description: str
    sample_file: str
    status: str = "submitted"                     # submitted | assessed | blocked | listed | rejected
    assessment: dict = Field(default_factory=dict, sa_column=Column(JSON))


class AICall(SQLModel, table=True):
    """OBS-01 run log: one row per model call. Hashes and counts only, never the question or the data."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str
    ts: datetime = Field(default_factory=now)
    purpose: str
    subject: str = ""
    customer_id: Optional[str] = None
    actor: str = ""
    alias: str = ""
    model_name: str = ""
    provider: str = ""
    model_id: str = ""
    prompt_version: str = ""
    prompt_sha: str = ""
    input_sha: str = ""
    context_sha: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    used_fallback: bool = False
    status: str = "ok"
    flags: list = Field(default_factory=list, sa_column=Column(JSON))
    metric_queries: list = Field(default_factory=list, sa_column=Column(JSON))   # NFR-2: the SQL behind every number
    error: Optional[str] = None


class Feedback(SQLModel, table=True):
    """HITL-03: a reviewer's correction of an AI output, fed into evals."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=now)
    kind: str
    subject: str
    ai_output: str
    human_output: str
    reviewer: str
    note: str = ""


# ---------------------------------------------------------------- engine and helpers
_engines: dict[str, Any] = {}


def engine(settings: Settings | None = None):
    settings = settings or Settings.load()
    url = os.getenv("DLP_DATABASE_URL")
    if not url:
        p = settings.path("catalog_db")
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    if url not in _engines:
        eng = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        if url.startswith("sqlite"):
            @event.listens_for(eng, "connect")
            def _fk(dbapi_con, _):
                dbapi_con.execute("pragma foreign_keys=on")
        SQLModel.metadata.create_all(eng)
        _engines[url] = eng
    return _engines[url]


def session(settings: Settings | None = None) -> Session:
    return Session(engine(settings), expire_on_commit=False)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


TENANT_MODELS = (Contract, Registration, Feed, Team, Member)


def tenant(s: Session, model, customer_id: str):
    """The only way customer-owned rows are read: always filtered to one firm (NFR-3)."""
    if model not in TENANT_MODELS:
        raise ValueError(f"{model.__name__} is not tenant-scoped")
    return s.exec(select(model).where(model.customer_id == customer_id)).all()


# ---------------------------------------------------------------- custom fields
def validate_custom(s: Session, entity: str, values: dict) -> dict:
    """Check custom field values against the operator's definitions; unknown keys are rejected."""
    defs = {d.key: d for d in s.exec(select(CustomFieldDef).where(CustomFieldDef.entity == entity)).all()}
    out = {}
    for k, v in (values or {}).items():
        if k not in defs:
            raise ValueError(f"Unknown {entity} custom field '{k}' (define it first)")
        d = defs[k]
        if v is None or v == "":
            continue
        if d.type == "number":
            v = float(v)
        elif d.type == "bool":
            v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "y")
        elif d.type == "date":
            v = date.fromisoformat(str(v)).isoformat()
        elif d.type == "enum" and v not in d.options:
            raise ValueError(f"{k}: '{v}' is not one of {d.options}")
        elif d.type == "url" and not str(v).startswith(("http://", "https://")):
            raise ValueError(f"{k}: must be an http(s) URL")
        out[k] = v
    return out


# ---------------------------------------------------------------- seed
def reset(settings: Settings | None = None) -> None:
    eng = engine(settings)
    SQLModel.metadata.drop_all(eng)
    SQLModel.metadata.create_all(eng)


def seed(settings: Settings | None = None, path=None) -> dict:
    """Load data/seed/catalog.yaml into an empty store (idempotent: resets first)."""
    settings = settings or Settings.load()
    raw = yaml.safe_load((path or ROOT / "data" / "seed" / "catalog.yaml").read_text())
    reset(settings)
    with session(settings) as s:
        for i, f in enumerate(raw["custom_fields"]):
            s.add(CustomFieldDef(id=f"cf-{f['entity']}-{f['key']}", **{k: f[k] for k in f}))
        s.commit()
        for v in raw["vendors"]:
            v = dict(v)
            v["custom"] = validate_custom(s, "vendor", v.get("custom", {}))
            s.add(Vendor(**v))
        s.commit()
        for d in raw["datasets"]:
            d = dict(d)
            d["vendor_id"] = d.pop("vendor")
            d["custom"] = validate_custom(s, "dataset", d.get("custom", {}))
            d["status"] = "active" if d.get("hub_id") in (settings["hub"]["options_dataset"],) else "listed"
            s.add(Dataset(**d))
        for c in raw["customers"]:
            s.add(Customer(id=c["id"], name=c["name"], kind=c.get("kind", ""), budget_usd=c.get("budget_usd", 0)))
        s.commit()
        for c in raw["customers"]:
            for t in c["teams"]:
                s.add(Team(id=t["id"], customer_id=c["id"], name=t["name"]))
            for u in c["users"]:
                s.add(Member(id=u["id"], customer_id=c["id"], team_id=u["team"], name=u["name"]))
        for c in raw["contracts"]:
            c = dict(c)
            c["customer_id"] = c.pop("customer")
            c["start"], c["end"] = date.fromisoformat(c["start"]), date.fromisoformat(c["end"])
            s.add(Contract(**c))
        for r in raw["registrations"]:
            s.add(Registration(id=new_id("reg"), customer_id=r["customer"], dataset_id=r["dataset"], use=r["use"],
                               registered=date.fromisoformat(r["registered"])))
        for dep in raw.get("dependencies", []):
            s.add(Dependency(dataset_id=dep["dataset"], consumers=dep.get("consumers", []), reports=dep.get("reports", [])))
        s.commit()
    return {"vendors": len(raw["vendors"]), "datasets": len(raw["datasets"]), "customers": len(raw["customers"]),
            "contracts": len(raw["contracts"])}


def seed_extras() -> dict:
    """Factor sensitivities and proxies: knowledge that lives only in the graph."""
    raw = yaml.safe_load((ROOT / "data" / "seed" / "catalog.yaml").read_text())
    return {"factor_sensitivities": raw.get("factor_sensitivities", []), "factor_proxies": raw.get("factor_proxies", [])}


def rows(objs: Iterable[SQLModel]) -> list[dict]:
    return [json.loads(o.model_dump_json()) for o in objs]
