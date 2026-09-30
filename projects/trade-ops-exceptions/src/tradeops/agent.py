"""The LangGraph agent: investigate (tool loop) -> policy -> human approval (interrupt) -> gated write.

    START -> agent <-> tools            (read-only MCP tools, step + budget caps, result screening)
             agent -> policy            (schema, evidence check, deterministic rules)
             policy -> human_review     (interrupt: waits for a named analyst)   | END if escalated
             human_review -> execute    (mint approval token; write-scoped MCP tool) -> END

The write tool never exists in the model's tool list, and the write-scoped MCP server process is only
started when a human decision resumes the graph (SEC-03, HITL-02).
"""
from __future__ import annotations

import json
import operator
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import ValidationError

from . import policy as P
from .llm import Budget, BudgetExceeded, Registry, build_chat_model, estimate_tokens


class AgentState(TypedDict, total=False):
    exception_id: str
    run_id: str
    thread_id: str
    messages: Annotated[list, add_messages]
    tool_calls: int
    llm_turns: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    model_name: str
    flags: Annotated[list[str], operator.add]
    tool_errors: int
    tool_results: Annotated[list[tuple[str, str]], operator.add]
    hit_limits: bool
    proposal: dict | None
    status: str
    policy_reasons: list[str]
    evidence_errors: list[str]
    decision: dict | None
    write_result: dict | None


def _submit_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kw: "received", name="submit_proposal", args_schema=P.Proposal,
        description="Submit the investigation result for human approval. Call exactly once, last.")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(getattr(b, "text", b)) for b in result)
    if isinstance(result, tuple):
        return _text(result[0])
    return json.dumps(result, default=str)


class Runtime:
    """Things nodes need that must not be checkpointed: config, DB, tools, budget."""

    def __init__(self, root: Path, settings: dict, con, registry: Registry, budget: Budget):
        self.root, self.s, self.con, self.registry, self.budget = root, settings, con, registry, budget
        self.read_tools: dict[str, Any] = {}
        self.write_tool = None
        self.alias = settings["llm"]["primary_alias"]
        tmpl = (root / settings["llm"]["prompt_file"]).read_text()
        self.system_prompt = tmpl.replace("{max_tool_calls}", str(settings["agent"]["max_tool_calls"]))
        self.prompt_sha = P._sha(tmpl)[:16]

    def log_step(self, thread_id, _step_hint, kind, name=None, args=None, result=None, tin=0, tout=0, cost=0.0, flag=None):
        step = self.con.one("select count(*) as n from agent_steps where thread_id = ?", (thread_id,))["n"] + 1
        self.con.execute("insert into agent_steps values (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (thread_id, step, kind, name, json.dumps(args, default=str) if args is not None else None,
                          P._sha(result)[:16] if result else None, (result or "")[:300], tin, tout, cost, flag, now()))
        self.con.commit()


# ------------------------------------------------------------------ nodes
async def agent_node(state: AgentState, config) -> dict:
    rt: Runtime = config["configurable"]["runtime"]
    agent_cfg, llm_cfg = rt.s["agent"], rt.s["llm"]
    if state.get("llm_turns", 0) >= agent_cfg["max_llm_turns"]:
        return {"hit_limits": True}
    tools = [rt.read_tools[n] for n in agent_cfg["read_tools"] if n in rt.read_tools] + [_submit_tool()]
    msgs = [SystemMessage(rt.system_prompt)] + state["messages"]
    last_err = None
    for alias in (rt.alias, llm_cfg["fallback_alias"]):
        spec = rt.registry.resolve(alias)
        try:
            rt.budget.check(spec, state.get("cost_usd", 0.0), estimate_tokens(msgs), llm_cfg["max_output_tokens"])
        except BudgetExceeded as e:
            rt.log_step(state["thread_id"], _step(state), "budget_blocked", flag=str(e))
            return {"hit_limits": True, "flags": ["budget_exceeded"]}
        try:
            model = build_chat_model(spec, llm_cfg["max_output_tokens"]).bind_tools(tools)
            ai: AIMessage = await model.ainvoke(msgs)
            break
        except Exception as e:  # provider/network error -> try fallback alias (MODEL-05)
            last_err = e
            rt.log_step(state["thread_id"], _step(state), "llm_error", name=spec.name, flag=str(e)[:200])
    else:
        raise RuntimeError(f"All models failed: {last_err}")
    usage = ai.usage_metadata or {}
    tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    cost = spec.cost(tin, tout)
    rt.budget.run_spent += cost
    rt.log_step(state["thread_id"], _step(state), "llm", name=spec.name,
                args=[tc["name"] for tc in ai.tool_calls], tin=tin, tout=tout, cost=cost)
    return {"messages": [ai], "llm_turns": state.get("llm_turns", 0) + 1, "model_name": spec.name,
            "cost_usd": state.get("cost_usd", 0.0) + cost, "input_tokens": state.get("input_tokens", 0) + tin,
            "output_tokens": state.get("output_tokens", 0) + tout}


def _step(state) -> int:
    return state.get("llm_turns", 0) + state.get("tool_calls", 0)


def route_after_agent(state: AgentState) -> str:
    if state.get("hit_limits"):
        return "policy"
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", []) or []
    if any(c["name"] == "submit_proposal" for c in calls) or not calls:
        return "policy"
    return "tools"


async def tools_node(state: AgentState, config) -> dict:
    rt: Runtime = config["configurable"]["runtime"]
    allowed, cap = set(rt.s["agent"]["read_tools"]), rt.s["agent"]["max_tool_calls"]
    n, out, flags, results, errors, hit = state.get("tool_calls", 0), [], [], [], 0, False
    for call in state["messages"][-1].tool_calls:
        name, args = call["name"], call["args"]
        if n >= cap:
            hit = True
            out.append(ToolMessage("Tool-call limit reached. Submit a proposal now.", tool_call_id=call["id"], name=name))
            continue
        n += 1
        if name not in allowed or name not in rt.read_tools:
            flags.append("disallowed_tool")
            text = json.dumps({"error": f"tool '{name}' is not permitted"})
            errors += 1
            rt.log_step(state["thread_id"], _step(state) + n, "tool", name, args, text, flag="disallowed_tool")
            out.append(ToolMessage(text, tool_call_id=call["id"], name=name))
            continue
        try:
            text = _text(await rt.read_tools[name].ainvoke(args))
        except Exception as e:  # MCP isError -> ToolException, bad args, transport errors
            text = json.dumps({"error": str(e)[:500]})
        is_err = '"error"' in text[:20] or text.startswith("Error")
        errors += int(is_err)
        found = P.scan_tool_result(text)
        flags += found
        results.append((name, text))
        rt.log_step(state["thread_id"], _step(state) + n, "tool", name, args, text,
                    flag=",".join(found) or ("tool_error" if is_err else None))
        out.append(ToolMessage(text, tool_call_id=call["id"], name=name))
    return {"messages": out, "tool_calls": n, "flags": flags, "tool_results": results,
            "tool_errors": state.get("tool_errors", 0) + errors, "hit_limits": hit or state.get("hit_limits", False)}


def route_after_tools(state: AgentState) -> str:
    return "agent"


async def policy_node(state: AgentState, config) -> dict:
    rt: Runtime = config["configurable"]["runtime"]
    last = state["messages"][-1] if state.get("messages") else None
    raw = next((c["args"] for c in (getattr(last, "tool_calls", []) or []) if c["name"] == "submit_proposal"), None)
    try:
        proposal = P.Proposal.model_validate(raw) if raw else None
    except ValidationError as e:
        proposal, raw = None, None
        rt.log_step(state["thread_id"], _step(state) + 1, "schema_error", flag=str(e)[:200])
    if proposal is None:
        proposal = P.Proposal(exception_id=state["exception_id"], category="UNKNOWN", fix_type="ESCALATE",
                              root_cause="Agent did not produce a valid proposal within limits.",
                              fix_details="Manual investigation required.", confidence=0.0,
                              evidence=[P.Evidence(tool="none", field="none", value=None)])
        ev_err = []
    else:
        ev_err = P.check_evidence(proposal, state.get("tool_results", []))
    status, reasons = P.apply_policy(proposal, set(state.get("flags", [])), ev_err, bool(state.get("hit_limits")),
                                     state.get("tool_errors", 0), rt.s["policy"])
    if raw is None and "Model escalated" in reasons and len(reasons) == 1:
        reasons = ["No valid proposal produced"]
    rt.con.execute(
        "insert or replace into agent_runs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)" if not rt.con.pg else
        "insert into agent_runs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict (thread_id) do update set status = excluded.status",
        (state["run_id"], state["exception_id"], state["thread_id"], state.get("model_name"), rt.prompt_sha, status,
         proposal.category, proposal.fix_type, _step(state), state.get("tool_calls", 0), state.get("input_tokens", 0),
         state.get("output_tokens", 0), state.get("cost_usd", 0.0),
         json.dumps({"flags": sorted(set(state.get("flags", []))), "reasons": reasons, "evidence_errors": ev_err}),
         proposal.model_dump_json(), now(), now()))
    rt.con.commit()
    return {"proposal": proposal.model_dump(), "status": status, "policy_reasons": reasons, "evidence_errors": ev_err}


def route_after_policy(state: AgentState) -> str:
    return "human_review" if state["status"] == "awaiting_approval" else END


async def human_review_node(state: AgentState, config) -> dict:
    decision = interrupt({"exception_id": state["exception_id"], "proposal": state["proposal"],
                          "policy_reasons": state.get("policy_reasons", [])})
    return {"decision": decision}


async def execute_node(state: AgentState, config) -> dict:
    rt: Runtime = config["configurable"]["runtime"]
    d, p = state["decision"] or {}, state["proposal"]
    approver = d.get("approver", "")
    allowed_approvers = rt.s["approval"]["allowed_approvers"]
    approval_id = uuid.uuid4().hex
    final = {**p, **{k: v for k, v in (d.get("edits") or {}).items() if k in ("fix_type", "fix_details", "email_draft")}}
    edited = final != p
    decision = d.get("decision")
    if decision == "approve" and final["fix_type"] not in rt.s["policy"]["allowed_fixes"].get(final["category"], []):
        decision, d["note"] = "rejected_by_policy", f"edited fix {final['fix_type']} not allowed for {final['category']}"
    if decision == "approve" and allowed_approvers and approver not in allowed_approvers:
        decision, d["note"] = "rejected_by_policy", f"{approver} is not an authorised approver"
    result = None
    if decision == "approve":
        if rt.write_tool is None:
            raise RuntimeError("write tool not available in this process")
        key = P.signing_key(rt.root, config["configurable"].get("signing_key"))
        exp = P.expiry(rt.s["approval"]["token_ttl_minutes"])
        fields = P.approval_fields(p["exception_id"], final["category"], final["fix_type"], final["fix_details"],
                                   final.get("email_draft"), approver, approval_id, exp)
        e = final.get("email_draft") or {"recipient": "", "subject": "", "body": ""}
        args = dict(exception_id=p["exception_id"], category=final["category"], fix_type=final["fix_type"],
                    fix_details=final["fix_details"], email_recipient=e["recipient"], email_subject=e["subject"],
                    email_body=e["body"], approver=approver, approval_id=approval_id, expires_at=exp,
                    approval_token=P.mint_token(key, fields))
        try:
            result = json.loads(_text(await rt.write_tool.ainvoke(args)))
        except Exception as ex:
            result = {"error": str(ex)[:300]}
    rt.con.execute("insert into approvals values (?,?,?,?,?,?,?,?,?,?)",
                   (approval_id, state["thread_id"], p["exception_id"], decision, approver, p["fix_type"],
                    final["fix_type"], edited, d.get("note", ""), now()))
    status = "resolved" if result and result.get("recorded") else ("rejected" if decision != "approve" else "write_failed")
    rt.con.execute("update agent_runs set status = ?, updated_at = ? where thread_id = ?", (status, now(), state["thread_id"]))
    rt.con.commit()
    return {"status": status, "write_result": result}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("policy", policy_node)
    g.add_node("human_review", human_review_node)
    g.add_node("execute", execute_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "policy": "policy"})
    g.add_conditional_edges("tools", lambda s: "policy" if s.get("hit_limits") else "agent",
                            {"agent": "agent", "policy": "policy"})
    g.add_conditional_edges("policy", route_after_policy, {"human_review": "human_review", END: END})
    g.add_edge("human_review", "execute")
    g.add_edge("execute", END)
    return g


def initial_state(exception_id: str, run_id: str) -> AgentState:
    return {"exception_id": exception_id, "run_id": run_id, "thread_id": f"{exception_id}:{run_id}",
            "messages": [HumanMessage(f"Investigate open exception {exception_id} and submit a proposal.")],
            "tool_calls": 0, "llm_turns": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
            "flags": [], "tool_errors": 0, "tool_results": [], "hit_limits": False}
