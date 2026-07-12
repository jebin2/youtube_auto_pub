# youtube_auto_pub

Upload videos to YouTube from unattended servers — forever, without a human.

```python
from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata

uploader = YouTubeUploader(YouTubeConfig())   # config comes from env vars
service = uploader.get_service()              # auth handled automatically
uploader.upload_video(service, "video.mp4", VideoMetadata(title="My Video"))
```

**How it stays unattended:** you authorize once, Google issues a long-lived
refresh token, and from then on every upload mints a fresh access token over
a plain HTTPS call — no browser, no login page, nothing that breaks. The
credentials live Fernet-encrypted in a private HuggingFace repo, so any
machine with three env vars can publish. In the rare case Google kills the
refresh token, you get a push notification on your phone and fix it from
there in under a minute — no server access needed.

There is deliberately **no browser automation** (Google's login page is a
moving target and hostile to bots) and **no service account** (the YouTube
Data API does not support them for normal channels — videos uploaded by one
belong to no channel).

## Setup

You need a Google OAuth client, a Fernet key, and a HuggingFace token.
Once. ~10 minutes.

**1. Google Cloud** — [console.cloud.google.com](https://console.cloud.google.com)

- Create a project and enable **YouTube Data API v3**.
- *OAuth consent screen* → user type **External** → **Publish app**.
  Ignore the verification warnings — the point is the "In production"
  status: while an app is in "Testing", refresh tokens die every 7 days
  and your automation dies weekly. Unverified-in-production is fine for
  personal use; you'll click through one warning screen during consent.
- *Credentials* → **Create OAuth client ID** → type **Desktop app** →
  download the JSON as `ytcredentials.json`.

**2. Keys** — generate a Fernet key, and create a HuggingFace token with
write access at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**3. Environment**

```bash
export HF_TOKEN="hf_..."                  # HuggingFace write token
export HF_YT_CRED_REPO_ID="you/yt-tokens" # repo for credentials (auto-created, private)
export ENCRYPT_KEY="<fernet key>"         # from step 2
export NTFY_TOPIC="yt-pub-9f3kq1"         # push alerts - pick an unguessable name
```

For `NTFY_TOPIC`: install the [ntfy](https://ntfy.sh) app on your phone and
subscribe to the same topic name. That's the entire notification setup.

**4. Authorize** — with `ytcredentials.json` in the working directory:

```bash
python -m youtube_auto_pub.auth --prompt
```

Open the printed URL, approve, paste the final `http://localhost/...`
redirect URL back. This one command adopts the client secret, exchanges the
code, and stores everything encrypted on HuggingFace. Delete the local
`ytcredentials.json` afterwards — from now on, any machine with the env
vars can publish.

(No terminal anywhere? Skip this step and just start your pipeline — the
consent link arrives as a push notification and you answer from your phone,
exactly like re-authorization below.)

## Install

```bash
pip install git+https://github.com/jebin2/youtube_auto_pub.git
```

## API

```python
config = YouTubeConfig()   # or override per channel:
config = YouTubeConfig(token_filename="channel2_token.json",
                       client_secret_filename="channel2_creds.json")

uploader = YouTubeUploader(config)
service = uploader.get_service(cache_key="main")   # cached per key

video_id = uploader.upload_video(
    service, "video.mp4",
    VideoMetadata(
        title="My Video",                     # required
        description="...",
        tags=["tag1"],
        category_id="24",                     # default "22"
        privacy_status="private",             # "public" | "private" | "unlisted"
        publish_at="2026-08-01T12:00:00Z",    # optional scheduled publish
    ),
    thumbnail_path="thumb.jpg",               # optional
)

uploader.set_thumbnail(service, video_id, "thumb.jpg")
uploader.add_end_screen_video(service, video_id, related_video_id)
```

Uploads are resumable and retry transient errors (HTTP 5xx, network) with
backoff. Token refresh retries the same way and never discards a working
refresh token over a network blip — only a genuine `invalid_grant` triggers
re-authorization.

## Notifications

Alerts go through every configured channel and are deduplicated (default:
one identical alert per hour). Two channels:

| Channel | Env vars |
|---|---|
| [ntfy.sh](https://ntfy.sh) push | `NTFY_TOPIC` (+ optional `NTFY_SERVER`, `NTFY_TOKEN` for self-hosting) |
| Email (Gmail app password) | `GOOGLE_EMAIL`, `GOOGLE_APP_PASSWORD` (+ optional `NOTIFY_EMAIL_TO`) |

You get notified on: re-authorization required (with the consent link),
authorization success/failure, persistent refresh failures, upload failures.

```bash
python -m youtube_auto_pub.notifier "Test" "Hello"   # test your channels
```

## Re-authorization from your phone

Happens only if the refresh token is revoked, the account password changes,
or the token goes unused ~6 months:

1. Push notification arrives with the consent URL → open, approve.
2. The redirect to `http://localhost/...` fails to load — expected.
   Copy the full URL from the address bar.
3. Send it back — whichever is easiest, first one wins:
   - **ntfy:** publish it to your reply topic (default `<NTFY_TOPIC>-reply`)
     from the app
   - upload it as `auth_response.txt` to the HuggingFace repo
   - write it to the `authorization_code_path` file on the server
4. Success notification arrives; publishing resumes on its own.

The pipeline polls for 30 minutes (configurable), accepts only responses
newer than the current attempt that carry an OAuth `code=` parameter, and
retries on the next cycle if you miss the window. The code itself is
single-use, expires in minutes, and is useless without your client secret —
but still keep the topic names unguessable.

## Reference

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `HF_TOKEN` | yes | HuggingFace token (write) |
| `HF_YT_CRED_REPO_ID` | yes | HuggingFace dataset repo for credentials |
| `ENCRYPT_KEY` | yes | Fernet key |
| `NTFY_TOPIC` | recommended | ntfy topic for push alerts |
| `GOOGLE_EMAIL` / `GOOGLE_APP_PASSWORD` | optional | email alert channel |
| `NOTIFY_EMAIL_TO` | optional | email recipient (default: sender) |
| `NTFY_REPLY_TOPIC` | optional | auth-response topic (default `<NTFY_TOPIC>-reply`) |
| `NTFY_SERVER` / `NTFY_TOKEN` | optional | self-hosted ntfy server / token |
| `NOTIFY_DEDUPE_SECONDS` | optional | duplicate-alert window (default 3600) |
| `AUTH_CODE_WAIT_SECONDS` | optional | auth-response wait window (default 1800) |
| `AUTH_CODE_POLL_SECONDS` | optional | poll interval (default 15) |
| `AUTH_RESPONSE_FILENAME` | optional | response file on HF (default `auth_response.txt`) |
| `UPLOAD_MAX_RETRIES` | optional | upload retry budget (default 5) |

### YouTubeConfig

Every field is optional; credentials fall back to the env vars above.

| Parameter | Default | Description |
|---|---|---|
| `client_secret_filename` | `ytcredentials.json` | client secret file (per channel) |
| `token_filename` | `yttoken.json` | token file (per channel) |
| `encrypt_path` | `./encrypt` | working dir for (de)crypted files |
| `authorization_code_path` | `./code.txt` | local auth-response file |
| `hf_repo_id` / `hf_token` / `encryption_key` | from env | explicit overrides |
| `hf_repo_type` | `dataset` | HuggingFace repo type |
| `local_client_secret_path` | `None` | extra path checked for a client secret |
| `scopes` | upload + manage | OAuth scopes |

### Package layout

One responsibility per module:

```
youtube_auto_pub/
├── config.py         # settings dataclass (env-first)
├── notifier.py       # alert dispatch (ntfy + email) with dedupe
├── token_manager.py  # encrypted credential storage on HuggingFace
├── credentials.py    # client-secret resolution, token load/refresh
├── uploader.py       # YouTube API: service, upload, thumbnail, end screen
└── auth/
    ├── flow.py         # consent URL → code exchange → token persistence
    ├── receivers.py    # response paths: local file / ntfy reply / HF upload
    ├── instructions.py # human-facing re-auth message
    └── cli.py          # python -m youtube_auto_pub.auth
```

## License

MIT
