# YouTube Auto Publisher

A standalone Python package for YouTube API automation with encrypted credential management and browser-based OAuth.

## Features

- **YouTubeUploader**: Complete video upload with thumbnails, resumable uploads, retry with backoff, and progress tracking
- **TokenManager**: Encrypted credential storage via HuggingFace Hub using Fernet encryption
- **Notifier**: Env-configured fallback notifications (ntfy.sh push + Gmail app-password email)
- **GoogleOAuthAutomator**: Automated browser-based OAuth2 authentication with 2FA support
- **Remote re-auth**: When re-authorization is ever needed, you get a notification with a link; approve from your phone and upload the response to your HuggingFace repo — no server access required
- **YouTubeConfig**: Fully configurable settings via dataclass

## Why not a service account?

**Service accounts do not work with the YouTube Data API for normal channels.**
Google explicitly does not support them: a video uploaded with a service
account is not associated with any channel (uploads fail or end up orphaned).
Service accounts only work for YouTube *Content Owner* (CMS) partner accounts,
which regular creators do not have.

The correct fully-automated setup is:

1. **One-time** interactive OAuth consent → Google issues a **refresh token**.
2. The refresh token silently mints new access tokens forever. No human needed.

### Making the refresh token live forever

This is the part that usually breaks people's automation:

- In Google Cloud Console → *APIs & Services* → *OAuth consent screen*, set the
  **Publishing status to "In production"** (External user type). While the app
  is in **"Testing"** status, every refresh token **expires after 7 days**.
  You do NOT need Google's verification review — an unverified production app
  just shows a warning screen during the one-time consent.
- The refresh token is only invalidated if you: change the Google account
  password (only for some scopes), revoke access manually, don't use it for
  ~6 months, or exceed 50 live refresh tokens per account per client.
- When that ever happens, this package detects `invalid_grant`, notifies you,
  and lets you re-authorize remotely (see Notifications below).

## One-time setup

1. Create a Google Cloud project, enable **YouTube Data API v3**, create an
   **OAuth client ID** (type: *Desktop app*), download `ytcredentials.json`.
2. Set the OAuth consent screen to **In production** (see above).
3. Run the interactive auth once (on any machine with a terminal):

```bash
python -m youtube_auto_pub.auth_worker \
    -c ./encrypt/ytcredentials.json \
    -t ./encrypt/yttoken.json \
    -s "https://www.googleapis.com/auth/youtube.upload,https://www.googleapis.com/auth/youtube,https://www.googleapis.com/auth/youtube.force-ssl,https://www.googleapis.com/auth/userinfo.email" \
    --prompt
```

   Open the printed URL, approve, and paste back the final
   `http://localhost/...` redirect URL.
4. The pipeline (or `TokenManager.encrypt_and_upload`) encrypts and stores the
   token on your HuggingFace repo. From this point everything is unattended.

## Installation

```bash
pip install git+https://github.com/jebin2/youtube_auto_pub.git
```

## Quick Start

```python
from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata

# Configure (required parameters)
config = YouTubeConfig(
    encrypt_path="./my_credentials",
    hf_repo_id="username/my-tokens",
    hf_token="hf_your_token",  # or set HF_TOKEN env var
    encryption_key="your-fernet-key",  # or pass bytes
)

# Create uploader
uploader = YouTubeUploader(config)

# Get authenticated service (handles token refresh and re-auth automatically)
service = uploader.get_service(
    token_path="yttoken.json",
    client_path="ytcredentials.json"
)

# Upload video with metadata
metadata = VideoMetadata(
    title="My Video Title",
    description="Video description here",
    tags=["tag1", "tag2"],
    privacy_status="private",
    publish_at="2025-01-01T12:00:00Z"  # Scheduled publishing
)

video_id = uploader.upload_video(
    service=service,
    video_path="/path/to/video.mp4",
    metadata=metadata,
    thumbnail_path="/path/to/thumbnail.jpg"
)

print(f"Uploaded: https://youtube.com/watch?v={video_id}")
```

## Configuration

The `YouTubeConfig` dataclass accepts the following parameters:

### Required Parameters

| Parameter | Description |
|-----------|-------------|
| `encryption_key` | **Required**. Fernet encryption key for credentials. Can be `str` or `bytes`. |
| `hf_repo_id` | **Required**. HuggingFace Hub repository ID for token storage (e.g., `"username/repo"`). |
| `hf_token` | **Required**. HuggingFace API token for repository access. |

### Optional Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `encrypt_path` | `"./encrypt"` | Directory for encrypted credentials |
| `authorization_code_path` | `"./code.txt"` | OAuth code file for headless mode |
| `browser_executable` | `None` | Browser path (None = system default) |
| `browser_profile_path` | `~/.youtube_auto_pub_browser_profile` | Browser profile directory |
| `is_docker` | `False` | Set to `True` when running in Docker container |
| `has_display` | `True` | Set to `False` if no display is available |
| `headless_mode` | Auto-computed | Run browser headless (computed from `is_docker` or `has_display` if not set) |
| `hf_repo_type` | `"dataset"` | HuggingFace Hub repository type |
| `docker_name` | `"youtube_auto_pub"` | Name for Docker container (used by browser_manager) |
| `host_network` | `True` | Whether to use host network in Docker |

## Environment Variables

```bash
# Required
export HF_TOKEN="hf_your_huggingface_token"
export ENCRYPT_KEY="your-fernet-encryption-key"

# Optional for OAuth browser automation
export GOOGLE_EMAIL="your@gmail.com"
export GOOGLE_PASSWORD="your_google_password"

# Notifications (configure at least one channel for unattended operation)
export NTFY_TOPIC="my-yt-pipeline"                  # push via https://ntfy.sh (zero signup)
export GOOGLE_APP_PASSWORD="abcd efgh ijkl mnop"    # Gmail app password -> email alerts
export NOTIFY_EMAIL_TO="you@example.com"            # defaults to GOOGLE_EMAIL

# ntfy extras (all optional)
export NTFY_SERVER="https://ntfy.sh"     # point at your own server if self-hosting
export NTFY_TOKEN="tk_..."               # access token for protected topics
export NTFY_REPLY_TOPIC="my-yt-reply"    # topic polled for auth responses
                                         # (default: "<NTFY_TOPIC>-reply")

# Tuning (all optional)
export NOTIFY_DEDUPE_SECONDS=3600    # suppress duplicate alerts within this window
export AUTH_CODE_WAIT_SECONDS=1800   # how long to wait for a manual auth response
export AUTH_CODE_POLL_SECONDS=15     # poll interval while waiting
export AUTH_RESPONSE_FILENAME="auth_response.txt"  # filename polled on the HF repo
export UPLOAD_MAX_RETRIES=5          # retries for transient upload errors
```

## Notifications & remote re-authorization

`Notifier` sends alerts through **every channel configured via env vars** and
mirrors everything to stdout. Channels: [ntfy.sh](https://ntfy.sh) push
(easiest — install the app, subscribe to a topic name, set `NTFY_TOPIC`,
done) and email via Gmail app password. Use a random, unguessable topic name
(e.g. `yt-pub-9f3kq1`) since hosted ntfy topics are open to anyone who knows
the name — or self-host and set `NTFY_SERVER`/`NTFY_TOKEN`.

You get alerted when:

- the refresh token is permanently rejected (`invalid_grant`) and re-auth starts
- (re)authorization is required and browser automation failed — the alert
  contains the auth URL and instructions
- authorization succeeds again
- token refresh keeps failing for transient reasons (network/Google outage)
- a video upload fails after all retries

### Completing re-auth from your phone

If re-authorization is ever needed on a headless server:

1. You receive a push notification containing the Google consent URL. Open it
   and approve.
2. The browser redirects to `http://localhost/...` which fails to load —
   expected. Copy that full URL from the address bar.
3. Send it back to the pipeline — any of these works, first one wins:
   - **ntfy (easiest):** publish the URL as a message to your reply topic
     (default `<NTFY_TOPIC>-reply`) — in the ntfy app tap the topic and use
     the publish field, or open `https://ntfy.sh/<reply-topic>` in a browser,
     or `curl -d "<url>" ntfy.sh/<reply-topic>`
   - upload it as `auth_response.txt` to your HuggingFace token repo
   - write it to the configured `authorization_code_path` on the server
4. The pipeline (which polls all sources for up to `AUTH_CODE_WAIT_SECONDS`)
   picks it up, completes the token exchange, and notifies you of success.
   Publishing resumes automatically.

The reply message is only accepted if it arrived *after* the current auth
flow started and contains an OAuth `code=` parameter, so stale or accidental
messages on the topic are ignored. The authorization code itself is
single-use and expires within minutes, and exchanging it also requires your
client secret — but still keep the reply topic name unguessable.

## Components

### YouTubeUploader

Handles all YouTube operations:

```python
uploader = YouTubeUploader(config)

# Get authenticated service (auto token refresh + re-auth)
service = uploader.get_service(token_path, client_path)

# Upload with automatic thumbnail
video_id = uploader.upload_video(service, video_path, metadata, thumbnail_path)

# Just set thumbnail
uploader.set_thumbnail(service, video_id, thumbnail_path)
```

### TokenManager

Encrypted credential storage:

```python
tm = TokenManager(config)
local_path = tm.download_and_decrypt("yttoken.json")
tm.encrypt_and_upload(["yttoken.json", "ytcredentials.json"])
```

### GoogleOAuthAutomator

Browser automation for OAuth:

```python
automator = GoogleOAuthAutomator(config=config)
automator.authorize_oauth("https://accounts.google.com/o/oauth2/auth?...")
```

## Integration Example

For CaptionCreator-style integration:

```python
import os
from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata
import custom_env  # Your project's config

config = YouTubeConfig(
    encrypt_path=custom_env.ENCRYPT_PATH,
    browser_executable=custom_env.BROWSER_EXECUTABLE,
    browser_profile_path=custom_env.BROWSER_PROFILE,
    is_docker=custom_env.IS_DOCKER,
    # Required parameters from environment
    encryption_key=os.getenv("ENCRYPT_KEY").encode(),  # bytes
    hf_repo_id=os.getenv("HF_REPO_ID"),
    hf_token=os.getenv("HF_TOKEN"),
)

uploader = YouTubeUploader(config)
service = uploader.get_service("yttoken.json", "ytcredentials.json")

metadata = VideoMetadata(
    title="My Video",
    description="Description",
    category_id="22",  # People & Blogs
)

video_id = uploader.upload_video(service, "/path/to/video.mp4", metadata)
```

## License

MIT
