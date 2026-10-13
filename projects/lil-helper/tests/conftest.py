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


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """A fresh server data folder (accounts + households) and an API client with helpers."""
    import glob
    import os
    import re
    from fastapi.testclient import TestClient
    from lilhelper import api
    data = tmp_path / "data"
    monkeypatch.setenv("HELPER_DATA", str(data))
    monkeypatch.setenv("HELPER_SIGNUP", "invite")
    monkeypatch.setenv("HELPER_SIGNUP_CODES", "family2026")
    api._hits.clear()

    class S:
        client = TestClient(api.app)

        def link(self, tag="signin"):
            files = sorted(glob.glob(str(data / "outbox" / f"{tag}-*.html")), key=os.path.getmtime)
            text = open(files[-1]).read()
            tok = re.search(r"token=([^&'\"<]+)", text).group(1)
            inv = re.search(r"invite=([^'\"<&]+)", text)
            return tok, inv.group(1) if inv else None

        def signin(self, email, invite_tag=None):
            if invite_tag:
                tok, inv = self.link(invite_tag)
            else:
                self.client.post("/api/auth/request", json={"email": email})
                tok, inv = self.link()
            r = self.client.post("/api/auth/verify", json={"token": tok, "invite": inv}).json()
            return {"Authorization": f"Bearer {r['session']}"}, r

        def household(self, email="ruairi@example.com", name="Ruairi", hname="Powers house"):
            H, _ = self.signin(email)
            r = self.client.post("/api/households", headers=H, json={"name": hname, "your_name": name,
                                                                      "signup_code": "family2026"}).json()
            return {"Authorization": f"Bearer {r['session']}"}, r["household"]

    return S()
