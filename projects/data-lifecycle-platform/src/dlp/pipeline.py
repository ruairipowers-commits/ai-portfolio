"""The build: seed → ingest → schema sync → semantic layer (dbt build + tests) → knowledge graph (SHACL → load).

Each step is also a Dagster asset (orchestration/definitions.py); this module is the plain-Python path the CLI,
the app and CI use. A failed gate stops everything after it and says why.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import catalog, graph, ontology, semantic, store, telemetry
from .config import ROOT, Settings


def seed_all(settings: Settings) -> dict:
    """Load the seed catalog, then attach dictionaries from structured sources (parsed by code)."""
    out = store.seed(settings)
    raw = yaml.safe_load((ROOT / "data" / "seed" / "catalog.yaml").read_text())
    with store.session(settings) as s:
        for d in raw["datasets"]:
            src = d.get("dictionary_source")
            if not src:
                continue
            kind, _, ref = src.partition(":")
            if kind == "hub":
                fields = catalog.hub_schema(ref)
            elif kind == "openapi":
                fields = catalog.parse_openapi((ROOT / ref).read_text())
            elif kind == "csv":
                fields = catalog.parse_csv_dictionary((ROOT / ref).read_text())
            elif kind == "columns":
                fields = [catalog._checked_field({"name": c}) for c in ref.split(",")]
            else:
                continue
            catalog.upsert_dataset(s, {"id": d["id"], "dictionary": fields, "provenance": {"dictionary": src}})
    out["dictionaries"] = sum(1 for d in raw["datasets"] if d.get("dictionary_source"))
    return out


def ensure_landing(settings: Settings) -> str:
    """Use what's in data/landing (real Hub slices after `dlp fetch`), or build the offline fixture."""
    landing = settings.path("landing")
    need = ["options_iv.parquet", "constituents.parquet", "usage.csv"]
    if not all((landing / n).exists() for n in need):
        if landing != ROOT / settings["paths"]["landing"] and all((ROOT / settings["paths"]["landing"] / n).exists() for n in need):
            landing.mkdir(parents=True, exist_ok=True)       # demo sandbox: copy the baseline
            for n in need + ["SOURCE"]:
                if (ROOT / settings["paths"]["landing"] / n).exists():
                    shutil.copy2(ROOT / settings["paths"]["landing"] / n, landing / n)
        else:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")], check=True,
                           capture_output=True, cwd=ROOT)
    src = landing / "SOURCE"
    return src.read_text().strip() if src.exists() else "unknown"


def build(settings: Settings, reseed: bool = True) -> dict:
    t0 = time.perf_counter()
    report: dict = {"ontology": ontology.summary()}
    problems = ontology.check()
    if problems:
        raise RuntimeError("Ontology boundary check failed: " + "; ".join(problems))
    if reseed:
        report["seed"] = seed_all(settings)
    report["landing"] = ensure_landing(settings)
    report["semantic"] = semantic.build(settings)            # raises QualityGateError
    report["graph"] = graph.build(settings)                  # raises GraphValidationError
    report["seconds"] = round(time.perf_counter() - t0, 1)
    telemetry.record("build", items=report["graph"]["instance_triples"],
                     detail={"tests_passed": report["semantic"]["tests_passed"], "graph_conforms": report["graph"]["conforms"]})
    out = settings.path("warehouse_db").parent / "build_report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    return report


def refresh_graph(settings: Settings) -> dict:
    """After a catalog edit: re-export to the semantic layer and rebuild the graph (no reseed)."""
    semantic.build(settings)
    return graph.build(settings)
