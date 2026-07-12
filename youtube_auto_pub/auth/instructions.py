"""Human-facing instructions for completing authorization remotely."""

import os

from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.auth.receivers import auth_response_filename, ntfy_reply_topic


def build_reauth_instructions(config: YouTubeConfig, auth_url: str) -> str:
    """The message sent to the user when manual authorization is needed."""
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
        "3. Send that URL back to the pipeline (any option works):",
    ]
    reply_topic = ntfy_reply_topic()
    if reply_topic:
        server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        lines.append(
            f"   - publish it to the ntfy topic '{reply_topic}' "
            f"(in the ntfy app, or at {server}/{reply_topic})"
        )
    if config.hf_repo_id and config.hf_token:
        lines.append(
            f"   - upload it as '{auth_response_filename()}' to "
            f"https://huggingface.co/datasets/{config.hf_repo_id}"
        )
    lines.append(
        f"   - save it on the server as: {os.path.abspath(config.authorization_code_path)}"
    )
    lines += [
        "",
        f"The pipeline polls for it for {wait_minutes} minutes, then retries on "
        "the next cycle.",
    ]
    return "\n".join(lines)
