"""
OAuth flows: build the consent URL, collect the authorization response,
exchange the code for a token, and persist it.
"""

import html
import os
from typing import Optional
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import InstalledAppFlow, Flow

from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.auth import receivers
from youtube_auto_pub.auth.instructions import build_reauth_instructions


def run_local_server_flow(config: YouTubeConfig) -> None:
    """Interactive flow with a local callback server (desktop machines)."""
    flow = InstalledAppFlow.from_client_secrets_file(config.client_id_path, config.scopes)
    creds = flow.run_local_server(
        port=0,
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true',
        open_browser=False,
        authorization_prompt_message="Please visit this URL to authorize this application: {url}"
    )
    _save_token(config, creds)


def run_code_flow(config: YouTubeConfig, prompt: bool = False, notifier=None) -> str:
    """Flow for unattended/remote machines: no callback server, no browser.

    Prints the consent URL (and, when a notifier is given, pushes it with
    instructions), then collects the redirect URL - from stdin when `prompt`
    is True, otherwise via `receivers.wait_for_response` (local file, ntfy
    reply topic, or HuggingFace upload).

    Returns:
        The authorization URL that was generated.
    """
    receivers.clear_local_file(config.authorization_code_path)

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

    if prompt:
        response = input("Please paste the full success url: ").strip()
    else:
        if notifier is not None:
            notifier.notify(
                title="YouTube authorization required",
                message=build_reauth_instructions(config, auth_url),
                priority="urgent",
                dedupe_key="yt-auth-required",
            )
        response = receivers.wait_for_response(config)

    if not response:
        raise ValueError("No authorization code received")

    code = _extract_code(response)
    if not code:
        raise ValueError("Could not extract code from URL")

    # Google may return extra scopes (like 'openid'); don't treat as an error.
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
    flow.fetch_token(code=code)
    _save_token(config, flow.credentials)

    # The response has served its purpose; never replay a stale copy.
    receivers.clear_local_file(config.authorization_code_path)

    if notifier is not None:
        notifier.notify(
            title="YouTube authorization successful",
            message="Authorization completed. Automated publishing resumes.",
        )
    return auth_url


def _extract_code(response_url: str) -> Optional[str]:
    """Pull the OAuth code out of a pasted redirect URL."""
    response_url = html.unescape(response_url)
    query = parse_qs(urlparse(response_url).query)
    return query.get('code', [None])[0]


def _save_token(config: YouTubeConfig, creds) -> None:
    token_dir = os.path.dirname(config.token_file_path)
    if token_dir:
        os.makedirs(token_dir, exist_ok=True)
    with open(config.token_file_path, 'w') as f:
        f.write(creds.to_json())
    print(f"[Auth] Credentials saved to '{config.token_file_path}'.")
