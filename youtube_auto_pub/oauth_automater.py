"""
Google OAuth Automator — thin wrapper around jebin_lib.GoogleLoginAutomator.
"""

import os
from typing import Optional
from youtube_auto_pub.config import YouTubeConfig
from browser_manager.browser_config import BrowserConfig
from jebin_lib import GoogleLoginAutomator


class GoogleOAuthAutomator:
    """Automates Google OAuth2 authentication flow via browser.

    Delegates all logic to jebin_lib.GoogleLoginAutomator.
    """

    def __init__(
        self,
        config: YouTubeConfig,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.config = config
        self._automator = GoogleLoginAutomator(
            email=email or config.google_email,
            password=password or config.google_password,
            browser_profile_path=config.browser_profile_path,
            authorization_code_path=config.authorization_code_path,
            docker_name=config.docker_name,
            hf_screenshot_repo_id=os.getenv("GOOGLE_SCREENSHOT_HF_REPO_ID", "jebin2/google"),
        )

    def authorize_oauth(self, auth_url: str) -> bool:
        """Automate OAuth authorization flow via browser.

        Args:
            auth_url: The OAuth authorization URL to open

        Returns:
            True if authorization was successful
        """
        browser_config = BrowserConfig()
        browser_config.use_neko = not self.config.is_docker and self.config.has_display
        browser_config.docker_name = self.config.docker_name
        browser_config.browser_executable = self.config.browser_executable
        browser_config.headless = False
        browser_config.user_data_dir = self.config.browser_profile_path
        browser_config.host_network = self.config.host_network

        return self._automator.authorize_oauth(auth_url, browser_config)
