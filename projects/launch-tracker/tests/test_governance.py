"""Governance client: telemetry events and the kill switch (against a stand-in console)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from launchtracker import telemetry


@pytest.fixture()
def console(monkeypatch):
    """Minimal stand-in for the governance console: one status endpoint + event ingest."""
    state = {"enabled": True, "events": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"enabled": state["enabled"], "reason": "test switch", "changed_by": "cro"}).encode()
            self.send_response(200), self.send_header("Content-Type", "application/json"), self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            state["events"] += json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["auth"] = self.headers.get("Authorization")
            self.send_response(202), self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GOVERNANCE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("GOVERNANCE_INGEST_TOKEN", "t0ken")
    telemetry._state_cache = (0.0, None)
    yield state
    srv.shutdown()
    telemetry._state_cache = (0.0, None)


def test_emit_writes_spool_without_console(governance_spool):
    telemetry.set_actor("alice", "named")
    ev = telemetry.emit("triage", model="mock-local", input_tokens=100, cost_usd=0.001, flags=["escalated"])
    line = json.loads(governance_spool.read_text().splitlines()[0])
    assert line["event_id"] == ev["event_id"] and line["workflow"] == "launch-tracker"
    assert line["actor"] == "alice" and line["flags"] == ["escalated"] and line["cost_usd"] == 0.001


def test_disabled_telemetry(monkeypatch, governance_spool):
    monkeypatch.setenv("GOVERNANCE_TELEMETRY", "off")
    assert telemetry.emit("visit") is None and not governance_spool.exists()


def test_events_post_to_console_with_token(console):
    telemetry.emit("visit")
    telemetry.flush()
    assert console["events"][0]["event_type"] == "visit" and console["auth"] == "Bearer t0ken"


def test_kill_switch_blocks_and_records(console):
    console["enabled"] = False
    with pytest.raises(telemetry.WorkflowDisabled, match="test switch"):
        telemetry.require_enabled("triage")
    telemetry.flush()
    assert console["events"][-1]["status"] == "blocked" and "kill_switch" in console["events"][-1]["flags"]


def test_unreachable_console_fails_open_by_default_and_closed_on_request(monkeypatch):
    monkeypatch.setenv("GOVERNANCE_URL", "http://127.0.0.1:9")   # nothing listens on the discard port
    telemetry._state_cache = (0.0, None)
    assert telemetry.status().enabled and telemetry.status().source == "unreachable"
    monkeypatch.setenv("GOVERNANCE_FAIL_CLOSED", "1")
    telemetry._state_cache = (0.0, None)
    assert not telemetry.status().enabled
    telemetry._state_cache = (0.0, None)
