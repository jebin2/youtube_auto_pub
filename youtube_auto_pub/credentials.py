"""
OAuth credential handling: client-secret resolution, token loading,
validation and refresh. Knows nothing about YouTube or notifications
beyond alerting through a provided notifier.
"""

import json
import os
import shutil
import time
from typing import Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from youtube_auto_pub.config import YouTubeConfig


def extract_client_id(client_path: str) -> Optional[str]:
    """Read the client_id from a client_secrets.json file, if present."""
    try:
        if not os.path.exists(client_path):
            return None
        with open(client_path, 'r') as f:
            data = json.load(f)
        for key in ('installed', 'web'):
            if key in data and 'client_id' in data[key]:
                return data[key]['client_id']
        return None
    except Exception as e:
        print(f"[Credentials] Error extracting client_id: {e}")
        return None


def token_matches_client(token_path: str, client_id: str) -> bool:
    """Whether the stored token was issued for the given client_id."""
    try:
        if not os.path.exists(token_path):
            return True  # no token yet, nothing to mismatch
        with open(token_path, 'r') as f:
            data = json.load(f)
        token_client_id = data.get('client_id')
        if token_client_id is None:
            print("[Credentials] Token missing client_id field, will re-authenticate.")
            return False
        return token_client_id == client_id
    except Exception as e:
        print(f"[Credentials] Error checking token client_id: {e}")
        return False


def _candidate_client_paths(config: YouTubeConfig) -> list:
    """Places a local (possibly newer) client secret may live."""
    filename = config.client_secret_filename
    paths = [filename]  # current working directory
    if config.project_path:
        paths.append(os.path.join(config.project_path, filename))
    if config.local_client_secret_path:
        paths.append(config.local_client_secret_path)
    paths.append(os.path.join('/app', filename))  # Docker-mounted files
    return paths


def sync_local_client_secret(config: YouTubeConfig, stored_client_path: str, token_path: str) -> None:
    """Adopt a local client secret when none is stored or the client changed.

    Covers first-time setup (nothing on HuggingFace yet: the user drops the
    downloaded OAuth client JSON next to the app) and client rotation. When
    the client_id changes, the stale token is deleted to force re-auth.
    """
    stored_id = extract_client_id(stored_client_path)

    for candidate in _candidate_client_paths(config):
        if not os.path.exists(candidate):
            continue
        if os.path.abspath(candidate) == os.path.abspath(stored_client_path):
            continue
        local_id = extract_client_id(candidate)
        if not local_id or local_id == stored_id:
            continue

        if stored_id is None:
            print(f"[Credentials] Using local client secret from '{candidate}' (first-time setup)")
        else:
            print(f"[Credentials] Client secret changed ('{candidate}'). Forcing re-authentication.")
        try:
            os.makedirs(os.path.dirname(stored_client_path) or '.', exist_ok=True)
            shutil.copy(candidate, stored_client_path)
            if stored_id is not None and os.path.exists(token_path):
                os.remove(token_path)
            stored_id = local_id
        except Exception as e:
            print(f"[Credentials] Error adopting local client secret: {e}")
        break

    # Drop a token that was issued for a different client.
    current_id = extract_client_id(stored_client_path)
    if current_id and not token_matches_client(token_path, current_id):
        print("[Credentials] Token does not match the client secret. Deleting it to force re-auth.")
        try:
            if os.path.exists(token_path):
                os.remove(token_path)
        except Exception as e:
            print(f"[Credentials] Error deleting stale token: {e}")


def load(token_path: str, scopes: list) -> Optional[Credentials]:
    """Load stored credentials, or None if absent/unreadable."""
    if not os.path.exists(token_path):
        return None
    try:
        creds = Credentials.from_authorized_user_file(token_path, scopes)
        print("[Credentials] Found existing credentials.")
        return creds
    except Exception as e:
        print(f"[Credentials] Error loading credentials: {e}")
        return None


def refresh(creds: Credentials, token_path: str, notifier) -> Optional[Credentials]:
    """Refresh expired credentials, retrying transient errors with backoff.

    Returns the refreshed credentials, or None when the refresh token is
    permanently invalid (revoked/expired) and re-authentication is required.

    Raises:
        RuntimeError: if refresh keeps failing for transient reasons. Callers
            must let this propagate so the outer retry loop tries again later
            instead of discarding a still-valid refresh token.
    """
    delays = (0, 2, 4, 8, 16)
    last_error = None
    for attempt, delay in enumerate(delays):
        if delay:
            print(f"[Credentials] Retrying token refresh in {delay}s "
                  f"(attempt {attempt}/{len(delays) - 1})...")
            time.sleep(delay)
        try:
            creds.refresh(Request())
            with open(token_path, 'w') as f:
                f.write(creds.to_json())
            print("[Credentials] Credentials refreshed and saved.")
            return creds
        except RefreshError as e:
            message = str(e).lower()
            if 'invalid_grant' in message or 'invalid_rapt' in message or 'deleted_client' in message:
                print(f"[Credentials] Refresh token permanently invalid ({e}).")
                notifier.notify(
                    title="YouTube re-authorization needed",
                    message=(
                        "The stored YouTube refresh token was rejected by Google "
                        f"({e}).\nCommon causes: OAuth consent screen still in "
                        "'Testing' status (tokens expire after 7 days - publish "
                        "the app to Production), password change, or manual "
                        "revocation.\nStarting the re-authorization flow now."
                    ),
                    priority="urgent",
                    dedupe_key="yt-token-invalid",
                )
                return None
            last_error = e
            print(f"[Credentials] Transient refresh error: {e}")
        except Exception as e:
            last_error = e
            print(f"[Credentials] Transient refresh error: {e}")

    notifier.notify(
        title="YouTube token refresh failing",
        message=(
            f"Token refresh failed {len(delays)} times in a row "
            f"(last error: {last_error}).\nThe refresh token is kept and the "
            "pipeline will retry on the next cycle. Check network/Google API "
            "status if this persists."
        ),
        priority="high",
        dedupe_key="yt-refresh-transient",
    )
    raise RuntimeError(f"Token refresh failed after retries: {last_error}")
