-- Portable SQL (SQLite and Postgres). Business tables are read by the MCP server;
-- resolutions/outbox are written ONLY via the approval-gated tool; audit_* by the agent runtime.

create table trades (
  trade_id text primary key, fund text not null, account text not null, ticker text not null,
  side text not null, quantity integer not null, booked_price numeric not null, exec_avg_price numeric not null,
  trade_date date not null, settle_date date not null, broker text not null, status text not null
);
create table allocations (trade_id text not null, sub_account text not null, quantity integer not null);
create table broker_confirms (
  confirm_id text primary key, trade_id text not null, broker text not null, quantity integer,
  price numeric, settle_date date, account_ref text, free_text text, received_at timestamp
);
create table custodian_records (
  trade_id text primary key, custodian text not null, raw_payload text not null, received_at timestamp
);
create table ssis (
  counterparty text primary key, account_ref text not null, bic text not null,
  effective_date date not null, verified_by text not null
);
create table exceptions (
  exception_id text primary key, trade_id text not null, detected_by text not null,
  description text not null, opened_at timestamp not null, status text not null
);
create table historical_resolutions (
  exception_id text primary key, category text not null, fix_type text not null, notes text not null
);

-- written only through the gated write tool
create table resolutions (
  exception_id text primary key, category text not null, fix_type text not null, fix_details text not null,
  approved_by text not null, approval_id text not null, recorded_at timestamp not null
);
create table outbox (
  message_id text primary key, exception_id text not null, recipient text not null, subject text not null,
  body text not null, approved_by text not null, created_at timestamp not null, sent boolean not null default false
);
