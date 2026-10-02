"""Config, paths and Postgres access.

`database_url: embedded` starts a local Postgres 16 with pgvector on demand (pgserver, data in warehouse/pg), so
the project runs with no Docker. Any postgresql:// URL (docker compose, RDS) works the same way.
In the hosted demo each visitor gets their own database, created from the baseline with CREATE DATABASE … TEMPLATE.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
import yaml
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from . import demo


def _find_root() -> Path:
    if os.getenv("EOD_ROOT"):
        return Path(os.environ["EOD_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


def workspace() -> Path:
    """Where mutable files live: the project root, or this visitor's sandbox in the hosted demo."""
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
    def landing_dir(self) -> Path:
        return workspace() / self.raw["landing_dir"]

    @property
    def kb_dir(self) -> Path:
        return workspace() / self.raw["kb_dir"]


# ---------------------------------------------------------------- server + database
_server_uri: str | None = None


def server_uri(settings: Settings) -> str:
    """A URI for the Postgres server (any database); starts the embedded server if configured."""
    global _server_uri
    url = os.getenv("EOD_DATABASE_URL") or settings["database_url"]
    if url != "embedded":
        return url
    if _server_uri is None:
        import pgserver  # pip install pgserver: Postgres 16 + pgvector binaries, no Docker

        mode = os.getenv("EOD_PG_CLEANUP") or None   # tests: "stop"; default: keep running between commands
        (ROOT / "warehouse").mkdir(parents=True, exist_ok=True)
        _server_uri = pgserver.get_server(ROOT / "warehouse" / "pg", cleanup_mode=mode).get_uri()
    return _server_uri


def database_name(settings: Settings) -> str:
    box = demo.current()
    if box is None:
        return settings["database_name"]
    return f"{settings['database_name']}_s_{hashlib.sha256(str(box).encode()).hexdigest()[:12]}"


def dsn(settings: Settings, dbname: str | None = None) -> str:
    info = conninfo_to_dict(server_uri(settings))
    info["dbname"] = dbname or database_name(settings)
    return make_conninfo(**{k: v for k, v in info.items() if v not in (None, "")})


_ready: set[str] = set()


def ensure_database(settings: Settings) -> str:
    """Create this workspace's database (from the baseline template in the hosted demo) with pgvector."""
    name = database_name(settings)
    key = f"{server_uri(settings)}|{name}"
    if key in _ready:
        return name
    with psycopg.connect(dsn(settings, "postgres"), autocommit=True) as admin:
        exists = admin.execute("select 1 from pg_database where datname = %s", (name,)).fetchone()
        if not exists:
            base = settings["database_name"]
            has_base = admin.execute("select 1 from pg_database where datname = %s", (base,)).fetchone()
            if name != base and has_base:
                admin.execute(f'create database "{name}" template "{base}"')
                _drop_orphans(admin, settings)
            else:
                admin.execute(f'create database "{name}"')
    with psycopg.connect(dsn(settings, name), autocommit=True) as con:
        con.execute("create extension if not exists vector")
    _ready.add(key)
    return name


def _drop_orphans(admin, settings: Settings) -> None:
    """Drop per-visitor databases whose sandbox folder has been pruned."""
    base = Path(os.getenv("DEMO_SESSIONS_DIR", "/tmp/demo-sessions")) / demo.PROJECT
    live = {f"{settings['database_name']}_s_{hashlib.sha256(str(d).encode()).hexdigest()[:12]}"
            for d in base.iterdir() if d.is_dir()} if base.exists() else set()
    for (db,) in admin.execute("select datname from pg_database where datname like %s",
                               (f"{settings['database_name']}_s_%",)).fetchall():
        if db not in live:
            admin.execute(f'drop database if exists "{db}" with (force)')


def connect(settings: Settings) -> psycopg.Connection:
    ensure_database(settings)
    return psycopg.connect(dsn(settings), row_factory=dict_row)


def dbt_env(settings: Settings) -> dict:
    info = conninfo_to_dict(dsn(settings))
    return {"EOD_PG_HOST": info.get("host", "localhost"), "EOD_PG_PORT": str(info.get("port", 5432)),
            "EOD_PG_USER": info.get("user", "postgres"), "EOD_PG_PASSWORD": info.get("password", ""),
            "EOD_PG_DBNAME": info["dbname"]}
