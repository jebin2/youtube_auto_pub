"""
Google OAuth Automator for browser-based authentication.

Provides automated browser interaction for Google OAuth2 flows,
including handling 2-factor authentication and account selection.
"""

import getpass
from typing import Optional, Tuple

from youtube_auto_pub.config import YouTubeConfig

# browser_manager is optional - allows manual auth if not available
try:
    from browser_manager import BrowserManager
    from browser_manager.browser_config import BrowserConfig
    HAS_BROWSER_MANAGER = True
except ImportError:
    HAS_BROWSER_MANAGER = False


class GoogleOAuthAutomator:
    """Automates Google OAuth2 authentication flow via browser.
    
    This class handles:
    - Opening OAuth URLs in a browser
    - Filling in email/password credentials
    - Handling 2-Step Verification prompts
    - Account selection for multi-account users
    - OAuth consent confirmation
    
    Credentials are obtained via (in priority order):
    1. Constructor parameters
    2. Environment variables (GOOGLE_EMAIL, GOOGLE_PASSWORD)
    3. Interactive user prompt
    
    Example:
        config = YouTubeConfig(browser_executable="/usr/bin/chrome")
        automator = GoogleOAuthAutomator(config=config)
        automator.authorize_oauth("https://accounts.google.com/o/oauth2/auth?...")
    """
    
    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        config: Optional[YouTubeConfig] = None
    ):
        """Initialize OAuth automator.
        
        Args:
            email: Google account email (optional, can use config or prompt)
            password: Google account password or app password (optional)
            config: YouTubeConfig instance for browser settings and credentials
        """
        self.config = config or YouTubeConfig()
        # Priority: constructor params > config values
        self.email = email or self.config.google_email
        self.password = password or self.config.google_password
        self.auth_code = None
        self.callback_url = None
        
    def get_credentials(self) -> Tuple[str, str]:
        """Get email and password using two-tier approach.
        
        Priority:
        1. From object instance (constructor parameters)
        2. Prompt user for input
        
        Returns:
            Tuple of (email, password)
            
        Raises:
            ValueError: If credentials cannot be obtained
        """
        email = self.email
        password = self.password
        
        # Tier 1: Check if credentials were provided in constructor
        if email and password:
            print("[OAuth] Using credentials from object instance")
            return email, password
        
        # Tier 2: Prompt user for missing credentials
        print("[OAuth] Credentials not found in instance, prompting user...")
        
        if not email:
            email = input("Enter your Google email: ").strip()
            
        if not password:
            password = getpass.getpass("Enter your Google password (or app password): ")
        
        if not email or not password:
            raise ValueError("Email and password are required for OAuth automation")
            
        print("[OAuth] Using credentials from user input")
        return email, password

    def authorize_oauth(self, auth_url: str) -> bool:
        """Automate OAuth authorization flow via browser.
        
        Args:
            auth_url: The OAuth authorization URL to open
            
        Returns:
            True if authorization was successful
            
        Raises:
            ValueError: If browser_manager is not available or authorization fails
            ImportError: If browser_manager package is not installed
        """
        if not HAS_BROWSER_MANAGER:
            raise ImportError(
                "browser_manager package is required for OAuth automation. "
                "Install with: pip install browser-manager"
            )
        
        try:
            browser_config = BrowserConfig()
            browser_config.use_neko = not self.config.is_docker and self.config.has_display
            browser_config.url = auth_url
            browser_config.docker_name = self.config.docker_name
            browser_config.browser_executable = self.config.browser_executable
            browser_config.headless = False
            browser_config.user_data_dir = self.config.browser_profile_path
            browser_config.host_network = self.config.host_network
            
            with BrowserManager(browser_config) as page:
                page.wait_for_timeout(2000)
                
                heading_element = page.query_selector("#headingText")
                if heading_element and heading_element.text_content() != "Choose your account or a brand account":
                    email, password = self.get_credentials()

                    page.wait_for_timeout(2000)
                    
                    # Wait for email input and enter email
                    print("[OAuth] Looking for email input...")
                    email_selector = '#identifierId'
                    page.wait_for_selector(email_selector)
                    page.fill(email_selector, email)
                    
                    # Click next button
                    next_button = '#identifierNext'
                    page.wait_for_selector(next_button)
                    page.click(next_button)
                    
                    # Wait for password input and enter password
                    print("[OAuth] Looking for password input...")
                    password_selector = 'input[type="password"]'
                    page.wait_for_selector(password_selector)
                    page.fill(password_selector, password)
                    
                    # Click next/sign in button
                    signin_button = '#passwordNext'
                    page.wait_for_selector(signin_button)
                    page.click(signin_button)

                    # Wait for 2-Step Verification
                    self._wait_for_2fa(page)
                    
                    # Wait for account selection
                    self._wait_for_account_selection(page)

                self._handle_account_selection_and_continue(page)
                return True
                
        except Exception as e:
            raise ValueError(f"Error during authorization: {e}")

    def _wait_for_2fa(self, page) -> None:
        """Wait for and handle 2-Step Verification if present."""
        import time
        max_attempts = 60  # 5 minutes max
        for _ in range(max_attempts):
            try:
                heading = page.query_selector("#headingText")
                if heading and heading.text_content() == "2-Step Verification":
                    checkbox = page.query_selector('input[type="checkbox"]')
                    if checkbox:
                        checkbox.uncheck()
                    print("[OAuth] Waiting for 2-Step Verification completion...")
                    time.sleep(5)
                    return
            except Exception:
                pass
            time.sleep(5)

    def _wait_for_account_selection(self, page) -> None:
        """Wait for account selection screen."""
        import time
        max_attempts = 60
        for _ in range(max_attempts):
            try:
                heading = page.query_selector("#headingText")
                if heading and heading.text_content() == "Choose your account or a brand account":
                    print("[OAuth] Account selection screen detected")
                    time.sleep(5)
                    return
            except Exception:
                pass
            time.sleep(5)

    def _handle_account_selection_and_continue(self, page) -> bool:
        """Handle account selection and consent screens.
        
        Args:
            page: Browser page object
            
        Returns:
            True if successful
        """
        import time
        
        buttons = page.query_selector_all("button")
        
        for button in buttons:
            data_destination = button.get_attribute("data-destination-info")
            if data_destination and "Choosing an account will redirect you to" in data_destination:
                button_text = button.inner_text()
                
                # Find matching account in form
                accounts = page.query_selector_all("form li")
                for account in accounts:
                    account_text = account.inner_text()
                    if button_text in account_text:
                        clickable_div = account.query_selector("div")
                        if clickable_div:
                            print(f"[OAuth] Found account div: {clickable_div}")
                            clickable_div.focus()
                            time.sleep(1)
                            clickable_div.click(force=True)
                            time.sleep(10)
                            break
                break

        # Handle sequence of Continue screens and Consent screen
        # We loop to handle variable number of "Continue" intermediate pages
        max_attempts = 10
        for i in range(max_attempts):
            print(f"[OAuth] Page interaction loop {i+1}/{max_attempts}")
            time.sleep(10) # Give page time to settle

            # 1. Check for Checkbox inside form (Consent Page)
            # User reported "Select all" label might be missing, so we check first checkbox in form
            form_checkbox = page.query_selector('form input[type="checkbox"]')
            if form_checkbox:
                print("[OAuth] Found checkbox in form (Consent Page)")
                
                if not form_checkbox.is_checked():
                     print("[OAuth] Checking checkbox")
                     form_checkbox.click(force=True)
                     time.sleep(1)
                
                # Now click Continue on this page to finish
                continue_buttons = page.query_selector_all("button")
                for button in continue_buttons:
                    if button.inner_text() == "Continue":
                        print("[OAuth] Clicking final Continue")
                        
                        # Use request interception to capture the URL even if navigation fails
                        # Register BEFORE clicking to ensure we catch it
                        final_url = [None]
                        def handle_request(request):
                            print(f"[OAuth] Intercepted request to: {request.url}")
                            if "code=" in request.url and "localhost" in request.url:
                                print(f"[OAuth] Intercepted request to: {request.url}")
                                final_url[0] = request.url

                        page.on("request", handle_request)
                        
                        # Click the button which triggers the r1edirect
                        button.click(force=True)
                        time.sleep(5) # Wait for navigation attempt
                        
                        # Wait for the request to happen
                        start_time = time.time()
                        while time.time() - start_time < 60:
                            if final_url[0]:
                                break
                            
                            # Check page.url as fallback
                            if "code=" in page.url or "localhost" in page.url:
                                final_url[0] = page.url
                                break
                                
                            time.sleep(1)

                        page.remove_listener("request", handle_request)
                        
                        if final_url[0]:
                            print(f"[OAuth] Final URL captured: {final_url[0]}")
                            with open(self.config.authorization_code_path, 'w') as f:
                                f.write(final_url[0])
                            print(f"[OAuth] Written URL to {self.config.authorization_code_path}")
                            return True
                        else:
                            print("[OAuth] Failed to capture final URL in time")
                            return False
            
            # 2. Check for "Continue" button (Intermediate Page)
            found_continue = False
            continue_buttons = page.query_selector_all("button")
            for button in continue_buttons:
                if button.inner_text() == "Continue":
                    print(f"[OAuth] Found intermediate Continue button")
                    button.click(force=True)
                    found_continue = True
                    time.sleep(2) # Wait for navigation
                    break
            
            if found_continue:
                continue

            # If neither found, wait and retry
            print("[OAuth] No actionable elements found, waiting...")
            time.sleep(2)
            
        print("[OAuth] Failed to complete OAuth flow within limit")
        return False
