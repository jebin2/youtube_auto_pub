"""
Encrypted credential storage on HuggingFace Hub.

Files are Fernet-encrypted before upload and decrypted after download.
The (private) repository is created automatically on first upload.
"""

import os
import shutil
from pathlib import Path
from typing import List

from huggingface_hub import hf_hub_download, HfApi
from cryptography.fernet import Fernet

from youtube_auto_pub.config import YouTubeConfig


class TokenManager:
    """Encrypt/decrypt credential files and sync them with HuggingFace Hub."""

    def __init__(self, config: YouTubeConfig):
        self.config = config

        # Start from a clean working directory (kept, not removed - it may
        # be a mount point).
        self._create_directory(self.config.encrypt_path)
        self._empty_directory(self.config.encrypt_path)

        if not self.config.encryption_key:
            raise ValueError("encryption_key is required in config or ENCRYPT_KEY env var")

        self._encryption_key = (
            self.config.encryption_key.encode()
            if isinstance(self.config.encryption_key, str)
            else self.config.encryption_key
        )

    def encrypt_and_upload(self, local_file_paths: List[str]) -> None:
        """Encrypt local files and upload them to HuggingFace Hub."""
        fernet = Fernet(self._encryption_key)

        for path in local_file_paths:
            if not os.path.exists(path):
                print(f"[TokenManager] Skipping missing file: {path}")
                continue
            with open(path, 'r') as f:
                data = fernet.encrypt(f.read().encode())
            with open(f'{self.config.encrypt_path}/{Path(path).name}', "wb") as f:
                f.write(data)

        api = HfApi(token=self.config.hf_token)
        # First-time setup: create the (private) repo if it does not exist yet.
        api.create_repo(
            repo_id=self.config.hf_repo_id,
            repo_type=self.config.hf_repo_type,
            private=True,
            exist_ok=True,
        )
        api.upload_folder(
            folder_path=self.config.encrypt_path,
            repo_id=self.config.hf_repo_id,
            repo_type=self.config.hf_repo_type,
            commit_message="Upload encrypted credentials",
            ignore_patterns=[".cache*", "*.lock"],
        )
        print(f"[TokenManager] Encrypted and uploaded {len(local_file_paths)} files successfully.")

    def download_and_decrypt(self, file_name: str) -> str:
        """Download an encrypted file from HuggingFace Hub and decrypt it.

        Returns:
            Local path of the decrypted file. When the file does not exist on
            the Hub yet (first-time setup) the path is returned anyway and
            simply does not exist locally.
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
            print(f"[TokenManager] File not found on HuggingFace Hub: {file_name} ({e})")
            print(f"[TokenManager] This is expected for first-time setup. Returning local path: {local_file_path}")
            return local_file_path

    @staticmethod
    def _create_directory(path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"[TokenManager] Error creating directory {path}: {e}")

    @staticmethod
    def _empty_directory(path: str) -> None:
        """Empty a directory without removing the directory itself."""
        try:
            if not os.path.isdir(path):
                return
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                try:
                    if os.path.isdir(item_path) and not os.path.islink(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                except Exception as e:
                    print(f"[TokenManager] Warning: Failed to delete item {item_path}: {e}")
        except Exception as e:
            print(f"[TokenManager] Warning: Failed to empty directory {path}: {e}")
