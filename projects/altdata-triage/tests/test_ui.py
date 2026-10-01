"""Streamlit app tests (headless, via streamlit.testing). Each test runs in a throwaway project copy."""
import os
import shutil
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "altdata_triage" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "dbt", "scripts"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("target", "logs", "security_master.csv"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALTDATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DUCKDB_PATH", "warehouse/ui.duckdb")
    # modules cache ROOT at import time; drop them so the app binds to tmp_path
    import sys
    for m in [m for m in sys.modules if m.startswith("altdata_triage")]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=300)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def summary(at):
    return at.dataframe[1].value.set_index("vendor")


def test_default_run(app):
    at = app.run()
    assert not at.exception
    at = click(at, "Run triage")
    assert not at.exception, at.exception
    s = summary(at)
    assert s.loc["WebCrawl Labs", "final"].endswith("ESCALATE")
    assert s.loc["CardPulse", "final"].endswith("PURSUE")


def test_injected_notes_force_escalation(app):
    at = app.run()
    at = click(at, "Insert injection example")       # default target is v01 (CardPulse)
    at = click(at, "Save notes")
    at = click(at, "Run triage")
    s = summary(at)
    assert s.loc["CardPulse", "model_draft"] == "PURSUE"     # mock model is not fooled...
    assert s.loc["CardPulse", "final"].endswith("ESCALATE")  # ...but policy escalates anyway
    assert bool(s.loc["CardPulse", "injection_flag"])


def test_upload_with_future_dates_blocks_ai(app, tmp_path):
    at = app.run()
    csv = b"obs_date,ticker,metric_value\n2026-09-11,AAA,1.0\n2030-01-04,AAA,2.0\n"
    from altdata_triage import pipeline as pl
    res = pl.add_vendor(csv, {"vendor_name": "Future Co", "category": "Test", "pii_present": False,
                              "point_in_time": True, "license_derived_use": True, "delivery": "weekly",
                              "annual_price_usd": 1000}, "Notes.")
    assert res.ok
    at = app.run()
    at = click(at, "Run triage")
    assert any("dbt build failed" in e.value for e in at.error)
    assert len(at.dataframe) >= 1 and not any("model_draft" in d.value.columns for d in at.dataframe)


def test_bad_csv_rejected(app):
    app.run()
    from altdata_triage import pipeline as pl
    assert not pl.add_vendor(b"date,price\n1,2\n", {"vendor_name": "x"}, "").ok
