# YouTube Auto Publisher

A standalone Python package for YouTube API automation with encrypted credential management and browser-based OAuth.

## Features

- **YouTubeUploader**: Complete video upload with thumbnails, resumable uploads, and progress tracking
- **TokenManager**: Encrypted credential storage via HuggingFace Hub using Fernet encryption
- **GoogleOAuthAutomator**: Automated browser-based OAuth2 authentication with 2FA support
- **YouTubeConfig**: Fully configurable settings via dataclass

## Installation

```bash
pip install git+https://github.com/jebin2/youtube_auto_pub.git
```

## Quick Start

```python
from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata

# Configure
config = YouTubeConfig(
    encrypt_path="./my_credentials",
    hf_repo_id="username/my-tokens",
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

The `YouTubeConfig` dataclass accepts:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `encrypt_path` | `"./encrypt"` | Directory for encrypted credentials |
| `authorization_code_path` | `"./code.txt"` | OAuth code file for headless mode |
| `browser_executable` | `None` | Browser path (None = system default) |
| `browser_profile_path` | `~/.youtube_auto_pub_browser_profile` | Browser profile directory |
| `is_docker` | Auto-detect | Running in Docker container |
| `has_display` | Auto-detect | Display available |
| `headless_mode` | Auto-compute | Run browser headless |
| `hf_repo_id` | `"jebin2/Data"` | HuggingFace repo for tokens |
| `hf_token` | From `HF_TOKEN` env | HuggingFace API token |
| `encryption_key` | From `ENCRYPT_KEY` env | Fernet encryption key |

## Environment Variables

```bash
export HF_TOKEN="hf_your_huggingface_token"
export ENCRYPT_KEY="your-fernet-encryption-key"

# Optional for OAuth automation
export GOOGLE_EMAIL="your@gmail.com"
export GOOGLE_PASSWORD="your_app_password"
```

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
from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata
import custom_env  # Your project's config

config = YouTubeConfig(
    encrypt_path=custom_env.ENCRYPT_PATH,
    browser_executable=custom_env.BROWSER_EXECUTABLE,
    browser_profile_path=custom_env.BROWSER_PROFILE,
    is_docker=custom_env.IS_DOCKER,
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
