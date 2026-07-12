"""
Multi-channel fallback notifier, configured entirely via environment variables.

Sends a notification through every channel that is configured. If no channel
is configured (or all fail) the message is still printed to stdout so it shows
up in logs. Duplicate messages are suppressed within a configurable window so
a retry loop does not spam the user.

Supported channels (all optional, all read from environment variables):

    ntfy.sh (zero-signup push to phone/desktop):
        NTFY_TOPIC          - topic name to publish to
        NTFY_SERVER         - server base URL (default: https://ntfy.sh)
        NTFY_TOKEN          - optional access token for protected topics

    Telegram bot:
        TELEGRAM_BOT_TOKEN  - bot token from @BotFather
        TELEGRAM_CHAT_ID    - chat id to send to

    Generic webhook (Slack / Discord / anything that accepts JSON POST):
        NOTIFY_WEBHOOK_URL  - full webhook URL. Slack and Discord payload
                              shapes are auto-detected from the URL.

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


class Notifier:
    """Send notifications through any channel configured via env vars."""

    def __init__(self, state_path: str = _STATE_PATH):
        self._state_path = state_path

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

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

        if dedupe_key and self._recently_sent(dedupe_key):
            print(f"[Notifier] Skipping duplicate notification: {dedupe_key}")
            return False

        delivered = False
        for name, sender in (
            ("ntfy", self._send_ntfy),
            ("telegram", self._send_telegram),
            ("webhook", self._send_webhook),
            ("email", self._send_email),
        ):
            try:
                if sender(title, message, priority):
                    print(f"[Notifier] Sent via {name}")
                    delivered = True
            except Exception as e:
                print(f"[Notifier] {name} failed: {e}")

        if not delivered:
            print("[Notifier] No notification channel configured or all failed. "
                  "Set NTFY_TOPIC, TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, "
                  "NOTIFY_WEBHOOK_URL or GOOGLE_APP_PASSWORD to enable alerts.")

        if delivered and dedupe_key:
            self._mark_sent(dedupe_key)
        return delivered

    # ------------------------------------------------------------------ #
    # channels
    # ------------------------------------------------------------------ #

    def _send_ntfy(self, title: str, message: str, priority: str) -> bool:
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

    def _send_telegram(self, title: str, message: str, priority: str) -> bool:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return False
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"{title}\n\n{message}"},
            timeout=15,
        )
        resp.raise_for_status()
        return True

    def _send_webhook(self, title: str, message: str, priority: str) -> bool:
        url = os.getenv("NOTIFY_WEBHOOK_URL")
        if not url:
            return False
        text = f"{title}\n\n{message}"
        if "discord" in url:
            payload = {"content": text[:2000]}
        elif "slack" in url:
            payload = {"text": text}
        else:
            payload = {"title": title, "message": message, "priority": priority}
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True

    def _send_email(self, title: str, message: str, priority: str) -> bool:
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

    # ------------------------------------------------------------------ #
    # dedupe state
    # ------------------------------------------------------------------ #

    def _load_state(self) -> Dict[str, float]:
        try:
            with open(self._state_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _recently_sent(self, key: str) -> bool:
        window = int(os.getenv("NOTIFY_DEDUPE_SECONDS", "3600"))
        last = self._load_state().get(key, 0)
        return (time.time() - last) < window

    def _mark_sent(self, key: str) -> None:
        state = self._load_state()
        state[key] = time.time()
        # Drop stale entries so the file does not grow forever.
        cutoff = time.time() - 7 * 24 * 3600
        state = {k: v for k, v in state.items() if v > cutoff}
        try:
            with open(self._state_path, "w") as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[Notifier] Warning: could not persist dedupe state: {e}")


if __name__ == "__main__":
    import sys

    title = sys.argv[1] if len(sys.argv) > 1 else "Test notification"
    body = sys.argv[2] if len(sys.argv) > 2 else "Notifier is working."
    ok = Notifier().notify(title, body)
    sys.exit(0 if ok else 1)
