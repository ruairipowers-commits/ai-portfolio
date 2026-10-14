from crash_course import mailer


def test_course_mail_from_wins_over_shared(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "Daily puzzle <puzzle@example.com>")
    monkeypatch.setenv("COURSE_MAIL_FROM", "Crash course <courses@example.com>")
    assert mailer.sender() == "Crash course <courses@example.com>"


def test_falls_back_to_shared_mail_from(monkeypatch):
    monkeypatch.delenv("COURSE_MAIL_FROM", raising=False)
    monkeypatch.setenv("MAIL_FROM", "Portfolio <hello@example.com>")
    assert mailer.sender() == "Portfolio <hello@example.com>"


def test_empty_course_value_falls_back(monkeypatch):
    # the deploy compose passes every listed variable, so an unset one arrives as an empty string
    monkeypatch.setenv("COURSE_MAIL_FROM", "")
    monkeypatch.setenv("MAIL_FROM", "Portfolio <hello@example.com>")
    assert mailer.sender() == "Portfolio <hello@example.com>"


def test_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("COURSE_MAIL_FROM", raising=False)
    monkeypatch.delenv("MAIL_FROM", raising=False)
    assert mailer.sender() == "Crash course <courses@example.com>"


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
    assert mailer._resend("learner@example.com", "Hi", "Body") == "sent"
    assert sent["from"] == "Crash course <courses@example.com>"
