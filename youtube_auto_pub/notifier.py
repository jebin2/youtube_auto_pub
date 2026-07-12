"""
Fallback notifier, configured entirely via environment variables.

Sends a notification through every channel that is configured. If no channel
is configured (or all fail) the message is still printed to stdout so it shows
up in logs. Duplicate messages are suppressed within a configurable window so
a retry loop does not spam the user.

Supported channels (all optional, all read from environment variables):

    ntfy.sh (zero-signup push to phone/desktop):
        NTFY_TOPIC          - topic name to publish to
        NTFY_SERVER         - server base URL (default: https://ntfy.sh)
        NTFY_TOKEN          - optional access token for protected topics

    Email via SMTP (works with a Gmail app password):
        GOOGLE_EMAIL / NOTIFY_SMTP_USER  - SMTP username (sender)
        GOOGLE_APP_PASSWORD / NOTIFY_SMTP_PASSWORD - SMTP password
        NOTIFY_EMAIL_TO     - recipient (default: same as sender)
        NOTIFY_SMTP_HOST    - SMTP host (default: smtp.gmail.com)
        NOTIFY_SMTP_PORT    - SMTP SSL port (default: 465)

    Behaviour tuning:
        NOTIFY_DEDUPE_SECONDS - suppress identical dedupe_key within this many
                                seconds (default: 3600)
"""

import json
import os
import smtplib
import time
from email.message import EmailMessage
from typing import Dict, Optional

import requests

_STATE_PATH = os.path.expanduser("~/.youtube_auto_pub_notifier.json")


# ---------------------------------------------------------------------- #
# channels
# ---------------------------------------------------------------------- #

def _send_via_ntfy(title: str, message: str, priority: str) -> bool:
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return False
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title, "Priority": priority}
    token = os.getenv("NTFY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(
        f"{server}/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return True


def _send_via_email(title: str, message: str, priority: str) -> bool:
    user = os.getenv("NOTIFY_SMTP_USER") or os.getenv("GOOGLE_EMAIL")
    password = os.getenv("NOTIFY_SMTP_PASSWORD") or os.getenv("GOOGLE_APP_PASSWORD")
    if not user or not password:
        return False
    to_addr = os.getenv("NOTIFY_EMAIL_TO", user)
    host = os.getenv("NOTIFY_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("NOTIFY_SMTP_PORT", "465"))

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(message)

    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    return True


_CHANNELS = (
    ("ntfy", _send_via_ntfy),
    ("email", _send_via_email),
)


# ---------------------------------------------------------------------- #
# duplicate suppression
# ---------------------------------------------------------------------- #

class _DedupeStore:
    """Persists when each dedupe key was last sent."""

    def __init__(self, path: str):
        self._path = path

    def recently_sent(self, key: str) -> bool:
        window = int(os.getenv("NOTIFY_DEDUPE_SECONDS", "3600"))
        return (time.time() - self._load().get(key, 0)) < window

    def mark_sent(self, key: str) -> None:
        state = self._load()
        state[key] = time.time()
        # Drop stale entries so the file does not grow forever.
        cutoff = time.time() - 7 * 24 * 3600
        state = {k: v for k, v in state.items() if v > cutoff}
        try:
            with open(self._path, "w") as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[Notifier] Warning: could not persist dedupe state: {e}")

    def _load(self) -> Dict[str, float]:
        try:
            with open(self._path, "r") as f:
                return json.load(f)
        except Exception:
            return {}


# ---------------------------------------------------------------------- #
# public API
# ---------------------------------------------------------------------- #

class Notifier:
    """Send notifications through any channel configured via env vars."""

    def __init__(self, state_path: str = _STATE_PATH):
        self._dedupe = _DedupeStore(state_path)

    def notify(
        self,
        title: str,
        message: str,
        priority: str = "default",
        dedupe_key: Optional[str] = None,
    ) -> bool:
        """Send a notification through every configured channel.

        Args:
            title: Short subject line.
            message: Full message body.
            priority: "default", "high" or "urgent" (used by ntfy).
            dedupe_key: If given, an identical key sent within
                NOTIFY_DEDUPE_SECONDS is silently skipped.

        Returns:
            True if at least one channel delivered the message.
        """
        # Always mirror to stdout so the message appears in logs.
        print(f"[Notifier] {title}\n{message}")

        if dedupe_key and self._dedupe.recently_sent(dedupe_key):
            print(f"[Notifier] Skipping duplicate notification: {dedupe_key}")
            return False

        delivered = False
        for name, send in _CHANNELS:
            try:
                if send(title, message, priority):
                    print(f"[Notifier] Sent via {name}")
                    delivered = True
            except Exception as e:
                print(f"[Notifier] {name} failed: {e}")

        if not delivered:
            print("[Notifier] No notification channel configured or all failed. "
                  "Set NTFY_TOPIC and/or GOOGLE_APP_PASSWORD to enable alerts.")

        if delivered and dedupe_key:
            self._dedupe.mark_sent(dedupe_key)
        return delivered


if __name__ == "__main__":
    import sys

    title = sys.argv[1] if len(sys.argv) > 1 else "Test notification"
    body = sys.argv[2] if len(sys.argv) > 2 else "Notifier is working."
    ok = Notifier().notify(title, body)
    sys.exit(0 if ok else 1)
