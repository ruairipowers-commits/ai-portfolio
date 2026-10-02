"""Land the EOD feeds into Postgres `raw.*` (idempotent full reload) and create the kb/audit schemas."""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

from .store import ROOT, Settings, connect

SCHEMA = """
create schema if not exists raw;
create schema if not exists kb;
create schema if not exists audit;
create table if not exists audit.runs (
  run_id text primary key, ts timestamptz default now(), business_date date, as_of text, actor text, trigger text,
  status text, dbt_status text, breaks int, explained int, needs_human int, alerts int, cost_usd numeric,
  detail jsonb);
create table if not exists audit.explanations (
  explanation_id text primary key, run_id text, ts timestamptz default now(), business_date date, break_id text,
  break_type text, severity text, entity text, status text, model_name text, model_id text, prompt_sha text,
  kb_version text, likely_cause text, next_step text, runbook_refs jsonb, incident_refs jsonb, confidence numeric,
  needs_human boolean, flags jsonb, input_tokens int, output_tokens int, cost_usd numeric, latency_ms int,
  used_fallback boolean);
create table if not exists audit.alerts (
  alert_id text primary key, ts timestamptz default now(), business_date date, break_id text, channel text,
  severity text, title text, body text, sent boolean default false, sent_at timestamptz);
create table if not exists audit.feedback (
  ts timestamptz default now(), explanation_id text, break_id text, rating text, actor text, note text);
create table if not exists kb.quarantine (chunk_id text, doc_id text, reason text, text text, ts timestamptz default now());
create table if not exists kb.index_runs (
  kb_version text, ts timestamptz default now(), embedding_model text, dims int, docs int, docs_changed int,
  chunks int, quarantined int, pii_redactions int, active boolean);
"""

RAW = {   # table: (file, columns with types)
    "securities": ("reference/securities.csv", "ticker text, name text, ccy text, book text"),
    "feeds": ("reference/feeds.csv", "feed text, sla_time text, critical boolean"),
    "opening_positions": ("reference/opening_positions.csv", "as_of date, book text, ticker text, qty numeric"),
    "opening_prices": ("reference/opening_prices.csv", "as_of date, ticker text, close numeric"),
    "opening_fx": ("reference/opening_fx.csv", "as_of date, ccy text, usd_rate numeric"),
    "prices": ("*/prices.csv", "business_date date, ticker text, ccy text, close numeric"),
    "fx": ("*/fx.csv", "business_date date, ccy text, usd_rate numeric"),
    "trades": ("*/trades.csv", "business_date date, trade_id text, book text, ticker text, qty numeric, price numeric, booked_time text"),
    "pb_positions": ("*/pb_positions.csv", "business_date date, book text, ticker text, qty numeric"),
    "corp_actions": ("*/corp_actions.csv", "business_date date, ticker text, action text, ratio numeric"),
    "adjustments": ("*/adjustments.csv", "business_date date, book text, ticker text, qty numeric, reason text"),
    "reported_pnl": ("*/reported_pnl.csv", "business_date date, book text, pnl_usd numeric"),
    "file_arrivals": ("*/arrivals.csv", "business_date date, feed text, arrived_at timestamp, rows int"),
}


def generate(settings: Settings) -> str:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_data.py")], capture_output=True, text=True,
                       env={**os.environ, "EOD_LANDING_DIR": str(settings.landing_dir)})
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return r.stdout.strip()


def business_dates(settings: Settings) -> list[str]:
    return sorted(p.name for p in settings.landing_dir.glob("2*") if p.is_dir())


def load(settings: Settings) -> dict[str, int]:
    """Truncate-and-reload every raw table from the landing folder (all business dates)."""
    counts = {}
    with connect(settings) as con:
        con.execute(SCHEMA)
        for table, (pattern, cols) in RAW.items():
            con.execute(f"drop table if exists raw.{table} cascade")
            con.execute(f"create table raw.{table} ({cols})")
            files = sorted(settings.landing_dir.glob(pattern))
            n = 0
            for f in files:
                with f.open(newline="") as fh:
                    rows = list(csv.reader(fh))
                if len(rows) <= 1:
                    continue
                with con.cursor().copy(f"copy raw.{table} ({','.join(rows[0])}) from stdin") as cp:
                    for r in rows[1:]:
                        cp.write_row([v if v != "" else None for v in r])
                n += len(rows) - 1
            counts[table] = n
        con.commit()
    return counts
