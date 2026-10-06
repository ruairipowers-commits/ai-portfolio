"""The managed catalog: CRUD for vendors and datasets (with operator-defined custom fields), AI-assisted cataloguing
from vendor pages, cards and dictionaries, and the approval queue every consequential write passes through.

AI cataloguing (FR-2):
  structured sources (OpenAPI, CSV dictionary, Hub card features) → parsed by code
  unstructured sources (vendor web pages, PDF/markdown dictionaries) → the model drafts, with a quote per value
  then, in code: injection scan, quote check (each value must quote the source), concept check against the
  vocabulary, licence text kept as an untrusted claim (never becomes the licence tag), PII redaction.
Nothing reaches the catalog until a named reviewer approves the draft (HITL-02); their edits are kept as feedback
for the eval set (HITL-03).
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from typing import Any

from sqlmodel import Session, select

from . import marketplaces, ontology, store, telemetry
from .ai import Runner
from .config import Settings, now
from .guardrails import html_to_text, quotes_missing, sanitize_untrusted, scan_injection
from .schemas import Extraction

VENDOR_FIELDS = ("name", "website", "docs_url", "api_base_url", "hq", "status", "notes")
DATASET_FIELDS = ("title", "description", "category", "delivery", "frequency", "price_model", "list_price_usd",
                  "formats", "coverage", "identifiers", "listed_on", "hub_id", "substitute_for", "status")


# ---------------------------------------------------------------- CRUD
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def upsert_vendor(s: Session, data: dict, actor: str = "") -> store.Vendor:
    vid = data.get("id") or "v-" + _slug(data["name"])
    v = s.get(store.Vendor, vid) or store.Vendor(id=vid, name=data["name"])
    for k in VENDOR_FIELDS:
        if k in data and data[k] is not None:
            setattr(v, k, data[k])
    if v.website and not str(v.website).startswith(("http://", "https://")):
        raise ValueError("website must be an http(s) URL")
    if "custom" in data:
        v.custom = {**(v.custom or {}), **store.validate_custom(s, "vendor", data["custom"])}
    if "marketplace_listings" in data:
        v.marketplace_listings = list(data["marketplace_listings"])
    if "provenance" in data:
        v.provenance = {**(v.provenance or {}), **data["provenance"]}
    v.updated_at = now()
    s.add(v)
    s.commit()
    telemetry.record("catalog_write", actor=actor, items=1, detail={"entity": "vendor"})
    return v


def upsert_dataset(s: Session, data: dict, actor: str = "") -> store.Dataset:
    did = data.get("id") or "ds-" + _slug(data["title"])
    d = s.get(store.Dataset, did) or store.Dataset(id=did, vendor_id=data["vendor_id"], title=data["title"])
    if "vendor_id" in data:
        if not s.get(store.Vendor, data["vendor_id"]):
            raise ValueError(f"Unknown vendor {data['vendor_id']}")
        d.vendor_id = data["vendor_id"]
    for k in DATASET_FIELDS:
        if k in data and data[k] is not None:
            setattr(d, k, data[k])
    if d.category and not ontology.term(d.category):
        raise ValueError(f"Unknown category {d.category}; use a DataCategory id from the vocabulary")
    if "custom" in data:
        d.custom = {**(d.custom or {}), **store.validate_custom(s, "dataset", data["custom"])}
    if "dictionary" in data:
        d.dictionary = [_checked_field(f) for f in data["dictionary"]]
    if "provenance" in data:
        d.provenance = {**(d.provenance or {}), **data["provenance"]}
    if "card_claims" in data:
        d.card_claims = data["card_claims"]
    d.updated_at = now()
    s.add(d)
    s.commit()
    telemetry.record("catalog_write", actor=actor, items=1, detail={"entity": "dataset"})
    return d


def set_licence(s: Session, dataset_id: str, licence: str, actor: str) -> store.Dataset:
    """The licence tag is set by a person, never by extraction (DATA-04)."""
    if not actor:
        raise ValueError("A named person must set a licence")
    d = s.get(store.Dataset, dataset_id)
    d.licence = licence.lower()
    d.provenance = {**(d.provenance or {}), "licence": f"set by {actor} on {date.today().isoformat()}"}
    s.add(d)
    s.commit()
    return d


def delete(s: Session, kind: str, id_: str) -> None:
    model = {"vendor": store.Vendor, "dataset": store.Dataset}[kind]
    obj = s.get(model, id_)
    if obj is None:
        raise KeyError(id_)
    if kind == "vendor" and s.exec(select(store.Dataset).where(store.Dataset.vendor_id == id_)).first():
        raise ValueError("Vendor still has datasets; delete or move them first")
    if kind == "dataset":
        live = [c.id for c in s.exec(select(store.Contract)).all() if id_ in c.datasets and c.status == "active"]
        if live:
            raise ValueError(f"Dataset is under active contract(s) {live}; retire it instead")
    s.delete(obj)
    s.commit()


def define_custom_field(s: Session, entity: str, key: str, label: str, type_: str, options: list | None = None,
                        bind_to: str | None = None) -> store.CustomFieldDef:
    if type_ not in ("text", "number", "date", "enum", "url", "bool"):
        raise ValueError("type must be text, number, date, enum, url or bool")
    if bind_to and not ontology.term(bind_to):
        raise ValueError(f"bind_to {bind_to} is not a vocabulary term")
    f = store.CustomFieldDef(id=f"cf-{entity}-{key}", entity=entity, key=key, label=label, type=type_,
                             options=options or [], bind_to=bind_to)
    s.merge(f)
    s.commit()
    return f


def _checked_field(f: dict) -> dict:
    """A dictionary field whose concept is a real vocabulary term (model proposals are re-checked)."""
    concept = f.get("concept")
    if concept and not ontology.term(concept):
        concept = None
    if not concept:
        t = ontology.map_field(f["name"], f.get("description", ""))
        concept = ontology.curie(t.iri) if t else None
    return {"name": f["name"], "type": f.get("type") or "string", "description": f.get("description", ""),
            "concept": concept}


# ---------------------------------------------------------------- structured schema sources (code, not a model)
def parse_openapi(text: str) -> list[dict]:
    spec = json.loads(text)
    out = []
    for name, sch in (spec.get("components", {}).get("schemas", {}) or {}).items():
        for col, p in (sch.get("properties") or {}).items():
            out.append(_checked_field({"name": col, "type": p.get("format") or p.get("type", "string"),
                                       "description": p.get("description", "")}))
    return out


def parse_csv_dictionary(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    key = lambda r, *ks: next((r[k] for k in ks if k in r), "")
    return [_checked_field({"name": key(r, "field", "name", "column"), "type": key(r, "type", "dtype"),
                            "description": key(r, "description", "desc")}) for r in rows]


def hub_schema(listing_id: str, live: bool = False) -> list[dict]:
    return [_checked_field(f) for f in marketplaces.HuggingFace(live=live).schema(listing_id)]


# ---------------------------------------------------------------- AI extraction
def extract(settings: Settings, text: str, source_url: str, kind: str = "auto", actor: str = "",
            runner: Runner | None = None, vendor_id: str | None = None) -> store.Approval:
    """Draft vendor/dataset records from a source and queue them for approval. Returns the pending approval."""
    kind = kind if kind != "auto" else ("openapi" if text.lstrip().startswith("{") and '"openapi"' in text[:200]
                                        else "csv" if text.lower().startswith(("field,", "name,", "column,"))
                                        else "html" if "<html" in text[:500].lower() else "text")
    flags: list[str] = []
    draft: dict[str, Any] = {"vendor": {}, "dataset": {}, "fields": [], "source_url": source_url, "kind": kind}
    raw_text = html_to_text(text) if kind == "html" else text
    injected_lines = [l for l in raw_text.splitlines() if scan_injection(l)]
    if injected_lines:
        flags.append("injection_suspected")
    model_name, cost = "", 0.0
    if kind == "openapi":
        draft["fields"] = parse_openapi(text)
        spec = json.loads(text)
        draft["dataset"]["title"] = {"value": spec.get("info", {}).get("title", ""), "quote": spec.get("info", {}).get("title", "")}
        if spec.get("servers"):
            draft["vendor"]["api_base_url"] = {"value": spec["servers"][0]["url"], "quote": spec["servers"][0]["url"]}
    elif kind == "csv":
        draft["fields"] = parse_csv_dictionary(text)
    else:
        runner = runner or Runner(settings)
        clean, sflags = sanitize_untrusted(raw_text, settings["data"]["max_untrusted_chars"],
                                           settings["data"]["redact_pii"])
        if sflags["pii_redactions"]:
            flags.append("pii_redacted")
        concepts = ", ".join(sorted(ontology.curie(t.iri) for t in ontology.terms()
                                    if t.kind in ("Measure", "Identifier", "Concept")))
        r = runner.call("extract", "extract", {"source": clean}, Extraction, actor=actor, subject=source_url,
                        flags=flags, prompt_subs={"concepts": concepts})
        model_name, cost = r.model_name, r.cost_usd
        if not r.ok:
            flags.append("extraction_failed")
        else:
            ex: Extraction = r.output
            src = clean.replace("&lt;", "<").replace("&gt;", ">")
            for side in ("vendor", "dataset"):
                vals = {k: v.model_dump() for k, v in getattr(ex, side).items()}
                missing = quotes_missing(vals, src)
                for k, v in vals.items():
                    if k in missing:
                        flags.append(f"unquoted:{side}.{k}")
                        continue
                    if any(v["quote"] and v["quote"][:40] in l for l in injected_lines):
                        flags.append(f"from_injected_text:{side}.{k}")     # a value lifted from injected text
                        continue
                    draft[side][k] = v
            draft["fields"] = [_checked_field(f.model_dump()) for f in ex.fields]
    # The licence the source states is a CLAIM: it goes to card_claims for legal, never to the licence tag.
    if "licence" in draft["dataset"]:
        draft["dataset"]["card_claims"] = draft["dataset"].pop("licence")
    with store.session(settings) as s:
        draft["match"] = suggest_match(s, draft, source_url, vendor_id)
        a = store.Approval(id=store.new_id("ap"), kind="extraction", subject_id=source_url, payload=draft,
                           flags=sorted(set(flags)), requested_by=actor or "system")
        a.payload = {**draft, "model": model_name, "cost_usd": cost}
        s.add(a)
        s.commit()
    return a


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    host = m.group(1).lower() if m else ""
    return ".".join(host.split(".")[-3:]) if host.endswith("example.com") else ".".join(host.split(".")[-2:])


def suggest_match(s: Session, draft: dict, source_url: str, vendor_id: str | None = None) -> dict:
    """Which existing vendor and dataset this source is about (by web domain, then title similarity), so an approved
    draft updates the record instead of creating a duplicate. The reviewer can override."""
    import difflib

    vendors = s.exec(select(store.Vendor)).all()
    dom = _domain(source_url)
    vid = vendor_id or next((v.id for v in vendors if v.website and dom and _domain(v.website) == dom), None)
    if not vid:
        name = str(draft.get("vendor", {}).get("name", {}).get("value", "")).lower()
        vid = next((v.id for v in vendors if name and v.name.lower() == name), None)
    cands = s.exec(select(store.Dataset).where(store.Dataset.vendor_id == vid)).all() if vid else \
        s.exec(select(store.Dataset)).all()
    title = " ".join(str(draft.get(side, {}).get(k, {}).get("value", "")) for side, k in
                     (("dataset", "title"), ("dataset", "description"), ("vendor", "name"))).lower()
    best = max(cands, key=lambda d: difflib.SequenceMatcher(None, d.title.lower(), title).ratio(), default=None)
    score = difflib.SequenceMatcher(None, best.title.lower(), title).ratio() if best else 0
    ds = best.id if best and (score > 0.35 or (vid and len(cands) == 1)) else None
    return {"vendor_id": vid, "dataset_id": ds, "score": round(score, 2)}


def apply_extraction(s: Session, a: store.Approval, reviewer: str, edits: dict | None = None) -> dict:
    """Write an approved draft into the catalog, with provenance (field → source URL)."""
    d = a.payload
    edits = edits or {}
    vals = lambda side: {k: v["value"] for k, v in d.get(side, {}).items()}
    vendor = {**vals("vendor"), **edits.get("vendor", {})}
    dataset = {**vals("dataset"), **edits.get("dataset", {})}
    for side, before in (("vendor", vals("vendor")), ("dataset", vals("dataset"))):
        for k, v in edits.get(side, {}).items():
            if before.get(k) != v:
                s.add(store.Feedback(kind="extraction", subject=f"{a.subject_id}#{side}.{k}", ai_output=str(before.get(k)),
                                     human_output=str(v), reviewer=reviewer))
    match = d.get("match", {})
    vid = edits.get("vendor_id") or match.get("vendor_id")
    target_ds = edits.get("dataset_id") or match.get("dataset_id")
    if vid and vendor:
        upsert_vendor(s, {"id": vid, **{k: v for k, v in vendor.items() if k != "name"},
                          "provenance": {k: d["source_url"] for k in vendor}}, actor=reviewer)
    if vendor.get("name") and not vid:
        prov = {k: d["source_url"] for k in vendor}
        v = upsert_vendor(s, {**vendor, "source": "extraction", "provenance": prov}, actor=reviewer)
        vid = v.id
    out = {"vendor_id": vid}
    if target_ds and d.get("kind") in ("openapi", "csv"):          # a schema source: attach the dictionary only
        out["dataset_id"] = upsert_dataset(s, {"id": target_ds, "dictionary": d.get("fields", []),
                                               "provenance": {"dictionary": d["source_url"]}}, actor=reviewer).id
    elif (dataset.get("title") or target_ds) and vid:
        ds = {k: dataset[k] for k in DATASET_FIELDS if k in dataset}
        if target_ds:
            ds["id"] = target_ds
            ds.pop("title", None) if s.get(store.Dataset, target_ds) else None
        if isinstance(ds.get("coverage"), str):
            ds["coverage"] = {"text": ds["coverage"]}
        if isinstance(ds.get("identifiers"), list):
            ids = [ontology.map_field(x) for x in ds["identifiers"]]
            ds["identifiers"] = [ontology.curie(t.iri) for t in ids if t]
        if "list_price_usd" in ds:
            try:
                ds["list_price_usd"] = float(ds["list_price_usd"])
                ds["price_model"] = "subscription"
            except (TypeError, ValueError):
                ds.pop("list_price_usd")
        if "history_start" in dataset:
            ds.setdefault("coverage", {})["history_start"] = dataset["history_start"]
        existing = s.get(store.Dataset, target_ds) if target_ds else None
        if existing:
            ds["coverage"] = {**(existing.coverage or {}), **(ds.get("coverage") or {})}
            ds["provenance"] = {k: d["source_url"] for k in dataset if k != "title"}
        ds["category"] = edits.get("dataset", {}).get("category") or (existing.category if existing else _guess_category(dataset))
        ds["vendor_id"] = vid
        if d.get("fields") or not existing:
            ds["dictionary"] = d.get("fields", [])
        ds.setdefault("provenance", {k: d["source_url"] for k in dataset})
        if "card_claims" in dataset:
            ds["card_claims"] = str(dataset["card_claims"])
        out["dataset_id"] = upsert_dataset(s, ds, actor=reviewer).id
    return out


def _guess_category(dataset: dict) -> str:
    text = " ".join(str(v) for v in dataset.values())
    hits = ontology.resolve(text, {"DataCategory"})
    return ontology.curie(hits[0].iri) if hits else "v:ReferenceData"


# ---------------------------------------------------------------- approvals (HITL-02)
def pending(s: Session, kind: str | None = None) -> list[store.Approval]:
    q = select(store.Approval).where(store.Approval.status == "pending")
    if kind:
        q = q.where(store.Approval.kind == kind)
    return list(s.exec(q.order_by(store.Approval.requested_at)).all())


def decide(settings: Settings, approval_id: str, reviewer: str, approve: bool, note: str = "",
           edits: dict | None = None) -> store.Approval:
    """Approve or reject any queued action. Approval applies it; both are recorded with the reviewer's name."""
    if not reviewer or not reviewer.strip():
        raise ValueError("A named reviewer is required (HITL-02)")
    from . import lifecycle, monetize

    with store.session(settings) as s:
        a = s.get(store.Approval, approval_id)
        if a is None or a.status != "pending":
            raise ValueError(f"{approval_id} is not pending")
        if approve:
            if a.kind == "extraction":
                a.payload = {**a.payload, "applied": apply_extraction(s, a, reviewer, edits)}
            elif a.kind == "contract":
                c = s.get(store.Contract, a.subject_id)
                c.status, c.signed_by = "active", reviewer
                s.add(c)
            elif a.kind == "retirement":
                lifecycle.apply_retirement(s, a, reviewer)
            elif a.kind == "listing":
                monetize.apply_listing(s, a, reviewer)
            # licence decisions are read by licensing.assess() from the approval itself
        a.status = "approved" if approve else "rejected"
        a.decided_by, a.decided_at, a.note = reviewer.strip(), now(), note
        s.add(a)
        s.commit()
        telemetry.emit("review", actor=reviewer, actor_type="named", records_in=1,
                       flags=[a.kind, a.status], detail={"approval_kind": a.kind})
        return a


def request_licence_review(settings: Settings, dataset_id: str, uses: list[str], requested_by: str,
                           customer_id: str | None = None) -> store.Approval:
    with store.session(settings) as s:
        a = store.Approval(id=store.new_id("ap"), kind="licence", subject_id=dataset_id, customer_id=customer_id,
                           payload={"uses": uses}, requested_by=requested_by)
        s.add(a)
        s.commit()
        return a
