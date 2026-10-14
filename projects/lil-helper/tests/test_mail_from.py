"""Each app has its own sender so its mail can be filtered on its own."""
import importlib

import pytest

M = importlib.import_module('lilhelper.outputs')
ALL = ("HELPER_MAIL_FROM", "MAIL_FROM", "SMTP_FROM", "SMTP_USER")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ALL:
        monkeypatch.delenv(k, raising=False)


def test_own_sender_wins(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "Another app <shared@example.com>")
    monkeypatch.setenv("HELPER_MAIL_FROM", "Lil'Helper <mine@example.com>")
    assert M.mail_from() == "Lil'Helper <mine@example.com>"


def test_shared_address_under_this_apps_name(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "Another app <shared@example.com>")
    assert M.mail_from() == "Lil'Helper <shared@example.com>"


def test_empty_own_value_counts_as_unset(monkeypatch):
    # the deploy compose passes every listed variable, so an unset one arrives as an empty string
    monkeypatch.setenv("HELPER_MAIL_FROM", "")
    monkeypatch.setenv("MAIL_FROM", "shared@example.com")
    assert M.mail_from() == "Lil'Helper <shared@example.com>"


def test_default_when_nothing_set():
    assert M.mail_from() == "Lil'Helper <helper@example.com>"
