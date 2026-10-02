"""Every test runs against a throwaway copy of the project with its own corpus, index and governance store."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def project(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "scripts", "docs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RQA_ROOT", str(tmp_path))
    monkeypatch.delenv("PORTFOLIO_DEMO", raising=False)
    for m in [m for m in sys.modules if m.startswith("research_qa")]:
        del sys.modules[m]
    return tmp_path


@pytest.fixture()
def m(project):
    """Freshly imported modules bound to this test's project copy (module-level ROOT is resolved at import)."""
    import importlib
    from types import SimpleNamespace

    names = ["answer", "cli", "evals", "guardrails", "ingest", "llm", "retrieve", "store", "telemetry", "api"]
    return SimpleNamespace(**{n: importlib.import_module(f"research_qa.{n}") for n in names})


@pytest.fixture()
def built(project):
    """Corpus generated and indexed."""
    from research_qa.cli import reset_corpus
    from research_qa.ingest import ingest
    from research_qa.store import Settings

    s = Settings.load()
    reset_corpus(s)
    ingest(s, full=True)
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
