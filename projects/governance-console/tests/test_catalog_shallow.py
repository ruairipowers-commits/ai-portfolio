"""The demo image installs the console at /app, which has only one parent: the catalog must fall back to the bundle."""
from pathlib import Path

from fastapi.testclient import TestClient

from govconsole import catalog


def test_shallow_install_uses_bundled_catalog(monkeypatch, tmp_path):
    monkeypatch.delenv("PORTFOLIO_ROOT", raising=False)
    monkeypatch.setattr(catalog, "PKG_ROOT", Path("/app"))   # as in Dockerfile.space
    assert catalog.find_portfolio_root() is None
    assert catalog.load()["workflows"], "bundled catalog should list the workflows"
