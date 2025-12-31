"""
Configuration module for YouTube Auto Publisher.

Provides a dataclass-based configuration that replaces hardcoded paths
and environment-specific settings.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class YouTubeConfig:
    """Configuration for YouTube Auto Publisher utilities.
    
    All paths and settings that were previously hardcoded in custom_env
    are now configurable through this dataclass.
    
    Attributes:
        encrypt_path: Directory for encrypted credential files
        authorization_code_path: File path for OAuth authorization code
        browser_executable: Path to browser executable (None for default)
        browser_profile_path: Directory for browser profile persistence
        is_docker: Whether running inside Docker container
        has_display: Whether a display is available
        headless_mode: Whether to run browser in headless mode
        hf_repo_id: HuggingFace Hub repository ID for token storage
        hf_repo_type: HuggingFace Hub repository type
        hf_token: HuggingFace Hub API token (from env if not provided)
        encryption_key: Fernet encryption key for credentials
        docker_name: Name for Docker container (used by browser_manager)
        host_network: Whether to use host network in Docker
        project_path: Project root path for finding local client secrets
    """
    encrypt_path: str = "./encrypt"
    authorization_code_path: str = "./code.txt"
    browser_executable: Optional[str] = None
    browser_profile_path: str = field(
        default_factory=lambda: os.path.abspath(
            os.path.expanduser("~/.youtube_auto_pub_browser_profile")
        )
    )
    is_docker: bool = False
    has_display: bool = True
    headless_mode: bool = field(default=None)  # Will be computed if None
    hf_repo_id: str = "jebin2/Data"
    hf_repo_type: str = "dataset"
    hf_token: Optional[str] = None
    encryption_key: Union[str, bytes, None] = None
    docker_name: str = "youtube_auto_pub"
    host_network: bool = False
    google_email: Optional[str] = None
    google_password: Optional[str] = None
    project_path: Optional[str] = None

    
    def __post_init__(self):
        """Compute derived values after initialization."""
        if self.headless_mode is None:
            self.headless_mode = self.is_docker or not self.has_display


# Default YouTube API scopes
YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/userinfo.email'
]
