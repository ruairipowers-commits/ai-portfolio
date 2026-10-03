import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "search_index.json"
SITE = "https://example.github.io/ai-portfolio"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    for k in ("OLLAMA_URL", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "GOVERNANCE_URL", "CF_API_TOKEN",
              "GITHUB_TRAFFIC_TOKEN", "PORTFOLIO_DEMO", "ASSISTANT_ADMIN_TOKEN", "GOVERNANCE_ADMIN_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOVERNANCE_TELEMETRY", "off")
    monkeypatch.setenv("PORTFOLIO_SITE_URL", SITE)
    monkeypatch.setenv("SITE_INDEX", str(FIX))
    monkeypatch.setenv("SITE_ASSISTANT_DB", str(tmp_path / "a.sqlite"))


@pytest.fixture()
def store(tmp_path):
    from siteassistant import index
    from siteassistant.store import Store

    s = Store(str(tmp_path / "a.sqlite"))
    index.refresh(s, str(FIX), SITE)
    return s


@pytest.fixture()
def client(store):
    from fastapi.testclient import TestClient

    from siteassistant import app as A

    return TestClient(A.create_app(store, background=False))


@pytest.fixture()
def fake_ollama(monkeypatch):
    """A stand-in Ollama: /api/tags lists the model, /api/chat streams a cited answer and records what it was sent."""
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"models": [{"name": "llama3.1:8b"}]}).encode()
            self.send_response(200), self.send_header("Content-Type", "application/json"), self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200), self.send_header("Content-Type", "application/x-ndjson"), self.end_headers()
            for part in ["The console ", "switches the workflow off ", "and emails the list [2]."]:
                self.wfile.write((json.dumps({"message": {"content": part}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"done": True, "prompt_eval_count": 420, "eval_count": 18}) + "\n").encode())

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OLLAMA_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    yield seen
    srv.shutdown()
