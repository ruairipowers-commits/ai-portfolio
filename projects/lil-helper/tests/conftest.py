from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def governance_spool(tmp_path, monkeypatch):
    """Telemetry goes to a per-test spool file, never to ~/.ai-portfolio or a real console."""
    spool = tmp_path / "governance-events.jsonl"
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(spool))
    monkeypatch.delenv("GOVERNANCE_URL", raising=False)
    monkeypatch.delenv("GOVERNANCE_TELEMETRY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("INSTACART_API_KEY", raising=False)
    return spool


@pytest.fixture()
def workspace(tmp_path):
    """A throwaway warehouse/output/logs for runs that write (the same mechanism as the demo's per-visitor sandbox)."""
    from lilhelper import demo
    ws = tmp_path / "ws"
    ws.mkdir()
    tok = demo._workspace.set(ws)
    yield ws
    demo._workspace.reset(tok)
