import os

import pytest

os.environ["GOVERNANCE_TELEMETRY"] = "off"
for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "EDITORIAL_REQUIRE_SECRETS",
          "EDITORIAL_CLASSIFIER_MODEL", "EDITORIAL_QUEUE_SIZE"):
    os.environ.pop(k, None)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITORIAL_DATA", str(tmp_path))
    from editorial.store import Store
    return Store(tmp_path / "t.sqlite")


@pytest.fixture()
def scouted(store):
    from editorial import scout
    from editorial.config import ROOT
    summary = scout.run(store, scout.fixture_getter(), corpus=str(ROOT / "fixtures" / "corpus.json"),
                        now=scout.FIXTURE_NOW)
    return store, summary
