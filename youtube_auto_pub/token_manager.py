"""
Token Manager for encrypted credential storage via HuggingFace Hub.

Provides functionality to:
- Encrypt and upload credential files to HuggingFace Hub
- Download and decrypt credential files from HuggingFace Hub
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional

from huggingface_hub import hf_hub_download, HfApi
from cryptography.fernet import Fernet

from youtube_auto_pub.config import YouTubeConfig


class TokenManager:
    """Manages encrypted credential storage via HuggingFace Hub.
    
    This class handles:
    - Encrypting local credential files using Fernet encryption
    - Uploading encrypted files to a HuggingFace Hub repository
    - Downloading encrypted files from HuggingFace Hub
    - Decrypting downloaded files for local use
    
    Example:
        config = YouTubeConfig(
            encrypt_path="./my_encrypt",
            hf_repo_id="username/repo",
            hf_token="hf_xxx",
            encryption_key="your-fernet-key"
        )
        tm = TokenManager(config)
        
        # Download and decrypt a token file
        local_path = tm.download_and_decrypt("yttoken.json")
        
        # Encrypt and upload token files
        tm.encrypt_and_upload(["yttoken.json", "ytcredentials.json"])
    """
    
    def __init__(self, config: Optional[YouTubeConfig] = None):
        """Initialize TokenManager with configuration.
        
        Args:
            config: YouTubeConfig instance. If None, uses default config.
        """
        self.config = config or YouTubeConfig()
        
        # Clean up existing encrypt directory
        if self._dir_exists(self.config.encrypt_path):
            if self.config.clear_encrypt_dir:
                self._remove_directory(self.config.encrypt_path)
        
        self._create_directory(self.config.encrypt_path)
        
        if not self.config.encryption_key:
            raise ValueError("encryption_key is required in config or ENCRYPT_KEY env var")
        
        self._encryption_key = self.config.encryption_key.encode() if isinstance(
            self.config.encryption_key, str
        ) else self.config.encryption_key

    def encrypt_and_upload(self, local_file_paths: List[str]) -> None:
        """Encrypt local files and upload to HuggingFace Hub.
        
        Args:
            local_file_paths: List of local file paths to encrypt and upload.
        """
        fernet = Fernet(self._encryption_key)
        
        for path in local_file_paths:
            with open(path, 'r') as f:
                data = fernet.encrypt(f.read().encode())
            
            new_path = f'{self.config.encrypt_path}/{Path(path).name}'
            
            with open(new_path, "wb") as f:
                f.write(data)
        
        api = HfApi(token=self.config.hf_token)
        api.upload_folder(
            folder_path=self.config.encrypt_path,
            repo_id=self.config.hf_repo_id,
            repo_type=self.config.hf_repo_type,
            commit_message="Upload encrypted credentials"
        )
        print(f"[TokenManager] Encrypted and uploaded {len(local_file_paths)} files successfully.")

    def download_and_decrypt(self, file_name: str) -> str:
        """Download encrypted file from HuggingFace Hub and decrypt it.
        
        Args:
            file_name: Name of the file to download (not full path).
            
        Returns:
            Local file path of the decrypted file (may not exist if file
            was not found on HuggingFace Hub - first time setup).
        """
        local_file_path = os.path.join(self.config.encrypt_path, file_name)
        
        try:
            downloaded_path = hf_hub_download(
                repo_id=self.config.hf_repo_id,
                filename=file_name,
                repo_type=self.config.hf_repo_type,
                token=self.config.hf_token,
                local_dir=self.config.encrypt_path
            )
            
            fernet = Fernet(self._encryption_key)
            with open(downloaded_path, "rb") as f:
                data = fernet.decrypt(f.read()).decode("utf-8")
            
            with open(downloaded_path, "w") as f:
                f.write(data)
            
            print(f"[TokenManager] Downloaded and decrypted: {file_name}")
            return downloaded_path
        except Exception as e:
            # File doesn't exist on HuggingFace Hub (first-time setup)
            print(f"[TokenManager] File not found on HuggingFace Hub: {file_name} ({e})")
            print(f"[TokenManager] This is expected for first-time setup. Returning local path: {local_file_path}")
            return local_file_path

    @staticmethod
    def _dir_exists(path: str) -> bool:
        """Check if directory exists."""
        try:
            return Path(path).is_dir()
        except Exception:
            return False

    @staticmethod
    def _remove_directory(path: str) -> None:
        """Remove directory and all contents."""
        try:
            if Path(path).exists():
                shutil.rmtree(path)
        except Exception as e:
            print(f"[TokenManager] Warning: Failed to delete {path}: {e}")

    @staticmethod
    def _create_directory(path: str) -> None:
        """Create directory if it doesn't exist."""
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"[TokenManager] Error creating directory {path}: {e}")


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) > 1:
        files_to_upload = sys.argv[1:]
        tm = TokenManager()
        tm.encrypt_and_upload(files_to_upload)
    else:
        print("Usage: python token_manager.py <file1> <file2> ...")
