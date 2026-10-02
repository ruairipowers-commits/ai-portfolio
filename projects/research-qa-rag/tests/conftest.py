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
    monkeypatch.setenv("GOVERNANCE_DB", str(tmp_path / "governance.sqlite"))
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
