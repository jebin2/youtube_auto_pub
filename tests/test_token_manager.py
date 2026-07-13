import os

import pytest
from cryptography.fernet import Fernet

from youtube_auto_pub import token_manager as tm_mod
from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.token_manager import TokenManager

KEY = Fernet.generate_key()


@pytest.fixture
def config(tmp_path):
    return YouTubeConfig(
        encrypt_path=str(tmp_path / "encrypt"),
        hf_repo_id="user/tokens",
        hf_token="hf_test",
        encryption_key=KEY,
    )


def test_missing_settings_reported_together(tmp_path):
    config = YouTubeConfig(encrypt_path=str(tmp_path / "enc"))

    with pytest.raises(ValueError) as exc:
        TokenManager(config)

    message = str(exc.value)
    assert "HF_YT_CRED_REPO_ID" in message
    assert "HF_TOKEN" in message
    assert "ENCRYPT_KEY" in message


def test_init_empties_stale_encrypt_dir(config, tmp_path):
    os.makedirs(config.encrypt_path)
    stale = os.path.join(config.encrypt_path, "stale.json")
    open(stale, "w").write("old")

    TokenManager(config)

    assert os.path.isdir(config.encrypt_path)
    assert not os.path.exists(stale)


def test_encrypt_and_upload_roundtrip(config, tmp_path, monkeypatch):
    calls = {}

    class FakeApi:
        def __init__(self, token):
            calls["token"] = token

        def create_repo(self, repo_id, repo_type, private, exist_ok):
            calls["create"] = {"repo_id": repo_id, "private": private, "exist_ok": exist_ok}

        def upload_folder(self, folder_path, repo_id, repo_type, commit_message,
                          ignore_patterns=None):
            calls["upload"] = {"folder": folder_path, "repo_id": repo_id,
                               "ignore": ignore_patterns}

    monkeypatch.setattr(tm_mod, "HfApi", FakeApi)

    manager = TokenManager(config)
    secret_file = tmp_path / "token.json"
    secret_file.write_text('{"refresh_token": "shh"}')

    manager.encrypt_and_upload([str(secret_file)])

    # Repo auto-created private, cache junk excluded from the upload.
    assert calls["create"] == {"repo_id": "user/tokens", "private": True, "exist_ok": True}
    assert calls["upload"]["repo_id"] == "user/tokens"
    assert ".cache*" in calls["upload"]["ignore"]

    # File on disk is really encrypted, and decrypts back to the original.
    encrypted = open(os.path.join(config.encrypt_path, "token.json"), "rb").read()
    assert b"shh" not in encrypted
    assert Fernet(KEY).decrypt(encrypted) == b'{"refresh_token": "shh"}'


def test_encrypt_and_upload_skips_missing_files(config, monkeypatch):
    uploads = []

    class FakeApi:
        def __init__(self, token): pass
        def create_repo(self, **kw): pass
        def upload_folder(self, **kw): uploads.append(kw)

    monkeypatch.setattr(tm_mod, "HfApi", FakeApi)

    TokenManager(config).encrypt_and_upload(["/nope/missing.json"])

    assert len(uploads) == 1  # upload still runs, nothing crashes
    assert os.listdir(config.encrypt_path) == []


def test_download_and_decrypt(config, monkeypatch):
    plaintext = b'{"refresh_token": "shh"}'

    def fake_download(repo_id, filename, repo_type, token, local_dir):
        path = os.path.join(local_dir, filename)
        with open(path, "wb") as f:
            f.write(Fernet(KEY).encrypt(plaintext))
        return path

    monkeypatch.setattr(tm_mod, "hf_hub_download", fake_download)

    manager = TokenManager(config)
    path = manager.download_and_decrypt("token.json")

    assert open(path).read() == plaintext.decode()


def test_download_missing_file_returns_expected_path(config, monkeypatch):
    def fake_download(**kwargs):
        raise FileNotFoundError("404")

    monkeypatch.setattr(tm_mod, "hf_hub_download", fake_download)

    manager = TokenManager(config)
    path = manager.download_and_decrypt("token.json")

    # First-time setup: path is where the file will be created later.
    assert path == os.path.join(config.encrypt_path, "token.json")
    assert not os.path.exists(path)
