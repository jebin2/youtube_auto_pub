"""
Authentication Worker for Google OAuth2 flows.

Provides functions to run OAuth authentication flows either:
- With a local server (opens browser, receives callback)
- With a manual code entry (for headless/Docker environments)

In headless mode the authorization response can be delivered in three ways,
polled in parallel until one succeeds:
1. Browser automation writes it to `config.authorization_code_path`
2. A human drops the redirect URL into `config.authorization_code_path`
3. A human uploads the redirect URL as `auth_response.txt` (configurable via
   AUTH_RESPONSE_FILENAME) to the configured HuggingFace repo — this allows
   completing re-authorization from a phone after receiving a notification,
   without any access to the machine running the pipeline.
"""

import os
import argparse
import tempfile
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import InstalledAppFlow, Flow

from youtube_auto_pub.config import YouTubeConfig


def process_auth(config: YouTubeConfig) -> None:
    """Run OAuth flow with local server (opens browser).

    This method starts a local HTTP server and opens a browser
    for the user to complete authentication.

    Args:
        config: YouTubeConfig instance containing paths and scopes
    """
    flow = InstalledAppFlow.from_client_secrets_file(config.client_id_path, config.scopes)
    creds = flow.run_local_server(
        port=0,
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true',
        open_browser=False,
        authorization_prompt_message="Please visit this URL to authorize this application: {url}"
    )

    with open(config.token_file_path, 'w') as token:
        token.write(creds.to_json())
        print(f"[Auth] Credentials saved to {config.token_file_path}.")


def _auth_response_filename() -> str:
    return os.getenv("AUTH_RESPONSE_FILENAME", "auth_response.txt")


def build_reauth_instructions(config: YouTubeConfig, auth_url: str) -> str:
    """Build the human instructions for completing authorization remotely."""
    wait_minutes = int(os.getenv("AUTH_CODE_WAIT_SECONDS", "1800")) // 60
    lines = [
        "YouTube needs (re)authorization to keep publishing automatically.",
        "",
        "1. Open this link and approve access:",
        auth_url,
        "",
        "2. After approving, the browser is redirected to a http://localhost/... "
        "page that fails to load - that is expected. Copy the FULL URL from the "
        "address bar.",
        "",
        "3. Deliver that URL back to the pipeline (either option works):",
        f"   - save it as the file: {os.path.abspath(config.authorization_code_path)}",
    ]
    if config.hf_repo_id and config.hf_token:
        lines.append(
            f"   - or upload it as '{_auth_response_filename()}' to "
            f"https://huggingface.co/datasets/{config.hf_repo_id}"
        )
    lines += [
        "",
        f"The pipeline polls for it for {wait_minutes} minutes, then retries on "
        "the next cycle.",
    ]
    return "\n".join(lines)


def _poll_remote_code(config: YouTubeConfig) -> Optional[str]:
    """Check the HuggingFace repo for an auth response file uploaded by the user.

    Returns the file content if found (and deletes the remote file so it is
    only consumed once), otherwise None.
    """
    if not config.hf_repo_id or not config.hf_token:
        return None

    from huggingface_hub import HfApi, hf_hub_download

    filename = _auth_response_filename()
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
                code = f.read().strip()
        if not code:
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
        return code
    except Exception:
        # File not present (yet) - this is the normal case while waiting.
        return None


def _wait_for_code(config: YouTubeConfig) -> Optional[str]:
    """Poll local file and HuggingFace repo until an auth response arrives."""
    wait_seconds = int(os.getenv("AUTH_CODE_WAIT_SECONDS", "1800"))
    poll_interval = int(os.getenv("AUTH_CODE_POLL_SECONDS", "15"))
    deadline = time.time() + wait_seconds

    print(f"[Auth] Waiting up to {wait_seconds}s for authorization response "
          f"(local file: {config.authorization_code_path}"
          + (f", HF repo: {config.hf_repo_id}" if config.hf_repo_id and config.hf_token else "")
          + ")")

    while time.time() < deadline:
        # Option 1/2: local file written by browser automation or a human
        try:
            if os.path.exists(config.authorization_code_path):
                with open(config.authorization_code_path, 'r') as f:
                    code = f.read().strip()
                if code:
                    print("[Auth] Received authorization response via local file.")
                    return code
        except Exception as e:
            print(f"[Auth] Error reading code file: {e}")

        # Option 3: file uploaded to the HuggingFace repo
        code = _poll_remote_code(config)
        if code:
            return code

        time.sleep(poll_interval)

    print("[Auth] Timed out waiting for authorization response.")
    return None


def process_auth_via_code(
    config: YouTubeConfig,
    prompt: bool = False,
    notifier=None
) -> str:
    """Run OAuth flow with manual code entry.

    Designed for headless/Docker environments where a browser cannot be
    opened directly. Prints an authorization URL, optionally notifies the
    user through the configured notification channels, and waits for the
    authorization response (local file, HuggingFace upload, or interactive
    prompt).

    Args:
        config: YouTubeConfig instance containing paths and scopes
        prompt: If True, prompt user for code on stdin. If False, wait for
            the code to arrive via file or HuggingFace repo.
        notifier: Optional Notifier used to alert a human that manual
            authorization is required.

    Returns:
        The authorization URL that was generated
    """
    # Clean up any existing code file
    _remove_file(config.authorization_code_path)

    flow = Flow.from_client_secrets_file(
        config.client_id_path,
        scopes=config.scopes,
        redirect_uri='http://localhost/'
    )

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true',
    )

    print(f"authorization_url####{auth_url}")

    code = None
    if prompt:
        code = input("Please paste the full success url: ").strip()
    else:
        if notifier is not None:
            notifier.notify(
                title="YouTube authorization required",
                message=build_reauth_instructions(config, auth_url),
                priority="urgent",
                dedupe_key="yt-auth-required",
            )
        code = _wait_for_code(config)

    if not code:
        raise ValueError("No authorization code received")

    # Clean up URL (handle encoded entities if read from file/logs)
    import html
    code = html.unescape(code)

    # Parse code from URL
    parsed_url = urlparse(code)
    query_params = parse_qs(parsed_url.query)
    code = query_params.get('code', [None])[0]

    if not code:
        raise ValueError("Could not extract code from URL")

    # Fetch token - suppress scope change warnings by setting include_granted_scopes
    # Google may return additional scopes (like 'openid') that weren't originally requested
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

    flow.fetch_token(code=code)
    creds = flow.credentials

    token_dir = os.path.dirname(config.token_file_path)
    if token_dir:
        os.makedirs(token_dir, exist_ok=True)
    with open(config.token_file_path, 'w') as token:
        token.write(creds.to_json())
        print(f"[Auth] Credentials saved to '{config.token_file_path}'.")

    # The response file has served its purpose; remove it so a stale copy
    # is never replayed on the next auth cycle.
    _remove_file(config.authorization_code_path)

    if notifier is not None:
        notifier.notify(
            title="YouTube authorization successful",
            message="Authorization completed. Automated publishing resumes.",
        )

    return auth_url


def _remove_file(file_path: str) -> None:
    """Remove a file if it exists."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Google OAuth flow.")

    parser.add_argument(
        "--client", "-c",
        required=True,
        help="Path to client_secrets.json"
    )

    parser.add_argument(
        "--token", "-t",
        required=True,
        help="Path to token.json"
    )

    parser.add_argument(
        "--scopes", "-s",
        required=True,
        help="Comma-separated list of OAuth scopes"
    )

    parser.add_argument(
        "--prompt", "-p",
        action="store_true",
        help="Prompt for code input instead of waiting for file"
    )

    parser.add_argument(
        "--file-mode", "-f",
        action="store_true",
        help="Use file-based auth exchange instead of local server"
    )

    parser.add_argument(
        "--code-path",
        help="Path to authorization code file",
        default="./code.txt"
    )

    args = parser.parse_args()
    scopes = args.scopes.split(",")

    config = YouTubeConfig(
        client_secret_filename=args.client,
        token_filename=args.token,
        scopes=scopes,
        authorization_code_path=args.code_path,
        # Allow the subprocess to poll the HuggingFace repo for a remotely
        # uploaded auth response (env vars are inherited from the parent).
        hf_repo_id=os.getenv("HF_YT_CRED_REPO_ID") or os.getenv("HF_REPO_ID") or "",
        hf_token=os.getenv("HF_TOKEN"),
    )

    if args.prompt:
        # Interactive prompt for code
        process_auth_via_code(config, prompt=True)
    elif args.file_mode:
        # File-based wait for code (no prompt)
        process_auth_via_code(config, prompt=False)
    else:
        # Default local server (browser callback)
        process_auth(config)
