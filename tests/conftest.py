"""Shared fixtures. All tests are hermetic: no network, no real Google/HF."""

import sys
import os

import pytest

# Make the package importable when running from a source checkout.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from youtube_auto_pub.config import YouTubeConfig  # noqa: E402

ENV_VARS = [
    "HF_TOKEN", "HF_REPO_ID", "HF_YT_CRED_REPO_ID", "ENCRYPT_KEY",
    "NTFY_TOPIC", "NTFY_REPLY_TOPIC", "NTFY_SERVER", "NTFY_TOKEN",
    "GOOGLE_EMAIL", "GOOGLE_APP_PASSWORD", "NOTIFY_SMTP_USER",
    "NOTIFY_SMTP_PASSWORD", "NOTIFY_EMAIL_TO", "NOTIFY_DEDUPE_SECONDS",
    "AUTH_CODE_WAIT_SECONDS", "AUTH_CODE_POLL_SECONDS",
    "AUTH_RESPONSE_FILENAME", "UPLOAD_MAX_RETRIES",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts with none of the package's env vars set."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def config(tmp_path):
    """A config rooted in a temp dir with explicit (non-env) credentials."""
    return YouTubeConfig(
        encrypt_path=str(tmp_path / "encrypt"),
        authorization_code_path=str(tmp_path / "code.txt"),
        hf_repo_id="user/tokens",
        hf_token="hf_test",
        encryption_key=b"test-key",
    )


class FakeNotifier:
    """Records notify() calls instead of sending anything."""

    def __init__(self):
        self.calls = []

    def notify(self, title, message, priority="default", dedupe_key=None):
        self.calls.append({"title": title, "message": message,
                           "priority": priority, "dedupe_key": dedupe_key})
        return True

    def titles(self):
        return [c["title"] for c in self.calls]


@pytest.fixture
def notifier():
    return FakeNotifier()
