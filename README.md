# YouTube Auto Publisher

Unattended YouTube uploads with encrypted credential storage and
notification-based OAuth. No browser automation, no server access needed for
re-authorization — everything after the one-time setup runs by itself.

**How it works:** a one-time OAuth consent yields a long-lived refresh token,
stored Fernet-encrypted in a private HuggingFace dataset repo. Every upload
silently refreshes the access token (a plain HTTPS call — nothing for Google
to flag). If the refresh token ever dies, you get a push notification with a
consent link: approve on your phone, send the redirect URL back through the
ntfy app, and publishing resumes on its own.

> **Why not a service account?** The YouTube Data API does not support
> service accounts for normal channels — videos uploaded by one are not
> associated with any channel. A refresh token is the correct unattended setup.

## Install

```bash
pip install git+https://github.com/jebin2/youtube_auto_pub.git
```

## Initial setup (from nothing)

You need three things once: a Google OAuth client, a Fernet key, and a
HuggingFace token. ~10 minutes.

**1. Google Cloud** (console.cloud.google.com)
   - Create a project, enable **YouTube Data API v3**.
   - *OAuth consent screen*: type **External**, then **Publish app** (status
     "In production"). Ignore the verification warnings — with "Testing"
     status your refresh token would expire every 7 days.
   - *Credentials* → create **OAuth client ID** (type: **Desktop app**) and
     download the JSON, e.g. as `ytcredentials.json`.

**2. Generate an encryption key**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**3. HuggingFace**: create a token with write access at
   huggingface.co/settings/tokens. The dataset repo for credentials is
   created automatically (private) on first run — just pick a name.

**4. First run** — place `ytcredentials.json` in the working directory and
   set the env vars below. There is no token yet, so the auth flow starts:

   - *With a terminal:* the consent URL is printed; open it, approve, paste
     the final `http://localhost/...` redirect URL back.
   - *Unattended (no terminal at all):* the consent URL arrives as a push
     notification; approve on your phone and publish the redirect URL to
     your ntfy reply topic (see below).

   Either way the tokens are then encrypted and uploaded to the HF repo
   automatically. You can delete the local `ytcredentials.json` afterwards —
   every future machine only needs the env vars.

Standalone one-time auth (without running your pipeline):

```bash
python -m youtube_auto_pub.auth \
    -c ./encrypt/ytcredentials.json -t ./encrypt/yttoken.json \
    -s "https://www.googleapis.com/auth/youtube.upload,https://www.googleapis.com/auth/youtube,https://www.googleapis.com/auth/youtube.force-ssl,https://www.googleapis.com/auth/userinfo.email" \
    --prompt
```

## Usage

```python
from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata

config = YouTubeConfig(
    encrypt_path="./my_credentials",
    hf_repo_id="username/my-tokens",
    hf_token="hf_...",
    encryption_key="your-fernet-key",
    client_secret_filename="ytcredentials.json",
    token_filename="yttoken.json",
)

uploader = YouTubeUploader(config)
service = uploader.get_service()  # refresh / re-auth handled automatically

video_id = uploader.upload_video(
    service=service,
    video_path="video.mp4",
    metadata=VideoMetadata(
        title="My Video",
        description="...",
        tags=["tag1"],
        privacy_status="private",
        publish_at="2026-08-01T12:00:00Z",  # optional scheduling
    ),
    thumbnail_path="thumb.jpg",  # optional
)
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `HF_TOKEN` | yes | HuggingFace token (write access) |
| `ENCRYPT_KEY` | yes | Fernet key for credential encryption |
| `NTFY_TOPIC` | recommended | [ntfy.sh](https://ntfy.sh) topic for push alerts — install the app, subscribe to an unguessable name (e.g. `yt-pub-9f3kq1`) |
| `GOOGLE_EMAIL` + `GOOGLE_APP_PASSWORD` | optional | Gmail app password → email alerts as backup channel |
| `NOTIFY_EMAIL_TO` | optional | Email recipient (default: `GOOGLE_EMAIL`) |
| `NTFY_REPLY_TOPIC` | optional | Topic polled for auth responses (default `<NTFY_TOPIC>-reply`) |
| `NTFY_SERVER` / `NTFY_TOKEN` | optional | Self-hosted ntfy server / access token |
| `NOTIFY_DEDUPE_SECONDS` | optional | Suppress duplicate alerts (default 3600) |
| `AUTH_CODE_WAIT_SECONDS` | optional | Wait window for an auth response (default 1800) |
| `AUTH_CODE_POLL_SECONDS` | optional | Poll interval while waiting (default 15) |
| `AUTH_RESPONSE_FILENAME` | optional | Auth response file polled on the HF repo (default `auth_response.txt`) |
| `UPLOAD_MAX_RETRIES` | optional | Retries for transient upload errors (default 5) |

Notifications fire on: re-auth required (with the consent link), auth
success/failure, persistent token-refresh failures, and upload failures.
Test with: `python -m youtube_auto_pub.notifier "Test" "Hello"`.

## Re-authorization from your phone

Rare (revoked token, password change, 6 months unused), and takes a minute:

1. Push notification arrives with the consent URL → open, approve.
2. The redirect to `http://localhost/...` fails to load — expected. Copy the
   full URL from the address bar.
3. Send it back (first one wins):
   - **ntfy:** publish it to your reply topic from the app
   - upload it as `auth_response.txt` to the HF repo
   - write it to `authorization_code_path` on the server
4. You get a success notification; publishing resumes.

Replies are only accepted if newer than the current auth attempt and
containing an OAuth `code=` parameter; the code is single-use, short-lived,
and useless without your client secret.

## Package layout

One responsibility per module:

```
youtube_auto_pub/
├── config.py         # YouTubeConfig dataclass — settings only
├── notifier.py       # alert dispatch (ntfy + email) with duplicate suppression
├── token_manager.py  # encrypted credential storage on HuggingFace Hub
├── credentials.py    # client-secret resolution, token loading and refresh
├── uploader.py       # YouTube API calls: service, upload, thumbnail, end screen
└── auth/
    ├── flow.py         # consent URL → code exchange → token persistence
    ├── receivers.py    # how a response reaches us: file / ntfy reply / HF upload
    ├── instructions.py # human-facing re-auth message
    └── cli.py          # `python -m youtube_auto_pub.auth`
```

## YouTubeConfig reference

| Parameter | Default | Description |
|---|---|---|
| `encryption_key` | — | **Required.** Fernet key (`str` or `bytes`) |
| `hf_repo_id` | — | **Required.** HF dataset repo for tokens |
| `hf_token` | — | **Required.** HF API token |
| `client_secret_filename` | — | **Required.** e.g. `ytcredentials.json` |
| `token_filename` | — | **Required.** e.g. `yttoken.json` |
| `encrypt_path` | `./encrypt` | Working dir for (de)crypted files |
| `authorization_code_path` | `./code.txt` | Local auth-response file |
| `hf_repo_type` | `dataset` | HF repo type |
| `project_path` / `local_client_secret_path` | `None` | Extra locations searched for a local client secret |
| `scopes` | YouTube upload/manage | OAuth scopes |

## License

MIT
