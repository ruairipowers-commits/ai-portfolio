"""DuckDB schema: one model that all three sources load into, plus the audit log (OBS-01).

Every source row keeps where it came from and when it was fetched (DATA-01). Numbers on screen and in summaries are
queries against these tables; nothing is computed by a model.
"""
from __future__ import annotations

import duckdb

from .config import Settings

SCHEMA = """
create table if not exists launches (
    launch_id varchar primary key,      -- 'll2:<uuid>' or 'gcat:<tag>'; merged rows keep the LL2 id
    ll2_id varchar, gcat_tag varchar, designator varchar,
    name varchar, net timestamptz, net_precision varchar, window_start timestamptz, window_end timestamptz,
    status varchar, status_abbrev varchar,
    outcome varchar,                    -- success | failure | partial | pending | unknown
    orbital boolean, category varchar,  -- category: orbital | suborbital | deep space
    provider varchar, provider_type varchar, country varchar,
    rocket varchar, rocket_family varchar, rocket_variant varchar,
    pad varchar, location varchar, pad_lat double, pad_lon double,
    mission_name varchar, mission_type varchar, industry varchar, mission_description varchar,
    orbit varchar, orbit_abbrev varchar, destination varchar, payload_mass_kg double,
    crewed boolean, failreason varchar, program varchar,
    image_url varchar, image_credit varchar, image_licence varchar,
    source varchar, source_updated timestamptz, fetched_at timestamptz
);
create table if not exists stages (
    launch_id varchar, stage_type varchar, serial varchar, reused boolean, flight_number integer,
    turnaround_days double, landing_attempt boolean, landing_success boolean, landing_type varchar,
    landing_location varchar, fetched_at timestamptz
);
create table if not exists spacecraft (
    launch_id varchar, serial varchar, name varchar, config varchar, destination varchar,
    landing_success boolean, landing_type varchar, landing_location varchar, splashdown boolean,
    fetched_at timestamptz
);
create table if not exists crew (
    launch_id varchar, name varchar, role varchar, agency varchar, nationality varchar, fetched_at timestamptz
);
create table if not exists net_snapshots (      -- delays are measured, not reported: one row per refresh per launch
    launch_id varchar, seen_at timestamptz, net timestamptz, status_abbrev varchar
);
create table if not exists vehicles (
    rocket varchar primary key, family varchar, provider varchar, first_launch timestamptz, last_launch timestamptz,
    launches integer, active_flag boolean
);
create table if not exists satcat (
    norad integer primary key, designator varchar, name varchar, object_type varchar, ops_status varchar,
    owner varchar, launch_date date, decay_date date, period_min double, inclination double,
    apogee_km double, perigee_km double, rcs double, fetched_at timestamptz
);
create table if not exists discrepancies (       -- the same launch in two sources, disagreeing: shown, not hidden
    launch_id varchar, field varchar, ll2_value varchar, gcat_value varchar, noted_at timestamptz
);
create table if not exists source_runs (
    source varchar, started_at timestamptz, finished_at timestamptz, mode varchar, rows integer,
    requests integer, status varchar, detail varchar
);
create table if not exists ll2_requests (ts timestamptz, url varchar, status integer);
create table if not exists reference_reviews (   -- HITL: a person approves a cost or reference entry before use
    entry_id varchar, table_name varchar, decision varchar, reviewer varchar, note varchar, reviewed_at timestamptz
);
create schema if not exists audit;
create table if not exists audit.ai_calls (
    run_id varchar, call_ts timestamptz, purpose varchar, subject varchar, alias varchar, model_name varchar,
    provider varchar, model_id varchar, prompt_version varchar, prompt_sha varchar, input_sha varchar,
    input_tokens integer, output_tokens integer, cost_usd double, latency_ms integer, used_fallback boolean,
    status varchar, flags varchar, error varchar
);
create table if not exists audit.summaries (
    run_id varchar, created_at timestamptz, purpose varchar, subject varchar, text varchar, citations varchar,
    accepted boolean, problems varchar, model_name varchar
);
"""

DATA_TABLES = ("launches", "stages", "spacecraft", "crew", "vehicles", "satcat", "discrepancies")


def connect(settings: Settings, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.db_path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    con.execute("set TimeZone = 'UTC'")
    return con


def rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def scalar(con, sql: str, params: list | None = None):
    r = con.execute(sql, params or []).fetchone()
    return r[0] if r else None
