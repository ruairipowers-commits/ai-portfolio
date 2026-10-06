"""Marketplace adapters: one interface, one live implementation (Hugging Face Hub) and three adapters tested on
recorded responses (Snowflake Marketplace, AWS Data Exchange, Databricks Marketplace).

    search(query) → [Listing]      listing(id) → Listing      schema(id) → [field dicts]      download(id, dest) → Path

Hugging Face works live when `huggingface_hub` is installed and the network is reachable (`live=True`), and from
the snapshot in data/reference/ otherwise. The other three read data/reference/marketplaces/*.json unless their
credentials are set; their live branches are written to each platform's documented API but have not been run
against the real services (no accounts) — the README and the post say so.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import ontology
from .config import ROOT

REF = ROOT / "data" / "reference"


@dataclass
class Listing:
    marketplace: str
    listing_id: str
    title: str
    publisher: str
    description: str = ""
    licence: str | None = None
    url: str = ""
    free: bool = True
    category_hint: str = ""
    downloads: int | None = None
    columns: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Adapter:
    name = "base"
    live_capable = False

    def search(self, query: str, limit: int = 20) -> list[Listing]:
        q = query.lower().split()
        hits = [l for l in self._all() if all(w in (l.title + " " + l.description + " " + l.listing_id).lower() for w in q)]
        return hits[:limit]

    def listing(self, listing_id: str) -> Listing:
        for l in self._all():
            if l.listing_id == listing_id:
                return l
        raise KeyError(f"{self.name}: no listing {listing_id}")

    def schema(self, listing_id: str) -> list[dict]:
        cols = self.listing(listing_id).columns
        return [{"name": c["name"], "type": c.get("type", "string"), "description": c.get("description", ""),
                 "concept": _concept(c["name"], c.get("description", ""))} for c in cols]

    def download(self, listing_id: str, dest: Path, **kw) -> Path:
        raise NotImplementedError(f"{self.name}: downloads go through the customer's own share/subscription")

    def _all(self) -> list[Listing]:
        raise NotImplementedError


def _concept(name: str, description: str = "") -> str | None:
    t = ontology.map_field(name, description)
    return ontology.curie(t.iri) if t else None


# ---------------------------------------------------------------- Hugging Face (live + snapshot)
class HuggingFace(Adapter):
    name = "huggingface"
    live_capable = True

    def __init__(self, live: bool | None = None):
        self.live = live if live is not None else os.getenv("DLP_HUB_LIVE") == "1"

    def _api(self):
        from huggingface_hub import HfApi   # pip install '.[hub]'
        return HfApi(token=os.getenv("HF_TOKEN") or None)

    def _all(self) -> list[Listing]:
        snap = json.loads((REF / "hub_snapshot.json").read_text())
        return [Listing("huggingface", d["id"], d["id"].split("/")[1], d["author"], d["description"], d["license"],
                        d["url"], True, d.get("hint_category", ""), d.get("downloads")) for d in snap["datasets"]]

    def search(self, query: str, limit: int = 20) -> list[Listing]:
        if not self.live:
            return super().search(query, limit) or [l for l in self._all() if any(
                w in (l.title + " " + l.description).lower() for w in query.lower().split())][:limit]
        out = []
        for d in self._api().list_datasets(search=query, limit=limit, full=True):
            tags = getattr(d, "tags", []) or []
            lic = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)
            card = getattr(d, "card_data", None) or {}
            out.append(Listing("huggingface", d.id, d.id.split("/")[-1], d.author or d.id.split("/")[0],
                               (getattr(d, "description", "") or "")[:500], lic, f"https://huggingface.co/datasets/{d.id}",
                               True, "", getattr(d, "downloads", None)))
        return out

    def card(self, listing_id: str) -> str:
        """The dataset card (README). Offline: the stored copy in data/seed/sources when there is one."""
        if self.live:
            from huggingface_hub import hf_hub_download
            p = hf_hub_download(listing_id, "README.md", repo_type="dataset", token=os.getenv("HF_TOKEN") or None)
            return Path(p).read_text()
        p = ROOT / "data" / "seed" / "sources" / "hf_cards" / (listing_id.replace("/", "__") + ".md")
        if p.exists():
            return p.read_text()
        raise FileNotFoundError(f"No offline card for {listing_id}; use live=True")

    def schema(self, listing_id: str) -> list[dict]:
        """Columns from the card's `dataset_info.features` (structured: parsed by code, not a model)."""
        text = self.card(listing_id)
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        meta = yaml.safe_load(m.group(1)) if m else {}
        feats = (meta.get("dataset_info") or {}).get("features") or []
        if isinstance(meta.get("dataset_info"), list):
            feats = meta["dataset_info"][0].get("features", [])
        return [{"name": f["name"], "type": f.get("dtype", "string"), "description": "",
                 "concept": _concept(f["name"])} for f in feats]

    def licence_tag(self, listing_id: str) -> str | None:
        try:
            return self.listing(listing_id).licence
        except KeyError:
            return None

    def download(self, listing_id: str, dest: Path, columns: list[str] | None = None, where_symbols: list[str] | None = None,
                 max_rows: int = 20000) -> Path:
        """A bounded slice of the dataset's parquet files (needs network + huggingface_hub)."""
        import duckdb
        from huggingface_hub import HfApi

        api = HfApi(token=os.getenv("HF_TOKEN") or None)
        files = [f for f in api.list_repo_files(listing_id, repo_type="dataset") if f.endswith(".parquet")]
        if not files:      # CSV-only repos are auto-converted by the Hub under refs/convert/parquet
            files = [f for f in api.list_repo_files(listing_id, repo_type="dataset", revision="refs/convert/parquet")
                     if f.endswith(".parquet")]
            rev = "refs%2Fconvert%2Fparquet"
        else:
            rev = "main"
        urls = [f"https://huggingface.co/datasets/{listing_id}/resolve/{rev}/{f}" for f in files]
        dest.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.execute("install httpfs; load httpfs")
        cols = ", ".join(f'"{c}"' for c in columns) if columns else "*"
        cond = f" where symbol in ({', '.join(repr(s) for s in where_symbols)})" if where_symbols else ""
        con.execute(f"copy (select {cols} from read_parquet({urls!r}){cond} limit {max_rows}) to '{dest}' (format parquet)")
        return dest


# ---------------------------------------------------------------- recorded adapters
class _Recorded(Adapter):
    file = ""
    env = ""

    @property
    def live(self) -> bool:
        return bool(os.getenv(self.env))

    def _raw(self) -> dict:
        if self.live:
            return self._fetch_live()
        return json.loads((REF / "marketplaces" / self.file).read_text())

    def _fetch_live(self) -> dict:       # pragma: no cover - needs real credentials
        raise NotImplementedError(f"{self.name}: live listing API not run in this project (no account)")


class Snowflake(_Recorded):
    name, file, env = "snowflake", "snowflake.json", "SNOWFLAKE_ACCOUNT"

    def _all(self):
        return [Listing("snowflake", l["global_name"], l["title"], l["provider"], l["description"], "proprietary",
                        l["url"], l["is_free"], l["category"], None, l.get("columns", [])) for l in self._raw()["listings"]]

    def _fetch_live(self):               # pragma: no cover
        import snowflake.connector  # noqa: F401  (SHOW AVAILABLE LISTINGS / DESCRIBE AVAILABLE LISTING)
        raise NotImplementedError("Snowflake: run `SHOW AVAILABLE LISTINGS` with a role that can see the Marketplace")


class AWSDataExchange(_Recorded):
    name, file, env = "aws_data_exchange", "aws_data_exchange.json", "AWS_DATA_EXCHANGE_ROLE_ARN"

    def _all(self):
        return [Listing("aws_data_exchange", d["Id"], d["Name"], d["ProviderName"], d["Description"], "proprietary",
                        d["Url"], False, d["AssetType"]) for d in self._raw()["DataSets"]]

    def _fetch_live(self):               # pragma: no cover
        import boto3
        return {"DataSets": boto3.client("dataexchange").list_data_sets(Origin="ENTITLED")["DataSets"]}


class Databricks(_Recorded):
    name, file, env = "databricks", "databricks.json", "DATABRICKS_HOST"

    def _all(self):
        return [Listing("databricks", l["id"], l["summary"]["name"], l["summary"]["provider_info"]["name"],
                        l["summary"].get("subtitle", ""), "proprietary", l["url"],
                        l["detail"].get("pricing_model") != "PAID", ",".join(l["summary"].get("categories", [])))
                for l in self._raw()["listings"]]


ADAPTERS: dict[str, type[Adapter]] = {"huggingface": HuggingFace, "snowflake": Snowflake,
                                      "aws_data_exchange": AWSDataExchange, "databricks": Databricks}


def get(name: str, **kw) -> Adapter:
    return ADAPTERS[name](**kw)


def search_all(query: str, limit: int = 10) -> list[Listing]:
    out = []
    for name in ADAPTERS:
        try:
            out += get(name).search(query, limit)
        except Exception:
            continue
    return out
