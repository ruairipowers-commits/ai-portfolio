"""Runs the graph: opens MCP sessions with the right scope and the checkpointer, per command."""
from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import db, demo, policy as P, telemetry
from .agent import Runtime, build_graph, initial_state
from .llm import Budget, Registry


def find_root() -> Path:
    if os.getenv("TRADEOPS_ROOT"):
        return Path(os.environ["TRADEOPS_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = find_root()


def workspace() -> Path:
    """Where mutable data lives: the project root, or this visitor's sandbox in the hosted demo."""
    return demo.current() or ROOT


def load_settings() -> dict:
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())


def db_url(s: dict) -> str:
    url = os.getenv("DATABASE_URL", s["database_url"])
    return url if db.is_pg(url) else str(workspace() / url)


@asynccontextmanager
async def mcp_tools(s: dict, scope: str, signing_key: str | None = None):
    """Start the TypeScript MCP server as a subprocess with only the given scope."""
    env = {**os.environ, "DATABASE_URL": db_url(s), "MCP_TOOL_SCOPE": scope, "NODE_NO_WARNINGS": "1"}
    env.pop("APPROVAL_SIGNING_KEY", None)
    if scope == "write" or "write" in scope:
        env["APPROVAL_SIGNING_KEY"] = signing_key or ""
    params = StdioServerParameters(command=s["agent"]["mcp_command"],
                                   args=[str(ROOT / a) for a in s["agent"]["mcp_args"]], env=env, cwd=str(ROOT))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        tools = await load_mcp_tools(session)
        yield {t.name: t for t in tools}


def checkpoint_path(s: dict) -> str:
    p = workspace() / s["checkpoint_db"]
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def make_runtime(s: dict, con, alias: str | None = None) -> Runtime:
    c = s["cost"]
    rt = Runtime(ROOT, s, con, Registry(ROOT / "config" / "models.yaml"),
                 Budget(c["max_usd_per_exception"], c["max_usd_per_run"], c["allow_unpriced_models"]))
    if alias:
        rt.alias = alias
    return rt


FLAG_WORDS = {"injection": "injection_detected", "bank-detail": "bank_change_request", "malformed": "bad_source_data",
              "returned errors": "bad_source_data", "limit reached": "step_or_budget_cap", "evidence": "evidence_mismatch"}


def _flags(reasons: list[str]) -> list[str]:
    return sorted({f for r in reasons for w, f in FLAG_WORDS.items() if w in r.lower()})


async def investigate(exception_ids: list[str] | None, alias: str | None = None, run_id: str | None = None) -> list[dict]:
    is_eval = bool(run_id and run_id.startswith("eval-"))
    if not is_eval:
        telemetry.require_enabled("investigate")      # kill switch, enforced here and not only in the UI
    s = load_settings()
    con = db.connect(db_url(s))
    db.ensure_audit(con, ROOT)
    rt = make_runtime(s, con, alias)
    rt.registry.resolve(rt.alias)  # fail fast on unknown/unapproved model
    run_id = run_id or uuid.uuid4().hex[:10]
    if not exception_ids:
        exception_ids = [r["exception_id"] for r in con.query("select exception_id from exceptions where status = 'OPEN' order by 1")]
    out = []
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path(s)) as saver, \
            mcp_tools(s, "read") as tools:
        rt.read_tools = tools
        assert "record_resolution" not in tools, "read-scoped server must not expose the write tool"
        graph = build_graph().compile(checkpointer=saver)
        for ex in exception_ids:
            st = initial_state(ex, run_id)
            cfg = {"configurable": {"thread_id": st["thread_id"], "runtime": rt}, "recursion_limit": 60}
            t0 = time.perf_counter()
            final = await graph.ainvoke(st, cfg)
            if not is_eval:
                _report(con, st["thread_id"], ex, final, int((time.perf_counter() - t0) * 1000))
            out.append({"exception_id": ex, "thread_id": st["thread_id"], "status": final.get("status"),
                        "category": (final.get("proposal") or {}).get("category"),
                        "fix_type": (final.get("proposal") or {}).get("fix_type"),
                        "reasons": final.get("policy_reasons", []), "tool_calls": final.get("tool_calls", 0),
                        "cost_usd": final.get("cost_usd", 0.0), "tools_used": [n for n, _ in final.get("tool_results", [])]})
    con.close()
    return out


def _report(con, thread_id: str, exception_id: str, final: dict, latency_ms: int) -> None:
    """One governance event per investigation, read back from the audit row the graph just wrote."""
    r = con.one("select model_name, input_tokens, output_tokens, cost_usd, tool_calls from agent_runs where thread_id = ?",
                (thread_id,)) or {}
    status = final.get("status")
    telemetry.emit("investigate", status="escalated" if status == "escalated" else "ok" if status else "error",
                    model=r.get("model_name") or "", input_tokens=r.get("input_tokens") or 0,
                    output_tokens=r.get("output_tokens") or 0, cost_usd=float(r.get("cost_usd") or 0),
                    latency_ms=latency_ms, records_in=int(r.get("tool_calls") or 0), records_out=1,
                    flags=_flags(final.get("policy_reasons", [])) + (["escalated"] if status == "escalated" else []),
                    run_id=final.get("run_id", ""), detail={"exception_id": exception_id, "status": status,
                                                            "category": (final.get("proposal") or {}).get("category")})


async def decide(exception_id: str, decision: str, approver: str, note: str = "", edits: dict | None = None) -> dict:
    """Resume a paused thread with a human decision. Only here is the write-scoped server started."""
    s = load_settings()
    con = db.connect(db_url(s))
    row = con.one("select thread_id from agent_runs where exception_id = ? and status = 'awaiting_approval' "
                  "and run_id not like 'eval-%' order by started_at desc", (exception_id,))
    if not row:
        raise LookupError(f"No proposal awaiting approval for {exception_id}")
    telemetry.require_enabled("approve" if decision == "approve" else "reject")
    key = P.signing_key(ROOT, os.getenv(s["approval"]["signing_key_env"]))
    rt = make_runtime(s, con)
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path(s)) as saver, \
            mcp_tools(s, "read,write", key) as tools:
        rt.read_tools = {k: v for k, v in tools.items() if k != "record_resolution"}
        rt.write_tool = tools["record_resolution"]
        graph = build_graph().compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": row["thread_id"], "runtime": rt, "signing_key": key}}
        final = await graph.ainvoke(Command(resume={"decision": decision, "approver": approver, "note": note,
                                                    "edits": edits or {}}), cfg)
    ok = final.get("status") in ("resolved", "rejected")
    telemetry.emit("approve" if decision == "approve" else "reject", actor=approver, actor_type="named",
                    status="ok" if ok else "error", records_in=1, records_out=1 if final.get("status") == "resolved" else 0,
                    flags=(["edited_by_human"] if edits else []) + ([] if ok else ["write_failed"]),
                    detail={"exception_id": exception_id, "status": final.get("status")})
    con.close()
    return {"exception_id": exception_id, "status": final.get("status"), "write_result": final.get("write_result")}
