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

    Attributes:
        encrypt_path: Directory for encrypted credential files
        authorization_code_path: File path for OAuth authorization code
        hf_repo_id: HuggingFace Hub repository ID for token storage
        hf_repo_type: HuggingFace Hub repository type
        hf_token: HuggingFace Hub API token (from env if not provided)
        encryption_key: Fernet encryption key for credentials
        project_path: Project root path for finding local client secrets
        local_client_secret_path: Explicit path to a local client secret file
        client_secret_filename: Name of the client secret file
        token_filename: Name of the token file
        scopes: OAuth scopes to request
    """
    encrypt_path: str = "./encrypt"
    authorization_code_path: str = "./code.txt"
    hf_repo_id: str = "jebin2/Data"
    hf_repo_type: str = "dataset"
    hf_token: Optional[str] = None
    encryption_key: Union[str, bytes, None] = None
    project_path: Optional[str] = None
    local_client_secret_path: Optional[str] = None
    client_secret_filename: str = None
    token_filename: str = None
    scopes: List[str] = field(default_factory=lambda: [
        'https://www.googleapis.com/auth/youtube.upload',
        'https://www.googleapis.com/auth/youtube',
        'https://www.googleapis.com/auth/youtube.force-ssl',
        'https://www.googleapis.com/auth/userinfo.email'
    ])

    @property
    def client_id_path(self) -> str:
        """Get the full path to the client secret file."""
        return os.path.join(self.encrypt_path, self.client_secret_filename)

    @property
    def token_file_path(self) -> str:
        """Get the full path to the token file."""
        return os.path.join(self.encrypt_path, self.token_filename)


# Default YouTube API scopes
YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/userinfo.email'
]
