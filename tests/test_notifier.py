import smtplib

import pytest

from youtube_auto_pub import notifier as notifier_mod
from youtube_auto_pub.notifier import Notifier


class FakeResponse:
    def raise_for_status(self):
        pass


@pytest.fixture
def fresh_notifier(tmp_path):
    return Notifier(state_path=str(tmp_path / "state.json"))


def test_no_channels_returns_false(fresh_notifier, capsys):
    assert fresh_notifier.notify("Title", "Body") is False
    out = capsys.readouterr().out
    assert "Title" in out and "Body" in out  # always mirrored to stdout


def test_ntfy_channel(fresh_notifier, monkeypatch):
    sent = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        sent.update(url=url, data=data, headers=headers)
        return FakeResponse()

    monkeypatch.setenv("NTFY_TOPIC", "my-topic")
    monkeypatch.setattr(notifier_mod.requests, "post", fake_post)

    assert fresh_notifier.notify("Alert", "Something", priority="urgent") is True
    assert sent["url"] == "https://ntfy.sh/my-topic"
    assert sent["data"] == b"Something"
    assert sent["headers"]["Title"] == "Alert"
    assert sent["headers"]["Priority"] == "urgent"


def test_ntfy_custom_server_and_token(fresh_notifier, monkeypatch):
    sent = {}
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("NTFY_SERVER", "https://my.server/")
    monkeypatch.setenv("NTFY_TOKEN", "tk_abc")
    monkeypatch.setattr(notifier_mod.requests, "post",
                        lambda url, **kw: sent.update(url=url, **kw) or FakeResponse())

    fresh_notifier.notify("A", "B")
    assert sent["url"] == "https://my.server/t"
    assert sent["headers"]["Authorization"] == "Bearer tk_abc"


def test_email_channel(fresh_notifier, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.update(host=host, port=port)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, user, password):
            sent.update(user=user, password=password)

        def send_message(self, msg):
            sent.update(subject=msg["Subject"], to=msg["To"])

    monkeypatch.setenv("GOOGLE_EMAIL", "me@gmail.com")
    monkeypatch.setenv("GOOGLE_APP_PASSWORD", "app-pass")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    assert fresh_notifier.notify("Subject line", "Body") is True
    assert sent == {
        "host": "smtp.gmail.com", "port": 465,
        "user": "me@gmail.com", "password": "app-pass",
        "subject": "Subject line", "to": "me@gmail.com",  # defaults to sender
    }


def test_dedupe_suppresses_repeats(fresh_notifier, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setattr(notifier_mod.requests, "post", lambda *a, **k: FakeResponse())

    assert fresh_notifier.notify("A", "B", dedupe_key="k") is True
    assert fresh_notifier.notify("A", "B", dedupe_key="k") is False  # suppressed
    assert fresh_notifier.notify("A", "B", dedupe_key="other") is True
    assert fresh_notifier.notify("A", "B") is True  # no key -> never suppressed


def test_dedupe_window_configurable(fresh_notifier, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setattr(notifier_mod.requests, "post", lambda *a, **k: FakeResponse())

    fresh_notifier.notify("A", "B", dedupe_key="k")
    monkeypatch.setenv("NOTIFY_DEDUPE_SECONDS", "0")
    assert fresh_notifier.notify("A", "B", dedupe_key="k") is True


def test_failed_channel_does_not_mark_dedupe(fresh_notifier, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(notifier_mod.requests, "post", boom)
    assert fresh_notifier.notify("A", "B", dedupe_key="k") is False

    # Channel recovers: the same key must go through (it was never delivered).
    monkeypatch.setattr(notifier_mod.requests, "post", lambda *a, **k: FakeResponse())
    assert fresh_notifier.notify("A", "B", dedupe_key="k") is True
