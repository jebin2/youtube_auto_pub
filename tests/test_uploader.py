import json
import os
import types

import pytest
from googleapiclient.errors import HttpError

from youtube_auto_pub import uploader as up_mod
from youtube_auto_pub.uploader import VideoMetadata, YouTubeUploader


@pytest.fixture
def uploader(config, notifier, monkeypatch):
    monkeypatch.setattr(up_mod.time, "sleep", lambda s: None)
    u = YouTubeUploader(config)
    u.notifier = notifier
    return u


# -------------------------------------------------------------- get_service

def make_valid_token(config):
    os.makedirs(config.encrypt_path, exist_ok=True)
    with open(config.client_id_path, "w") as f:
        json.dump({"installed": {"client_id": "id-1"}}, f)
    with open(config.token_file_path, "w") as f:
        json.dump({"client_id": "id-1"}, f)


def test_get_service_with_valid_creds(uploader, config, monkeypatch):
    make_valid_token(config)
    monkeypatch.setattr(uploader.token_manager, "download_and_decrypt",
                        lambda name: os.path.join(config.encrypt_path, name))
    uploaded = []
    monkeypatch.setattr(uploader.token_manager, "encrypt_and_upload",
                        lambda paths: uploaded.extend(paths))

    valid_creds = types.SimpleNamespace(valid=True, expired=False, refresh_token="r")
    monkeypatch.setattr(up_mod.credentials, "load", lambda path, scopes: valid_creds)
    monkeypatch.setattr(up_mod, "build",
                        lambda *a, **k: types.SimpleNamespace(
                            channels=lambda: types.SimpleNamespace(
                                list=lambda **kw: types.SimpleNamespace(execute=lambda: {}))))

    service = uploader.get_service(cache_key="main")

    assert service is not None
    assert len(uploaded) == 2  # token + client secret re-uploaded
    assert uploader.get_service(cache_key="main") is service  # cached


def test_get_service_skip_auth_flow(uploader, config, monkeypatch):
    monkeypatch.setattr(uploader.token_manager, "download_and_decrypt",
                        lambda name: os.path.join(config.encrypt_path, name))
    monkeypatch.setattr(up_mod.credentials, "load", lambda path, scopes: None)

    assert uploader.get_service(skip_auth_flow=True) is None


def test_auth_failure_notifies_and_raises(uploader, notifier, monkeypatch):
    def failing_flow(config, prompt=False, notifier=None):
        raise ValueError("No authorization code received")

    monkeypatch.setattr(up_mod, "run_code_flow", failing_flow)
    monkeypatch.setattr(up_mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(ValueError):
        uploader._run_auth_flow()

    assert notifier.titles() == ["YouTube authorization failed"]


# ------------------------------------------------------------- upload_video

def http_error(status):
    resp = types.SimpleNamespace(status=status, reason="err")
    return HttpError(resp, b"boom")


class FakeRequest:
    """Yields configured errors, then progress, then a response."""

    def __init__(self, errors=()):
        self._errors = list(errors)

    def next_chunk(self):
        if self._errors:
            raise self._errors.pop(0)
        return None, {"id": "vid-123"}


class FakeService:
    def __init__(self, request):
        self._request = request
        self.body = None

    def videos(self):
        return types.SimpleNamespace(insert=self._insert)

    def _insert(self, part, body, media_body):
        self.body = body
        return self._request


@pytest.fixture(autouse=True)
def fake_media(monkeypatch):
    monkeypatch.setattr(up_mod, "MediaFileUpload",
                        lambda path, chunksize=None, resumable=None: object())


def test_upload_success_builds_correct_body(uploader):
    service = FakeService(FakeRequest())
    metadata = VideoMetadata(title="T" * 150, description="d", tags=["a"],
                             privacy_status="private",
                             publish_at="2026-08-01T12:00:00Z")

    video_id = uploader.upload_video(service, "v.mp4", metadata)

    assert video_id == "vid-123"
    assert len(service.body["snippet"]["title"]) == 100  # clamped
    assert service.body["status"]["publishAt"] == "2026-08-01T12:00:00Z"


def test_upload_retries_transient_5xx(uploader):
    service = FakeService(FakeRequest(errors=[http_error(503), http_error(500)]))

    assert uploader.upload_video(service, "v.mp4", VideoMetadata(title="t")) == "vid-123"


def test_upload_gives_up_on_4xx_and_notifies(uploader, notifier):
    service = FakeService(FakeRequest(errors=[http_error(403)]))

    assert uploader.upload_video(service, "v.mp4", VideoMetadata(title="t")) is None
    assert notifier.titles() == ["YouTube upload failed"]


def test_upload_retry_budget_exhausted(uploader, notifier, monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_RETRIES", "2")
    service = FakeService(FakeRequest(errors=[http_error(503)] * 3))

    assert uploader.upload_video(service, "v.mp4", VideoMetadata(title="t")) is None
    assert notifier.titles() == ["YouTube upload failed"]


# --------------------------------------------------------------- end screen

def test_end_screen_rejects_short_video(uploader):
    service = types.SimpleNamespace(videos=lambda: types.SimpleNamespace(
        list=lambda **kw: types.SimpleNamespace(
            execute=lambda: {"items": [{"contentDetails": {"duration": "PT20S"}}]})))

    assert uploader.add_end_screen_video(service, "vid", "related") is False


def test_video_duration_parsing(uploader):
    service = types.SimpleNamespace(videos=lambda: types.SimpleNamespace(
        list=lambda **kw: types.SimpleNamespace(
            execute=lambda: {"items": [{"contentDetails": {"duration": "PT1H2M3S"}}]})))

    assert uploader._video_duration_ms(service, "vid") == (3600 + 120 + 3) * 1000
