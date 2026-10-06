"""Offline end to end: `dlp all` (build + eval gate) and a few CLI commands, in a scratch workspace."""
import json

from dlp import cli


def test_dlp_all_passes_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DLP_WORKSPACE", str(tmp_path))
    assert cli.main(["all"]) == 0
    out = capsys.readouterr().out
    assert "SHACL conforms" in out and "eval: PASS" in out
    assert cli.main(["ask", "Put call ratio for Financials", "--customer", "cust-kestrel"]) == 0
    assert '"status": "ANSWERED"' in capsys.readouterr().out
    assert cli.main(["ontology", "check"]) == 0
