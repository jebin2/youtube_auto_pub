"""One-time / manual OAuth authorization.

With your OAuth client JSON in the working directory and the env vars set
(HF_TOKEN, HF_YT_CRED_REPO_ID, ENCRYPT_KEY), this authorizes and stores the
encrypted credentials on HuggingFace in one go:

    python -m youtube_auto_pub.auth --prompt   # paste redirect URL in terminal
    python -m youtube_auto_pub.auth            # respond via ntfy / HF / file
"""

import argparse

from youtube_auto_pub import credentials
from youtube_auto_pub.auth.flow import run_code_flow
from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.token_manager import TokenManager


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Authorize YouTube access (one-time setup or manual re-auth).")
    parser.add_argument("--client", "-c", default="ytcredentials.json",
                        help="Client secret filename (default: ytcredentials.json)")
    parser.add_argument("--token", "-t", default="yttoken.json",
                        help="Token filename (default: yttoken.json)")
    parser.add_argument("--scopes", "-s",
                        help="Comma-separated OAuth scopes (default: YouTube upload/manage)")
    parser.add_argument("--prompt", "-p", action="store_true",
                        help="Paste the redirect URL on stdin instead of waiting for ntfy/HF/file")
    args = parser.parse_args()

    config = YouTubeConfig(client_secret_filename=args.client, token_filename=args.token)
    if args.scopes:
        config.scopes = args.scopes.split(",")

    # When HF storage is configured, sync through it (download existing files,
    # upload the fresh token afterwards). Without it, authorize locally only.
    token_manager = None
    if config.hf_repo_id and config.hf_token and config.encryption_key:
        token_manager = TokenManager(config)
        token_manager.download_and_decrypt(config.token_filename)
        token_manager.download_and_decrypt(config.client_secret_filename)

    # Adopt a client secret sitting in the working directory (first-time setup).
    credentials.sync_local_client_secret(config, config.client_id_path, config.token_file_path)

    run_code_flow(config, prompt=args.prompt)

    if token_manager:
        token_manager.encrypt_and_upload([config.token_file_path, config.client_id_path])
        print("[Auth] Credentials stored on HuggingFace. Setup complete.")


if __name__ == "__main__":
    main()
