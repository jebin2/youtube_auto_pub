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
