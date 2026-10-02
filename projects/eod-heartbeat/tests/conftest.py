"""Tests share one embedded Postgres server (started once, stopped at exit) but each gets its own database and
its own copy of the project files."""
import importlib
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def pg_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("pg")


@pytest.fixture()
def project(tmp_path, monkeypatch, pg_dir):
    for d in ("config", "prompts", "evals", "scripts", "docs", "kb", "dbt"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("target", "logs"))
    (tmp_path / "warehouse").symlink_to(pg_dir, target_is_directory=True)   # one server for the whole session
    cfg = tmp_path / "config" / "settings.yaml"
    cfg.write_text(cfg.read_text().replace("database_name: eod", f"database_name: eod_t{uuid.uuid4().hex[:8]}"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EOD_ROOT", str(tmp_path))
    monkeypatch.setenv("EOD_PG_CLEANUP", "stop")
    monkeypatch.delenv("PORTFOLIO_DEMO", raising=False)
    monkeypatch.delenv("EOD_DATABASE_URL", raising=False)
    for m in [m for m in sys.modules if m.startswith("eod_heartbeat")]:
        del sys.modules[m]
    return tmp_path


@pytest.fixture()
def m(project):
    names = ["cli", "evals", "explain", "kb", "llm", "loader", "retention", "store", "telemetry", "transform"]
    return SimpleNamespace(**{n: importlib.import_module(f"eod_heartbeat.{n}") for n in names})


@pytest.fixture()
def ready(m):
    s = m.store.Settings.load()
    m.cli.reset_all(s)
    return s


# ---------------------------------------------------------------- governance console stand-in
@pytest.fixture(autouse=True)
def governance_spool(tmp_path, monkeypatch):
    """Telemetry goes to a per-test spool file, never to ~/.ai-portfolio or a real console."""
    spool = tmp_path / "governance-events.jsonl"
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(spool))
    monkeypatch.delenv("GOVERNANCE_URL", raising=False)
    monkeypatch.delenv("GOVERNANCE_TELEMETRY", raising=False)
    return spool


def read_spool(path) -> list[dict]:
    import json

    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture()
def console(monkeypatch):
    """Minimal governance console: kill-switch status endpoint + event ingest, on a free local port."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    state = {"enabled": True, "reason": "", "changed_by": "", "events": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({k: state[k] for k in ("enabled", "reason", "changed_by")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            state["events"] += json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(202)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GOVERNANCE_URL", f"http://127.0.0.1:{srv.server_port}")
    yield state
    srv.shutdown()
