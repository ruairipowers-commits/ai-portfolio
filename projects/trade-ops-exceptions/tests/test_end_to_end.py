"""End-to-end tests against the real TypeScript MCP server (built with `tradeops build-server`).

Each test runs in a throwaway copy of the project so it never touches your warehouse/.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-server" / "dist" / "index.js"
pytestmark = pytest.mark.skipif(not SERVER.exists(), reason="MCP server not built (tradeops build-server)")


@pytest.fixture(scope="module")
def wd(tmp_path_factory):
    d = tmp_path_factory.mktemp("tradeops")
    for sub in ("config", "prompts", "evals", "schema"):
        shutil.copytree(ROOT / sub, d / sub)
    (d / "mcp-server").mkdir()
    for sub in ("dist", "node_modules"):
        os.symlink(ROOT / "mcp-server" / sub, d / "mcp-server" / sub)
    r = run(d, "data")
    assert r.returncode == 0, r.stderr
    return d


def env(d):
    return {**os.environ, "TRADEOPS_ROOT": str(d), "PYTHONPATH": str(ROOT / "src")}


def run(d, *args):
    return subprocess.run([sys.executable, "-m", "tradeops", *args], cwd=d, env=env(d), capture_output=True, text=True, timeout=300)


def py(d, code):
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=d, env=env(d),
                          capture_output=True, text=True, timeout=300)


def sql(d, q):
    import sqlite3

    return sqlite3.connect(d / "warehouse" / "tradeops.sqlite").execute(q).fetchall()


def test_investigate_all_writes_nothing(wd):
    r = run(wd, "investigate")
    assert r.returncode == 0, r.stderr
    assert "'awaiting_approval': 36" in r.stdout and "'escalated': 4" in r.stdout
    assert sql(wd, "select count(*) from resolutions")[0][0] == 0          # NFR-2
    assert sql(wd, "select count(*) from outbox")[0][0] == 0


def test_read_scope_has_no_write_tool(wd):
    r = py(wd, """
        import asyncio
        from tradeops.runner import mcp_tools, load_settings
        async def main():
            async with mcp_tools(load_settings(), "read") as t: print(sorted(t))
        asyncio.run(main())""")
    assert r.returncode == 0, r.stderr
    assert "record_resolution" not in r.stdout and "get_trade" in r.stdout


def test_write_tool_refuses_forged_token(wd):
    r = py(wd, """
        import asyncio, json
        from tradeops.runner import mcp_tools, load_settings
        from tradeops import policy as P
        async def main():
            async with mcp_tools(load_settings(), "read,write", "real-key") as t:
                w = t["record_resolution"]
                exp = P.expiry(5)
                f = P.approval_fields("EX-0005", "SETTLE_DATE_MISMATCH", "AMEND_INTERNAL", "x", None, "mallory", "id-12345678", exp)
                args = dict(exception_id="EX-0005", category="SETTLE_DATE_MISMATCH", fix_type="AMEND_INTERNAL", fix_details="x",
                            email_recipient="", email_subject="", email_body="", approver="mallory", approval_id="id-12345678",
                            expires_at=exp, approval_token=P.mint_token("guessed-key", f))
                try: print("RESULT", await w.ainvoke(args))
                except Exception as e: print("RESULT", e)
        asyncio.run(main())""")
    assert "write refused" in r.stdout, r.stdout + r.stderr
    assert sql(wd, "select count(*) from resolutions")[0][0] == 0


def test_approve_writes_exactly_once_and_queues_email(wd):
    r = run(wd, "approve", "EX-0002", "--approver", "rpowers", "--note", "ok")
    assert r.returncode == 0 and "'recorded': True" in r.stdout, r.stdout + r.stderr
    assert sql(wd, "select approved_by from resolutions where exception_id='EX-0002'") == [("rpowers",)]
    assert sql(wd, "select count(*) from outbox where exception_id='EX-0002' and sent=0")[0][0] == 1
    again = run(wd, "approve", "EX-0002", "--approver", "rpowers")
    assert again.returncode != 0                                           # no longer awaiting approval


def test_reject_and_escalated_cannot_be_approved(wd):
    assert "'rejected'" in run(wd, "reject", "EX-0001", "--approver", "rpowers", "--note", "no").stdout
    r = run(wd, "approve", "EX-0037", "--approver", "rpowers")               # escalated injection case
    assert r.returncode != 0 and "No proposal awaiting approval" in r.stderr
    assert sql(wd, "select count(*) from resolutions where exception_id in ('EX-0001','EX-0037')")[0][0] == 0


def test_eval_gate_passes(wd):
    r = run(wd, "eval")
    assert r.returncode == 0 and "EVAL GATE: PASS" in r.stdout, r.stdout + r.stderr
