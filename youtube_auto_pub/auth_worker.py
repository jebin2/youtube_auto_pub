"""
Authentication Worker for Google OAuth2 flows.

Provides functions to run OAuth authentication flows either:
- With a local server (opens browser, receives callback)
- With a manual code entry (for headless/Docker environments)
"""

import os
import argparse
import time
from typing import List, Optional
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
    flow = InstalledAppFlow.from_client_secrets_file(config.client_secret_path, config.scopes)
    creds = flow.run_local_server(
        port=0,
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true',
        open_browser=False,
        authorization_prompt_message="Please visit this URL to authorize this application: {url}"
    )
    
    with open(config.token_path, 'w') as token:
        token.write(creds.to_json())
        print(f"[Auth] Credentials saved to {config.token_path}.")


def process_auth_via_code(
    config: YouTubeConfig,
    prompt: bool = False
) -> str:
    """Run OAuth flow with manual code entry.
    
    This method is designed for headless/Docker environments where
    a browser cannot be opened directly. It prints an authorization URL
    and waits for the user to paste the callback URL.
    
    Args:
        config: YouTubeConfig instance containing paths and scopes
        prompt: If True, prompt user for code. If False, wait for code file.
        
    Returns:
        The authorization URL that was generated
    """
    # Clean up any existing code file
    _remove_file(config.authorization_code_path)
    
    flow = Flow.from_client_secrets_file(
        config.client_secret_path,
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
        # Wait for code file to be created (by browser automation)
        count = 0
        max_attempts = 20
        while count < max_attempts and (code is None or code == ""):
            try:
                with open(config.authorization_code_path, 'r') as file:
                    code = file.read().strip()
                print("[Auth] Waiting for authorization code...", end="\r")
                time.sleep(10)
                count += 1
            except FileNotFoundError:
                time.sleep(10)
                count += 1
            except Exception:
                pass

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
    import os
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
    
    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(config.token_path, 'w') as token:
        token.write(creds.to_json())
        print(f"[Auth] Credentials saved to '{config.token_path}'.")
    
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

    args = parser.parse_args()
    scopes = args.scopes.split(",")
    
    config = YouTubeConfig(
        client_secret_path=args.client,
        token_path=args.token,
        scopes=scopes
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
