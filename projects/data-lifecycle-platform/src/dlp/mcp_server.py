"""Read-only MCP server: the catalog, graph, metrics and context layer as tools other agents can use.

Every tool reads; none writes (SEC-03). The server runs as one buyer firm (DLP_MCP_CUSTOMER), so entitlements apply
exactly as in the app: metrics and answers only cover data that firm may send to an AI model. Tool calls are capped
per session (DLP_MCP_MAX_CALLS) and counted in telemetry.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from sqlmodel import select

from . import context, graph, licensing, search, semantic, store, telemetry
from .config import Settings

server = MCPServer("data-lifecycle-platform", instructions=(
    "Read-only tools over a data marketplace: find datasets, describe one, check usage rights, run governed "
    "metrics, and ask questions answered only from data the configured firm is entitled to use with AI."))
_calls = {"n": 0}


def _guard(tool: str) -> tuple[Settings, str]:
    cap = int(os.getenv("DLP_MCP_MAX_CALLS", "50"))
    _calls["n"] += 1
    if _calls["n"] > cap:
        raise RuntimeError(f"Tool-call cap of {cap} reached for this session")
    telemetry.require_enabled(f"mcp:{tool}")
    telemetry.record(f"mcp_{tool}", items=1)
    return Settings.load(), os.getenv("DLP_MCP_CUSTOMER", "cust-kestrel")


@server.tool()
def find_data(need: str) -> dict:
    """Search the catalog and marketplaces for datasets that fit a plain-English data need."""
    s, cid = _guard("find_data")
    r = search.run(s, need, cid, actor=f"mcp:{cid}")
    return {"plan": r["plan"], "results": r["results"][:8], "discoveries": r["discoveries"]}


@server.tool()
def describe_dataset(dataset_id: str) -> dict:
    """Vendor, category, licence, fields and the concepts they mean, sectors covered, metrics and substitutes."""
    s, _ = _guard("describe_dataset")
    return graph.dataset_neighbourhood(s, dataset_id)


@server.tool()
def check_rights(dataset_id: str, use: str = "v:AIProcessing") -> dict:
    """Usage-rights verdict for the configured firm: PERMITTED, CONDITIONAL, LEGAL_REVIEW or BLOCKED, with reasons."""
    s, cid = _guard("check_rights")
    with store.session(s) as ss:
        return licensing.assess(ss, s, dataset_id, use, cid).__dict__


@server.tool()
def list_metrics() -> list[dict]:
    """Governed metrics in the semantic layer, with the concept each measures and the dataset it comes from."""
    _guard("list_metrics")
    return [{"name": m.name, "label": m.label, "concept": m.ontology_iri, "dataset": m.dataset_id, "unit": m.unit}
            for m in semantic.metrics().values()]


@server.tool()
def query_metric(metric: str, group_by: str = "", where_symbol: str = "") -> dict:
    """Run one governed metric (optionally grouped, e.g. option_day__gics_sector, or for one symbol)."""
    s, cid = _guard("query_metric")
    m = semantic.metrics().get(metric)
    if m is None:
        return {"status": "NOT_DEFINED", "metric": metric}
    if m.dataset_id != "platform":
        with store.session(s) as ss:
            v = licensing.assess(ss, s, m.dataset_id, "v:AIProcessing", cid)
        if not v.allowed:
            return {"status": "NOT_ENTITLED", "reason": "; ".join(v.reasons)}
    where = {"option_day__symbol": where_symbol} if where_symbol else None
    r = semantic.query(s, metric, [group_by] if group_by else None, where, limit=50)
    return {"status": "OK", "rows": r.rows, "query_id": r.query_id}


@server.tool()
def ask(question: str) -> dict:
    """Answer a question from the context layer: entitled data only, every number from a governed metric."""
    s, cid = _guard("ask")
    r = context.answer(s, question, cid, actor=f"mcp:{cid}")
    return {"status": r.status, "answer": r.answer, "citations": r.citations}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
