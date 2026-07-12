"""
YouTube Auto Publisher - A standalone package for YouTube API automation.

Provides utilities for:
- Token management with HuggingFace Hub encryption
- Notification-based OAuth authorization (no browser automation)
- YouTube video uploading
"""
from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.token_manager import TokenManager
from youtube_auto_pub.notifier import Notifier
from youtube_auto_pub.auth_worker import process_auth, process_auth_via_code
from youtube_auto_pub.uploader import YouTubeUploader, VideoMetadata

__version__ = "0.3.0"
__all__ = [
    "YouTubeConfig",
    "TokenManager",
    "Notifier",
    "process_auth",
    "process_auth_via_code",
    "YouTubeUploader",
    "VideoMetadata",
]
