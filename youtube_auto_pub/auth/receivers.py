"""
Ways an OAuth authorization response can reach the pipeline.

`wait_for_response` polls every available source until one delivers:
  - a local file (written by a human with access to the machine)
  - the ntfy reply topic (published from the ntfy app on a phone)
  - an `auth_response.txt` uploaded to the HuggingFace credential repo
"""

import json
import os
import tempfile
import time
from typing import Optional

import requests

from youtube_auto_pub.config import YouTubeConfig


def auth_response_filename() -> str:
    return os.getenv("AUTH_RESPONSE_FILENAME", "auth_response.txt")


def ntfy_reply_topic() -> Optional[str]:
    """Topic polled for the auth response published from the ntfy app."""
    topic = os.getenv("NTFY_REPLY_TOPIC")
    if topic:
        return topic
    base = os.getenv("NTFY_TOPIC")
    return f"{base}-reply" if base else None


def clear_local_file(path: str) -> None:
    """Remove a (possibly stale) local auth-response file."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _check_local_file(path: str) -> Optional[str]:
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                content = f.read().strip()
            if content:
                print("[Auth] Received authorization response via local file.")
                return content
    except Exception as e:
        print(f"[Auth] Error reading code file: {e}")
    return None


def _check_ntfy(since_ts: int) -> Optional[str]:
    """Newest OAuth-looking message on the reply topic, newer than since_ts.

    The since filter guarantees a response from a previous flow is never
    replayed; requiring a code= parameter ignores unrelated chatter.
    """
    topic = ntfy_reply_topic()
    if not topic:
        return None

    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {}
    token = os.getenv("NTFY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(
            f"{server}/{topic}/json",
            params={"poll": "1", "since": str(since_ts)},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[Auth] ntfy poll failed: {e}")
        return None

    latest = None
    for line in resp.text.splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get("event") != "message":
            continue
        message = (event.get("message") or "").strip()
        if "code=" in message:
            latest = message
    if latest:
        print("[Auth] Received authorization response via ntfy.")
    return latest


def _check_hf(config: YouTubeConfig) -> Optional[str]:
    """Auth response uploaded to the HuggingFace repo (consumed on read)."""
    if not config.hf_repo_id or not config.hf_token:
        return None

    from huggingface_hub import HfApi, hf_hub_download

    filename = auth_response_filename()
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloaded = hf_hub_download(
                repo_id=config.hf_repo_id,
                filename=filename,
                repo_type=config.hf_repo_type,
                token=config.hf_token,
                local_dir=tmp_dir,
                force_download=True,
            )
            with open(downloaded, 'r') as f:
                content = f.read().strip()
        if not content:
            return None
        try:
            HfApi(token=config.hf_token).delete_file(
                path_in_repo=filename,
                repo_id=config.hf_repo_id,
                repo_type=config.hf_repo_type,
                commit_message="Consume auth response",
            )
        except Exception as e:
            print(f"[Auth] Warning: could not delete remote {filename}: {e}")
        print("[Auth] Received authorization response via HuggingFace Hub.")
        return content
    except Exception:
        # File not present (yet) - the normal case while waiting.
        return None


def wait_for_response(config: YouTubeConfig) -> Optional[str]:
    """Poll all sources until an auth response arrives or the window closes."""
    wait_seconds = int(os.getenv("AUTH_CODE_WAIT_SECONDS", "1800"))
    poll_interval = int(os.getenv("AUTH_CODE_POLL_SECONDS", "15"))
    started_at = int(time.time())
    deadline = started_at + wait_seconds

    sources = [f"local file: {config.authorization_code_path}"]
    if ntfy_reply_topic():
        sources.append(f"ntfy topic: {ntfy_reply_topic()}")
    if config.hf_repo_id and config.hf_token:
        sources.append(f"HF repo: {config.hf_repo_id}")
    print(f"[Auth] Waiting up to {wait_seconds}s for authorization response "
          f"({'; '.join(sources)})")

    while time.time() < deadline:
        response = (
            _check_local_file(config.authorization_code_path)
            or _check_ntfy(started_at)
            or _check_hf(config)
        )
        if response:
            return response
        time.sleep(poll_interval)

    print("[Auth] Timed out waiting for authorization response.")
    return None
