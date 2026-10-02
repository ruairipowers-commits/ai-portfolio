"""Config, paths and the SQLite index (FTS5 for BM25 + sqlite-vec for vectors) with its audit tables."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec
import yaml

from . import demo


def _find_root() -> Path:
    if os.getenv("RQA_ROOT"):
        return Path(os.environ["RQA_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


def workspace() -> Path:
    """Where mutable data lives: the project root, or this visitor's sandbox in the hosted demo."""
    return demo.current() or ROOT


@dataclass
class Settings:
    raw: dict

    @classmethod
    def load(cls) -> "Settings":
        return cls(yaml.safe_load((ROOT / "config" / "settings.yaml").read_text()))

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def db_path(self) -> Path:
        return workspace() / os.getenv("RQA_DB_PATH", self.raw["db_path"])

    @property
    def corpus_dir(self) -> Path:
        return workspace() / self.raw["corpus_dir"]


def users(settings: Settings) -> dict[str, dict]:
    return yaml.safe_load((ROOT / settings["users_file"]).read_text())["users"]


SCHEMA = """
create table if not exists documents (
  doc_id text primary key, file text, title text, company text, ticker text, doc_type text, source text,
  published text, entitlement text, licence text, ai_processing integer, sha256 text, pages integer,
  chunks integer default 0, quarantined integer default 0, pii_redactions integer default 0,
  status text, ingested_at text);
create table if not exists chunks (
  rowid integer primary key, chunk_id text unique, doc_id text, page integer, section text, text text,
  words integer, sha text, entitlement text, ai_processing integer, quarantined integer default 0,
  quarantine_reason text, config_hash text, doc_sha text, embedding blob);
create index if not exists chunks_doc on chunks (doc_id);
create virtual table if not exists chunks_fts using fts5(text, content='chunks', content_rowid='rowid',
  tokenize='porter unicode61');
create table if not exists quarantine (
  chunk_id text, doc_id text, page integer, reason text, text text, ts text);
create table if not exists index_runs (
  index_version text, ts text, embedding_model text, dimensions integer, chunk_words integer, overlap_words integer,
  docs integer, docs_changed integer, docs_unchanged integer, chunks integer, quarantined integer,
  dedup_dropped integer, pii_redactions integer, embed_tokens integer, active integer);
create table if not exists answers (
  answer_id text primary key, ts text, run_id text, user_id text, question_sha text, question text, status text,
  refusal_reason text, answer text, citations text, model_name text, model_id text, prompt_sha text,
  index_version text, embedding_model text, retrieval_mode text, top_k integer, context_chunks text,
  excluded_entitlement integer, excluded_licence integer, input_tokens integer, output_tokens integer,
  cost_usd real, latency_ms integer, supported_ratio real, citations_verified integer, flags text,
  used_fallback integer);
create table if not exists feedback (ts text, answer_id text, user_id text, rating text, note text);
"""


def connect(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.db_path, timeout=10)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
