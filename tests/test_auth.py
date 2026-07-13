import builtins
import json
import sys
import types

import pytest

from youtube_auto_pub.auth import flow as flow_mod
from youtube_auto_pub.auth import receivers
from youtube_auto_pub.auth.instructions import build_reauth_instructions

REDIRECT_URL = "http://localhost/?state=xyz&code=4/0AeaTESTCODE&scope=youtube"


# ------------------------------------------------------------- receivers

def test_ntfy_reply_topic_derivation(monkeypatch):
    assert receivers.ntfy_reply_topic() is None
    monkeypatch.setenv("NTFY_TOPIC", "base")
    assert receivers.ntfy_reply_topic() == "base-reply"
    monkeypatch.setenv("NTFY_REPLY_TOPIC", "explicit")
    assert receivers.ntfy_reply_topic() == "explicit"


def test_check_local_file(tmp_path):
    path = tmp_path / "code.txt"
    assert receivers._check_local_file(str(path)) is None
    path.write_text("  " + REDIRECT_URL + "\n")
    assert receivers._check_local_file(str(path)) == REDIRECT_URL


class FakeNtfyResponse:
    def __init__(self, events):
        self.text = "\n".join(json.dumps(e) for e in events)

    def raise_for_status(self):
        pass


def test_check_ntfy_picks_latest_code_message(monkeypatch):
    monkeypatch.setenv("NTFY_REPLY_TOPIC", "reply")
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params)
        return FakeNtfyResponse([
            {"event": "open"},
            {"event": "message", "message": "just chatting"},
            {"event": "message", "message": REDIRECT_URL},
        ])

    monkeypatch.setattr(receivers.requests, "get", fake_get)

    assert receivers._check_ntfy(since_ts=123) == REDIRECT_URL
    assert captured["url"] == "https://ntfy.sh/reply/json"
    assert captured["params"] == {"poll": "1", "since": "123"}


def test_check_ntfy_ignores_chatter_and_errors(monkeypatch):
    monkeypatch.setenv("NTFY_REPLY_TOPIC", "reply")
    monkeypatch.setattr(receivers.requests, "get",
                        lambda *a, **k: FakeNtfyResponse([{"event": "message", "message": "hi"}]))
    assert receivers._check_ntfy(0) is None

    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(receivers.requests, "get", boom)
    assert receivers._check_ntfy(0) is None  # never raises

    monkeypatch.delenv("NTFY_REPLY_TOPIC")
    assert receivers._check_ntfy(0) is None  # unconfigured -> no-op


def test_check_hf_consumes_response(config, monkeypatch, tmp_path):
    def fake_download(repo_id, filename, repo_type, token, local_dir, force_download):
        path = f"{local_dir}/{filename}"
        with open(path, "w") as f:
            f.write(REDIRECT_URL)
        return path

    deleted = {}

    class FakeApi:
        def __init__(self, token):
            pass

        def delete_file(self, path_in_repo, repo_id, repo_type, commit_message):
            deleted.update(file=path_in_repo, repo=repo_id)

    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.hf_hub_download = fake_download
    fake_hub.HfApi = FakeApi
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    assert receivers._check_hf(config) == REDIRECT_URL
    assert deleted == {"file": "auth_response.txt", "repo": "user/tokens"}


def test_wait_for_response_finds_local_file(config, monkeypatch):
    monkeypatch.setenv("AUTH_CODE_WAIT_SECONDS", "5")
    monkeypatch.setenv("AUTH_CODE_POLL_SECONDS", "1")
    with open(config.authorization_code_path, "w") as f:
        f.write(REDIRECT_URL)
    assert receivers.wait_for_response(config) == REDIRECT_URL


def test_wait_for_response_times_out(config, monkeypatch):
    monkeypatch.setenv("AUTH_CODE_WAIT_SECONDS", "0")
    assert receivers.wait_for_response(config) is None


# ----------------------------------------------------------- instructions

def test_instructions_mention_every_return_path(config, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "alerts")
    text = build_reauth_instructions(config, "https://consent.example")

    assert "https://consent.example" in text
    assert "alerts-reply" in text
    assert "huggingface.co/datasets/user/tokens" in text
    assert config.authorization_code_path in text


# ------------------------------------------------------------------ flow

class FakeFlow:
    def __init__(self):
        self.fetched = {}
        self.credentials = types.SimpleNamespace(to_json=lambda: '{"token": "new"}')

    def authorization_url(self, **kwargs):
        return "https://consent.example", None

    def fetch_token(self, code):
        self.fetched["code"] = code


@pytest.fixture
def fake_flow(config, monkeypatch, tmp_path):
    import os
    os.makedirs(config.encrypt_path, exist_ok=True)
    with open(config.client_id_path, "w") as f:
        json.dump({"installed": {"client_id": "id"}}, f)

    flow = FakeFlow()
    monkeypatch.setattr(flow_mod.Flow, "from_client_secrets_file",
                        classmethod(lambda cls, *a, **k: flow))
    return flow


def test_prompt_mode_reads_stdin_and_saves_token(config, fake_flow, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a: REDIRECT_URL)

    flow_mod.run_code_flow(config, prompt=True)

    assert fake_flow.fetched["code"] == "4/0AeaTESTCODE"
    assert json.load(open(config.token_file_path)) == {"token": "new"}


def test_unattended_mode_notifies_and_waits(config, fake_flow, notifier, monkeypatch):
    monkeypatch.setattr(flow_mod.receivers, "wait_for_response", lambda c: REDIRECT_URL)

    flow_mod.run_code_flow(config, prompt=False, notifier=notifier)

    assert notifier.titles() == ["YouTube authorization required",
                                 "YouTube authorization successful"]
    assert "https://consent.example" in notifier.calls[0]["message"]


def test_no_response_raises(config, fake_flow, notifier, monkeypatch):
    monkeypatch.setattr(flow_mod.receivers, "wait_for_response", lambda c: None)

    with pytest.raises(ValueError, match="No authorization code"):
        flow_mod.run_code_flow(config, prompt=False, notifier=notifier)


def test_html_escaped_response_is_unescaped(config, fake_flow, monkeypatch):
    escaped = "http://localhost/?code=4/0AeaTESTCODE&amp;scope=youtube"
    monkeypatch.setattr(builtins, "input", lambda *a: escaped)

    flow_mod.run_code_flow(config, prompt=True)

    assert fake_flow.fetched["code"] == "4/0AeaTESTCODE"


def test_garbage_response_raises(config, fake_flow, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a: "not a url at all")

    with pytest.raises(ValueError, match="Could not extract code"):
        flow_mod.run_code_flow(config, prompt=True)
