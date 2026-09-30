"""Tiny DB layer: SQLite by default, Postgres when DATABASE_URL starts with postgres (optional extra).

The same SQL runs on both; `?` placeholders are translated for Postgres.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def is_pg(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


class Conn:
    def __init__(self, url: str):
        self.url, self.pg = url, is_pg(url)
        if self.pg:
            import psycopg  # pip install '.[postgres]'

            self.raw = psycopg.connect(url)
        else:
            Path(url).parent.mkdir(parents=True, exist_ok=True)
            self.raw = sqlite3.connect(url)
            self.raw.row_factory = sqlite3.Row

    def _sql(self, sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s") if self.pg else sql

    def execute(self, sql: str, params: tuple | list = ()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), params)
        return cur

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        cur = self.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def script(self, sql: str) -> None:
        sql = "\n".join(line.split("--")[0] for line in sql.splitlines())  # drop comments
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            self.execute(stmt)

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


def connect(url: str) -> Conn:
    return Conn(url)


def reset(con: Conn, schema_path: Path) -> None:
    tables = ["outbox", "resolutions", "historical_resolutions", "exceptions", "ssis", "custodian_records",
              "broker_confirms", "allocations", "trades", "agent_runs", "agent_steps", "approvals"]
    for t in tables:
        con.execute(f"drop table if exists {t}")
    con.script(schema_path.read_text())
    con.script((schema_path.parent / "audit.sql").read_text())
    con.commit()


def ensure_audit(con: Conn, root: Path) -> None:
    con.script((root / "schema" / "audit.sql").read_text())
    con.commit()


def insert_many(con: Conn, table: str, rows: list[tuple]) -> None:
    ph = ",".join("?" * len(rows[0]))
    for r in rows:
        con.execute(f"insert into {table} values ({ph})", r)
