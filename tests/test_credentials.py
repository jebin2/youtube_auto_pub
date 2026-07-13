import json
import os

import pytest
from google.auth.exceptions import RefreshError

from youtube_auto_pub import credentials
from youtube_auto_pub.config import YouTubeConfig


def write_client_secret(path, client_id, kind="installed"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({kind: {"client_id": client_id}}, f)


# ---------------------------------------------------------------- helpers

def test_extract_client_id_installed_and_web(tmp_path):
    installed = tmp_path / "installed.json"
    web = tmp_path / "web.json"
    write_client_secret(str(installed), "id-a", "installed")
    write_client_secret(str(web), "id-b", "web")

    assert credentials.extract_client_id(str(installed)) == "id-a"
    assert credentials.extract_client_id(str(web)) == "id-b"
    assert credentials.extract_client_id(str(tmp_path / "missing.json")) is None


def test_token_matches_client(tmp_path):
    token = tmp_path / "token.json"

    assert credentials.token_matches_client(str(token), "abc") is True  # no token yet

    token.write_text(json.dumps({"client_id": "abc"}))
    assert credentials.token_matches_client(str(token), "abc") is True
    assert credentials.token_matches_client(str(token), "other") is False

    token.write_text(json.dumps({}))  # legacy token without client_id
    assert credentials.token_matches_client(str(token), "abc") is False


# ------------------------------------------------- sync_local_client_secret

def test_first_time_setup_adopts_cwd_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_client_secret("ytcredentials.json", "fresh-id")
    config = YouTubeConfig(encrypt_path=str(tmp_path / "enc"))
    stored = config.client_id_path

    credentials.sync_local_client_secret(config, stored, config.token_file_path)

    assert credentials.extract_client_id(stored) == "fresh-id"


def test_client_rotation_replaces_secret_and_deletes_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = YouTubeConfig(encrypt_path=str(tmp_path / "enc"))
    write_client_secret(config.client_id_path, "old-id")
    with open(config.token_file_path, "w") as f:
        json.dump({"client_id": "old-id"}, f)
    write_client_secret("ytcredentials.json", "new-id")

    credentials.sync_local_client_secret(config, config.client_id_path, config.token_file_path)

    assert credentials.extract_client_id(config.client_id_path) == "new-id"
    assert not os.path.exists(config.token_file_path)  # forced re-auth


def test_same_client_id_leaves_everything_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = YouTubeConfig(encrypt_path=str(tmp_path / "enc"))
    write_client_secret(config.client_id_path, "same-id")
    with open(config.token_file_path, "w") as f:
        json.dump({"client_id": "same-id"}, f)
    write_client_secret("ytcredentials.json", "same-id")

    credentials.sync_local_client_secret(config, config.client_id_path, config.token_file_path)

    assert os.path.exists(config.token_file_path)


def test_mismatched_token_is_deleted_even_without_local_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = YouTubeConfig(encrypt_path=str(tmp_path / "enc"))
    write_client_secret(config.client_id_path, "id-a")
    with open(config.token_file_path, "w") as f:
        json.dump({"client_id": "id-b"}, f)

    credentials.sync_local_client_secret(config, config.client_id_path, config.token_file_path)

    assert not os.path.exists(config.token_file_path)


def test_explicit_local_client_secret_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "elsewhere" / "secret.json"
    write_client_secret(str(explicit), "explicit-id")
    config = YouTubeConfig(encrypt_path=str(tmp_path / "enc"),
                           local_client_secret_path=str(explicit))

    credentials.sync_local_client_secret(config, config.client_id_path, config.token_file_path)

    assert credentials.extract_client_id(config.client_id_path) == "explicit-id"


# ------------------------------------------------------------ load / refresh

def test_load_missing_token_returns_none(tmp_path):
    assert credentials.load(str(tmp_path / "nope.json"), []) is None


class FakeCreds:
    def __init__(self, error=None):
        self._error = error
        self.refresh_calls = 0

    def refresh(self, request):
        self.refresh_calls += 1
        if self._error:
            raise self._error

    def to_json(self):
        return '{"token": "refreshed"}'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(credentials.time, "sleep", lambda s: None)


def test_refresh_success_saves_token(tmp_path, notifier):
    token_path = str(tmp_path / "token.json")
    creds = FakeCreds()

    result = credentials.refresh(creds, token_path, notifier)

    assert result is creds
    assert json.load(open(token_path)) == {"token": "refreshed"}
    assert notifier.calls == []


def test_refresh_invalid_grant_returns_none_and_notifies(tmp_path, notifier):
    creds = FakeCreds(error=RefreshError("invalid_grant: Token has been revoked"))

    result = credentials.refresh(creds, str(tmp_path / "t.json"), notifier)

    assert result is None
    assert creds.refresh_calls == 1  # permanent failure: no pointless retries
    assert notifier.titles() == ["YouTube re-authorization needed"]


def test_refresh_transient_errors_raise_and_keep_token(tmp_path, notifier):
    creds = FakeCreds(error=ConnectionError("network blip"))

    with pytest.raises(RuntimeError, match="network blip"):
        credentials.refresh(creds, str(tmp_path / "t.json"), notifier)

    assert creds.refresh_calls == 5  # initial try + 4 retries
    assert notifier.titles() == ["YouTube token refresh failing"]
