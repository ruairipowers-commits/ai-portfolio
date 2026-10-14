"""Each app has its own sender so its mail can be filtered on its own."""
import importlib

import pytest

M = importlib.import_module('crash_course.mailer')
ALL = ("COURSE_MAIL_FROM", "MAIL_FROM", "SMTP_FROM", "SMTP_USER")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ALL:
        monkeypatch.delenv(k, raising=False)


def test_own_sender_wins(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "Another app <shared@example.com>")
    monkeypatch.setenv("COURSE_MAIL_FROM", "Crash course <mine@example.com>")
    assert M.mail_from() == "Crash course <mine@example.com>"


def test_shared_address_under_this_apps_name(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "Another app <shared@example.com>")
    assert M.mail_from() == 'Crash course <shared@example.com>'


def test_empty_own_value_counts_as_unset(monkeypatch):
    # the deploy compose passes every listed variable, so an unset one arrives as an empty string
    monkeypatch.setenv("COURSE_MAIL_FROM", "")
    monkeypatch.setenv("MAIL_FROM", "shared@example.com")
    assert M.mail_from() == 'Crash course <shared@example.com>'


def test_default_when_nothing_set():
    assert M.mail_from() == 'Crash course <courses@example.com>'


def test_resend_uses_sender(monkeypatch):
    sent = {}

    class R:
        status_code = 200

    def fake_post(url, json, timeout, headers):
        sent.update(json)
        return R()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("RESEND_API_KEY", "test")
    monkeypatch.setenv("MAIL_FROM", "Daily puzzle <puzzle@example.com>")
    monkeypatch.setenv("COURSE_MAIL_FROM", "Crash course <courses@example.com>")
    assert M._resend("learner@example.com", "Hi", "Body") == "sent"
    assert sent["from"] == "Crash course <courses@example.com>"
