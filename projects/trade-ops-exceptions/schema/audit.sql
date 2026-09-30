-- Agent runtime tables (OBS-01, COST-02, HITL-02/03). Written by the Python runtime, never by the model.
create table if not exists agent_runs (
  run_id text not null, exception_id text not null, thread_id text primary key, model_name text,
  prompt_sha text, status text not null, category text, fix_type text, steps integer, tool_calls integer,
  input_tokens integer, output_tokens integer, cost_usd numeric, policy_flags text, proposal_json text,
  started_at timestamp not null, updated_at timestamp not null
);
create table if not exists agent_steps (
  thread_id text not null, step integer not null, kind text not null, name text, args_json text,
  result_sha text, result_preview text, input_tokens integer, output_tokens integer, cost_usd numeric,
  flag text, ts timestamp not null
);
create table if not exists approvals (
  approval_id text primary key, thread_id text not null, exception_id text not null, decision text not null,
  approver text not null, ai_fix_type text, final_fix_type text, edited boolean not null, note text,
  ts timestamp not null
);
