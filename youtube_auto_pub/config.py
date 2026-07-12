"""
Configuration for YouTube Auto Publisher.

Env-first: every credential setting falls back to an environment variable,
so `YouTubeConfig()` with no arguments works for the common case:

    HF_YT_CRED_REPO_ID (or HF_REPO_ID) -> hf_repo_id
    HF_TOKEN                           -> hf_token
    ENCRYPT_KEY                        -> encryption_key
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Union

DEFAULT_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/userinfo.email',
]


@dataclass
class YouTubeConfig:
    """Settings for credential storage and the OAuth flow.

    Attributes:
        client_secret_filename: Name of the OAuth client secret file
        token_filename: Name of the token file
        encrypt_path: Working directory for (de)crypted credential files
        authorization_code_path: Local file polled for an auth response
        hf_repo_id: HuggingFace repo for encrypted credentials (env fallback)
        hf_repo_type: HuggingFace repo type
        hf_token: HuggingFace API token (env fallback)
        encryption_key: Fernet key, str or bytes (env fallback)
        local_client_secret_path: Explicit path to a local client secret
        scopes: OAuth scopes to request
    """
    client_secret_filename: str = "ytcredentials.json"
    token_filename: str = "yttoken.json"
    encrypt_path: str = "./encrypt"
    authorization_code_path: str = "./code.txt"
    hf_repo_id: Optional[str] = None
    hf_repo_type: str = "dataset"
    hf_token: Optional[str] = None
    encryption_key: Union[str, bytes, None] = None
    local_client_secret_path: Optional[str] = None
    scopes: List[str] = field(default_factory=lambda: list(DEFAULT_SCOPES))

    def __post_init__(self):
        self.hf_repo_id = self.hf_repo_id or os.getenv("HF_YT_CRED_REPO_ID") or os.getenv("HF_REPO_ID")
        self.hf_token = self.hf_token or os.getenv("HF_TOKEN")
        self.encryption_key = self.encryption_key or os.getenv("ENCRYPT_KEY")

    @property
    def client_id_path(self) -> str:
        """Full path to the client secret file."""
        return os.path.join(self.encrypt_path, self.client_secret_filename)

    @property
    def token_file_path(self) -> str:
        """Full path to the token file."""
        return os.path.join(self.encrypt_path, self.token_filename)
