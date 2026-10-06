"""The REST API (tenant tokens, operator-only writes) and the read-only MCP server."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from dlp import api


@pytest.fixture()
def client(built):
    return TestClient(api.app)


def h(who):
    return {"Authorization": f"Bearer {api.issue_token(who)}"}


def test_tokens_and_roles(client):
    assert client.get("/vendors").status_code == 401
    assert client.get("/vendors", headers={"Authorization": "Bearer cust-kestrel.forged"}).status_code == 401
    assert client.get("/vendors", headers=h("cust-kestrel")).status_code == 200
    assert client.put("/vendors/v-northlight", json={"name": "x"}, headers=h("cust-kestrel")).status_code == 403
    assert client.get("/approvals", headers=h("cust-kestrel")).status_code == 403


def test_a_firm_sees_only_its_own_contracts(client):
    mine = client.get("/me/contracts", headers=h("cust-kestrel")).json()
    assert {c["customer_id"] for c in mine} == {"cust-kestrel"} and len(mine) == 1
    assert client.get("/me/contracts", headers=h("operator")).status_code == 403


def test_download_is_entitlement_checked(client):
    assert client.get("/me/datasets/ds-options-iv/download", headers=h("cust-alder")).status_code == 403
    r = client.get("/me/datasets/ds-options-iv/download", headers=h("cust-kestrel"))
    assert r.status_code == 200 and r.content[:4] == b"PAR1"


def test_ask_via_api_is_scoped_to_the_token(client):
    r = client.post("/me/ask", json={"question": "What is the implied vol for JPM?"}, headers=h("cust-alder")).json()
    assert r["status"] == "NOT_ENTITLED"


def test_licence_tag_cannot_be_changed_through_a_dataset_update(client):
    client.put("/datasets/ds-constituents", json={"licence": "apache-2.0", "description": "x"}, headers=h("operator"))
    assert client.get("/datasets/ds-constituents", headers=h("operator")).json()["licence"] == "none"


def test_mcp_tools_are_read_only_and_capped(built, monkeypatch):
    from dlp import mcp_server

    tools = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert tools == {"find_data", "describe_dataset", "check_rights", "list_metrics", "query_metric", "ask"}
    monkeypatch.setenv("DLP_MCP_CUSTOMER", "cust-alder")
    r = asyncio.run(mcp_server.server.call_tool("query_metric", {"metric": "atm_iv"}))
    body = r.structured_content or json.loads(r.content[0].text)
    assert body["status"] == "NOT_ENTITLED"
    monkeypatch.setenv("DLP_MCP_MAX_CALLS", "0")
    with pytest.raises(Exception, match="list_metrics"):
        asyncio.run(mcp_server.server.call_tool("list_metrics", {}))
