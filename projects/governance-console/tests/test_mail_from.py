"""Each app has its own sender so its mail can be filtered on its own."""
import importlib

import pytest

M = importlib.import_module('govconsole.notify')
ALL = ("GOVERNANCE_MAIL_FROM", "MAIL_FROM", "SMTP_FROM", "SMTP_USER")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ALL:
        monkeypatch.delenv(k, raising=False)


def test_own_sender_wins(monkeypatch):
    monkeypatch.setenv("SMTP_FROM", "Another app <shared@example.com>")
    monkeypatch.setenv("GOVERNANCE_MAIL_FROM", "Governance console <mine@example.com>")
    assert M.mail_from() == "Governance console <mine@example.com>"


def test_shared_address_under_this_apps_name(monkeypatch):
    monkeypatch.setenv("SMTP_FROM", "Another app <shared@example.com>")
    assert M.mail_from() == 'Governance console <shared@example.com>'


def test_empty_own_value_counts_as_unset(monkeypatch):
    # the deploy compose passes every listed variable, so an unset one arrives as an empty string
    monkeypatch.setenv("GOVERNANCE_MAIL_FROM", "")
    monkeypatch.setenv("SMTP_FROM", "shared@example.com")
    assert M.mail_from() == 'Governance console <shared@example.com>'


def test_default_when_nothing_set():
    assert M.mail_from() == 'governance-console@localhost'
