"""
YouTube Auto Publisher - unattended YouTube uploads with encrypted
credential storage and notification-based OAuth.

Modules (one responsibility each):
- config: settings dataclass
- notifier: alert dispatch (ntfy push + email) with duplicate suppression
- token_manager: encrypted credential storage on HuggingFace Hub
- credentials: client-secret resolution, token loading and refresh
- auth: OAuth flows and the ways an auth response reaches the pipeline
- uploader: YouTube API operations (service, upload, thumbnail, end screen)
"""
from youtube_auto_pub.config import YouTubeConfig, YOUTUBE_SCOPES
from youtube_auto_pub.notifier import Notifier
from youtube_auto_pub.token_manager import TokenManager
from youtube_auto_pub.auth import (
    run_code_flow,
    run_local_server_flow,
    process_auth,
    process_auth_via_code,
)
from youtube_auto_pub.uploader import YouTubeUploader, VideoMetadata

__version__ = "0.4.0"
__all__ = [
    "YouTubeConfig",
    "YOUTUBE_SCOPES",
    "TokenManager",
    "Notifier",
    "YouTubeUploader",
    "VideoMetadata",
    "run_code_flow",
    "run_local_server_flow",
    "process_auth",
    "process_auth_via_code",
]
