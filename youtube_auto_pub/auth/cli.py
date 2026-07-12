"""Command-line entry point for one-time / manual OAuth authorization.

Usage:
    python -m youtube_auto_pub.auth -c client.json -t token.json -s <scopes> --prompt
"""

import argparse
import os

from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.auth.flow import run_code_flow, run_local_server_flow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Google OAuth flow.")
    parser.add_argument("--client", "-c", required=True, help="Path to client_secrets.json")
    parser.add_argument("--token", "-t", required=True, help="Path to token.json")
    parser.add_argument("--scopes", "-s", required=True, help="Comma-separated OAuth scopes")
    parser.add_argument("--prompt", "-p", action="store_true",
                        help="Paste the redirect URL on stdin (interactive one-time setup)")
    parser.add_argument("--file-mode", "-f", action="store_true",
                        help="Wait for the response via file / ntfy / HuggingFace instead of stdin")
    parser.add_argument("--code-path", default="./code.txt", help="Path to authorization code file")
    args = parser.parse_args()

    config = YouTubeConfig(
        client_secret_filename=args.client,
        token_filename=args.token,
        scopes=args.scopes.split(","),
        authorization_code_path=args.code_path,
        # Allow polling the HuggingFace repo for a remotely uploaded response.
        hf_repo_id=os.getenv("HF_YT_CRED_REPO_ID") or os.getenv("HF_REPO_ID") or "",
        hf_token=os.getenv("HF_TOKEN"),
    )

    if args.prompt:
        run_code_flow(config, prompt=True)
    elif args.file_mode:
        run_code_flow(config, prompt=False)
    else:
        run_local_server_flow(config)


if __name__ == "__main__":
    main()
