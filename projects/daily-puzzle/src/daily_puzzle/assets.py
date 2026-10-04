"""Public data a puzzle may use: the allow-list check (DATA-04) and staging files into a sandbox workspace.

Only trusted code here touches the network: files are fetched from the Hugging Face Hub *before* a sandbox run,
at a pinned revision, after the Hub's licence metadata is checked against config. The sandbox itself is offline.
Bundled fixtures (fixtures/<name>/) stand in for Hub files so CI and the offline demo need no network.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import Settings, root

PICKLE_TYPES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".joblib")


def short(asset_id: str) -> str:
    return asset_id.rstrip("/").split("/")[-1]


def allow_list(s: Settings | None = None) -> dict[str, dict]:
    s = s or Settings.load()
    return {a["id"]: a for a in s.puzzles["data_sources"]["assets"]}


def check(refs: list[dict], s: Settings | None = None, live: bool | None = None) -> list[str]:
    """Problems with a draft's asset references (empty = allowed). Each ref is {id, files}."""
    s = s or Settings.load()
    ds = s.puzzles["data_sources"]
    allowed = allow_list(s)
    live = os.getenv("PUZZLE_LIVE_ASSETS") == "1" if live is None else live
    problems = []
    for r in refs or []:
        aid, files = r.get("id", ""), r.get("files") or []
        entry = allowed.get(aid)
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in PICKLE_TYPES:
                problems.append(f"{aid}/{f}: pickle-based file types can run code when loaded; only safetensors/CSV/JSON/text")
            elif ext not in ds["allowed_file_types"]:
                problems.append(f"{aid}/{f}: file type {ext or '(none)'} is not allowed")
        if not entry:
            problems.append(f"{aid}: not on the data allow-list (config/puzzles.yaml → data_sources.assets)")
            continue
        if entry["license"] not in ds["allowed_licenses"]:
            problems.append(f"{aid}: licence {entry['license']} is not an allowed licence")
        extra = [f for f in files if f not in entry["files"]]
        if extra:
            problems.append(f"{aid}: files not on the allow-list: {', '.join(extra)}")
        if entry["source"] == "huggingface" and live:
            problems += _hub_check(entry, files, ds)
    return problems


def _hub_check(entry: dict, files: list[str], ds: dict) -> list[str]:
    """Live: the Hub's own licence tag must match ours and every file must fit the size cap."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return [f"{entry['id']}: huggingface_hub is not installed (pip install '.[hub]')"]
    try:
        info = HfApi().model_info(entry["id"], files_metadata=True) if entry["kind"] == "model" else \
            HfApi().dataset_info(entry["id"], files_metadata=True)
    except Exception as e:  # noqa: BLE001
        return [f"{entry['id']}: can't read Hub metadata ({type(e).__name__})"]
    tags = [t.split(":", 1)[1] for t in (info.tags or []) if t.startswith("license:")]
    out = [] if entry["license"] in tags else [f"{entry['id']}: Hub licence is {tags or 'missing'}, config says {entry['license']}"]
    sizes = {x.rfilename: (x.size or 0) for x in (info.siblings or [])}
    for f in files:
        if f not in sizes:
            out.append(f"{entry['id']}: {f} doesn't exist in the repo")
        elif sizes[f] > ds["max_mb"] * 2**20:
            out.append(f"{entry['id']}: {f} is {sizes[f] / 2**20:.0f} MB (cap {ds['max_mb']} MB)")
    entry["_revision"] = info.sha
    return out


def revision(asset_id: str) -> str:
    """The revision a puzzle is pinned to: the bundled fixture's version, or the Hub commit resolved at check time."""
    e = allow_list().get(asset_id, {})
    return e.get("_revision") or ("fixture-v1" if e.get("source") == "fixture" else "unresolved")


def stage(ref: dict, data_dir: Path) -> None:
    """Copy one asset's files into a sandbox workspace as data/<name>/<file>. Refuses anything not allow-listed."""
    entry = allow_list().get(ref["id"])
    if not entry:
        raise PermissionError(f"{ref['id']} is not allow-listed")
    dest = data_dir / short(ref["id"])
    dest.mkdir(parents=True, exist_ok=True)
    for f in ref.get("files") or entry["files"]:
        if f not in entry["files"] or Path(f).suffix.lower() in PICKLE_TYPES:
            raise PermissionError(f"{ref['id']}/{f} is not allow-listed")
        if entry["source"] == "fixture":
            shutil.copy2(root() / "fixtures" / short(ref["id"]) / f, dest / f)
        else:
            from huggingface_hub import hf_hub_download
            p = hf_hub_download(entry["id"], f, revision=ref.get("revision") or entry.get("_revision"),
                                repo_type="dataset" if entry["kind"] == "dataset" else "model")
            shutil.copy2(p, dest / f)
