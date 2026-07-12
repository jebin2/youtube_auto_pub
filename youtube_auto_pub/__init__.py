"""
YouTube Auto Publisher - unattended YouTube uploads with encrypted
credential storage and notification-based OAuth.

Minimal usage (credentials from HF_TOKEN / HF_YT_CRED_REPO_ID / ENCRYPT_KEY
environment variables):

    from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata

    uploader = YouTubeUploader(YouTubeConfig())
    service = uploader.get_service()
    uploader.upload_video(service, "video.mp4", VideoMetadata(title="Hi"))
"""
from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.notifier import Notifier
from youtube_auto_pub.token_manager import TokenManager
from youtube_auto_pub.uploader import YouTubeUploader, VideoMetadata

__version__ = "1.0.0"
__all__ = [
    "YouTubeConfig",
    "Notifier",
    "TokenManager",
    "YouTubeUploader",
    "VideoMetadata",
]
