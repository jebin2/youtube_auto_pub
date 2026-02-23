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
        config: YouTubeConfig,
        email: Optional[str] = None,
        password: Optional[str] = None
    ):
        """Initialize OAuth automator.
        
        Args:
            config: YouTubeConfig instance for browser settings and credentials
            email: Google account email (optional, can use config or prompt)
            password: Google account password or app password (optional)
        """
        self.config = config
        # Priority: constructor params > config values
        self.email = email or self.config.google_email
        self.password = password or self.config.google_password
        self.auth_code = None
        self.callback_url = None
        self.browser_config = None  # Will be set during authorize_oauth
        
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
            # Clear session cookies so we always get a fresh email/password login.
            # Cached sessions can be expired/invalid, causing Google to show
            # "Couldn't sign you in" (authuser=unknown). Clearing forces a clean flow.
            import os
            cookies_path = os.path.join(self.config.browser_profile_path, "Default", "Cookies")
            if os.path.exists(cookies_path):
                try:
                    os.remove(cookies_path)
                    print(f"[OAuth] Cleared session cookies at {cookies_path}")
                except Exception as e:
                    print(f"[OAuth] Could not clear cookies: {e}")

            browser_config = BrowserConfig()
            browser_config.use_neko = not self.config.is_docker and self.config.has_display
            browser_config.url = auth_url
            browser_config.docker_name = self.config.docker_name
            browser_config.browser_executable = self.config.browser_executable
            browser_config.headless = False
            browser_config.user_data_dir = self.config.browser_profile_path
            browser_config.host_network = self.config.host_network
            self.browser_config = browser_config  # Store for use in _capture_url_from_address_bar

            with BrowserManager(browser_config) as page:
                page.wait_for_timeout(2000)

                heading_element = page.query_selector("#headingText")
                heading_text = heading_element.text_content() if heading_element else ""
                print(f"[OAuth] Initial page heading: '{heading_text}'")

                if heading_text != "Choose your account or a brand account":
                    email, password = self.get_credentials()
                    page.wait_for_timeout(2000)

                    # Probe for email input — short timeout distinguishes fresh login
                    # from cached-session account chooser (which has no #identifierId)
                    email_selector = '#identifierId'
                    email_input_found = False
                    try:
                        page.wait_for_selector(email_selector, timeout=5000)
                        email_input_found = True
                    except Exception:
                        pass

                    if email_input_found:
                        print("[OAuth] Fresh login — entering email...")
                        page.fill(email_selector, email)

                        next_button = '#identifierNext'
                        page.wait_for_selector(next_button)
                        page.click(next_button)

                        print("[OAuth] Looking for password input...")
                        password_selector = 'input[type="password"]'
                        page.wait_for_selector(password_selector)
                        page.fill(password_selector, password)

                        signin_button = '#passwordNext'
                        page.wait_for_selector(signin_button)
                        page.click(signin_button)

                        # Wait for 2-Step Verification
                        self._wait_for_2fa(page)

                        # Wait for account selection
                        self._wait_for_account_selection(page)
                    else:
                        # Cached session: account chooser shown — click matching account
                        print(f"[OAuth] Cached session detected — clicking account '{email}'...")
                        self._click_account_from_chooser(page, email)

                self._handle_account_selection_and_continue(page)
                return True
                
        except Exception as e:
            raise ValueError(f"Error during authorization: {e}")

    def _click_account_from_chooser(self, page, email: str) -> bool:
        """Click the matching account from Google's account chooser (cached-session flow).

        Tries selectors commonly used by Google's account chooser UI.
        Falls back to clicking the first available account if no email match is found.
        """
        import time

        selectors = [
            f'[data-identifier="{email}"]',   # most reliable: exact email attribute
            f'[data-email="{email}"]',
        ]
        # Try exact-match selectors first
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    print(f"[OAuth] Clicking account via selector '{sel}'")
                    el.click(force=True)
                    time.sleep(3)
                    return True
            except Exception:
                pass

        # Fallback: iterate list items and match by text content
        for li_sel in ["ul li", "ol li", "li"]:
            try:
                items = page.query_selector_all(li_sel)
                for item in items:
                    try:
                        text = item.inner_text()
                        if email and email.lower() in text.lower():
                            print(f"[OAuth] Clicking account list item matching '{email}'")
                            item.click(force=True)
                            time.sleep(3)
                            return True
                    except Exception:
                        pass
            except Exception:
                pass

        # Last resort: click the first clickable account item
        for li_sel in ["ul li", "li"]:
            try:
                first = page.query_selector(li_sel)
                if first:
                    print(f"[OAuth] Clicking first account item (no email match found)")
                    first.click(force=True)
                    time.sleep(3)
                    return True
            except Exception:
                pass

        print("[OAuth] Could not find any account to click in chooser")
        return False

    def _wait_for_2fa(self, page) -> None:
        """Wait for and handle 2-Step Verification if present."""
        import time
        max_attempts = 60  # 5 minutes max
        for _ in range(max_attempts):
            try:
                heading = page.query_selector("#headingText")
                if heading and heading.text_content() == "2-Step Verification":
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

        def _playwright_url_has_code() -> str:
            """Check page.url directly via Playwright — fastest redirect detection."""
            try:
                url = page.url
                print(f"[OAuth][DEBUG] playwright page.url = {url[:120]}")
                if url and "code=" in url:
                    return url
            except Exception as e:
                print(f"[OAuth][DEBUG] playwright page.url error: {e}")
            return None

        def _save_url(url: str) -> bool:
            with open(self.config.authorization_code_path, 'w') as f:
                f.write(url)
            print(f"[OAuth] Written URL to {self.config.authorization_code_path}")
            return True

        def _check_redirect() -> str:
            """Return redirect URL if found via Playwright or CDP, else None."""
            url = _playwright_url_has_code()
            if url:
                return url
            captured = self._capture_url_from_address_bar()
            if captured and "code=" in captured:
                return captured
            return None

        def _dismiss_banners() -> bool:
            """Click 'Got it' / 'OK' / 'Dismiss' banners that may cover the page."""
            try:
                for b in page.query_selector_all("button"):
                    try:
                        btext = b.inner_text().strip().lower()
                        if btext in ("got it", "ok", "dismiss", "close"):
                            print(f"[OAuth] Dismissing banner: '{b.inner_text().strip()}'")
                            b.click(force=True)
                            time.sleep(2)
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
            return False

        def _click_brand_account_button() -> bool:
            """Click the first button with data-destination-info using multiple strategies."""
            try:
                for button in page.query_selector_all("button"):
                    data_destination = button.get_attribute("data-destination-info")
                    if data_destination and "Choosing an account will redirect you to" in data_destination:
                        btext = button.inner_text().strip()
                        print(f"[OAuth] Attempting to click brand account button: '{btext}'")

                        # DIAGNOSTIC: print outerHTML to understand DOM structure
                        try:
                            html = button.evaluate("el => el.outerHTML")
                            print(f"[OAuth][DIAG] button outerHTML: {html[:400]}")
                            parent_html = button.evaluate("el => el.parentElement ? el.parentElement.outerHTML.substring(0, 600) : 'NO PARENT'")
                            print(f"[OAuth][DIAG] parent outerHTML: {parent_html}")
                        except Exception as de:
                            print(f"[OAuth][DIAG] outerHTML error: {de}")

                        # Strategy 1: scroll into view + real mouse click at coordinates
                        try:
                            button.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            box = button.bounding_box()
                            if box:
                                x = box['x'] + box['width'] / 2
                                y = box['y'] + box['height'] / 2
                                # Verify what element is actually at these coordinates
                                try:
                                    elem_info = page.evaluate(
                                        f"() => {{ const el = document.elementFromPoint({x}, {y}); return el ? el.tagName + ' id=' + el.id + ' class=' + el.className : 'NONE'; }}"
                                    )
                                    print(f"[OAuth][DIAG] Element at ({x:.0f}, {y:.0f}): {elem_info}")
                                except Exception:
                                    pass
                                page.mouse.move(x, y)
                                time.sleep(0.3)
                                page.mouse.click(x, y)
                                print(f"[OAuth] Clicked '{btext}' via mouse at ({x:.0f}, {y:.0f})")
                                return True
                        except Exception as e1:
                            print(f"[OAuth] Strategy 1 (mouse) failed: {e1}")

                        # Strategy 2: JS eval click (bypasses pointer-events CSS)
                        try:
                            page.evaluate("(el) => el.click()", button)
                            print(f"[OAuth] Clicked '{btext}' via JS eval")
                            return True
                        except Exception as e2:
                            print(f"[OAuth] Strategy 2 (JS eval) failed: {e2}")

                        # Strategy 3: dispatch click event
                        try:
                            button.dispatch_event("click")
                            print(f"[OAuth] Clicked '{btext}' via dispatch_event")
                            return True
                        except Exception as e3:
                            print(f"[OAuth] Strategy 3 (dispatch_event) failed: {e3}")

                        # Strategy 4: force=True fallback
                        try:
                            button.click(force=True)
                            print(f"[OAuth] Clicked '{btext}' via force=True")
                            return True
                        except Exception as e4:
                            print(f"[OAuth] Strategy 4 (force) failed: {e4}")

                        # Strategy 5: keyboard focus + Enter
                        try:
                            button.focus()
                            time.sleep(0.3)
                            page.keyboard.press("Enter")
                            print(f"[OAuth] Clicked '{btext}' via keyboard Enter")
                            return True
                        except Exception as e5:
                            print(f"[OAuth] Strategy 5 (keyboard Enter) failed: {e5}")

                        # Strategy 6: click parent element via JS
                        try:
                            page.evaluate("(el) => el.parentElement && el.parentElement.click()", button)
                            print(f"[OAuth] Clicked '{btext}' parent via JS eval")
                            return True
                        except Exception as e6:
                            print(f"[OAuth] Strategy 6 (parent JS click) failed: {e6}")

                        break
            except Exception as e:
                print(f"[OAuth][DEBUG] brand button click error: {e}")
            return False

        def _dump_diagnostics():
            """Print concise page state for monitoring."""
            try:
                heading = page.query_selector("#headingText")
                print(f"[OAuth] Page heading: '{heading.text_content() if heading else 'none'}'")
            except Exception:
                pass

            try:
                all_buttons = page.query_selector_all("button")
                for b in all_buttons:
                    try:
                        btext = b.inner_text().strip()
                        bdata = b.get_attribute("data-destination-info") or ""
                        if btext or bdata:
                            print(f"[OAuth]   button='{btext}' has_destination={bool(bdata)}")
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                checkboxes = page.query_selector_all('form input[type="checkbox"]')
                if checkboxes:
                    print(f"[OAuth]   form checkboxes: {len(checkboxes)}")
            except Exception:
                pass

            # Print ALL li items to find where brand accounts are listed
            try:
                all_lis = page.query_selector_all("li")
                if all_lis:
                    print(f"[OAuth][DIAG] All li items ({len(all_lis)}):")
                    for li in all_lis:
                        try:
                            print(f"[OAuth][DIAG]   li: '{li.inner_text().strip()[:80]}'")
                        except Exception:
                            pass
            except Exception:
                pass

        # ── Initial brand account click ────────────────────────────────────
        if _click_brand_account_button():
            # Poll for redirect — navigation after mouse click can take several seconds
            for wait_sec in [3, 5, 7]:
                time.sleep(wait_sec)
                url = _check_redirect()
                if url:
                    return _save_url(url)
                print(f"[OAuth] Waiting for navigation after initial brand button click ({wait_sec}s)...")
        else:
            print("[OAuth] No brand account button found on initial scan")

        # ── Loop: handle Continue / consent screens ────────────────────────
        max_attempts = 15
        for i in range(max_attempts):
            print(f"[OAuth] Page interaction loop {i+1}/{max_attempts}")

            # Check for redirect FIRST — fastest exit
            url = _check_redirect()
            if url:
                return _save_url(url)

            time.sleep(5)  # Let page settle

            _dump_diagnostics()

            # Dismiss any "Got it" / info banners
            _dismiss_banners()

            # Re-check redirect after dismissing banner
            url = _check_redirect()
            if url:
                return _save_url(url)

            # ── a) Brand account button re-appeared ───────────────────────
            if _click_brand_account_button():
                # Wait longer — mouse click navigation can take time
                for wait_sec in [3, 5, 7]:
                    time.sleep(wait_sec)
                    url = _check_redirect()
                    if url:
                        return _save_url(url)
                    print(f"[OAuth] Waiting for navigation after brand button click ({wait_sec}s passed)...")
                # Button clicked but no redirect yet — loop will retry
                continue

            # ── b) Consent page: check all checkboxes, then Continue ───────
            form_checkboxes = page.query_selector_all('form input[type="checkbox"]')
            if form_checkboxes:
                print(f"[OAuth] Found {len(form_checkboxes)} checkbox(es) in form (Consent Page)")
                for cb in form_checkboxes:
                    try:
                        if not cb.is_checked():
                            print("[OAuth] Checking checkbox")
                            cb.click(force=True)
                            time.sleep(0.5)
                    except Exception as e:
                        print(f"[OAuth][DEBUG] checkbox click error: {e}")

            # ── c) Click any Continue button (case-insensitive) ───────────
            clicked_continue = False
            for button in page.query_selector_all("button"):
                try:
                    if button.inner_text().strip().lower() == "continue":
                        print("[OAuth] Clicking Continue button")
                        button.click(force=True)
                        clicked_continue = True
                        time.sleep(5)
                        url = _check_redirect()
                        if url:
                            return _save_url(url)
                        print("[OAuth] Continue clicked — not final redirect yet, looping...")
                        break
                except Exception:
                    pass

            if not clicked_continue and not form_checkboxes:
                print("[OAuth] No actionable elements found, waiting...")
                time.sleep(5)

        print("[OAuth] Failed to complete OAuth flow within limit")
        return False

    def _capture_url_from_address_bar(self) -> str:
        """Capture URL from browser using Chrome DevTools Protocol.
        
        Uses CDP endpoint to get the current page URL, which is more reliable
        than clipboard-based methods in Docker containers.
        
        Returns:
            The captured URL string, or None if capture failed
        """
        import subprocess
        import time
        import json
        
        docker_name = self.config.docker_name
        # Get CDP port from browser_config if available, otherwise use default
        cdp_port = 9224  # Default fallback
        if self.browser_config is not None:
            cdp_port = self.browser_config.debug_port
        
        # Method 1: Chrome DevTools Protocol (preferred - most reliable)
        try:
            import urllib.request
            cdp_url = f"http://localhost:{cdp_port}/json"
            with urllib.request.urlopen(cdp_url, timeout=5) as response:
                pages = json.loads(response.read().decode())
                if pages:
                    # Get URL from the first page
                    url = pages[0].get('url', '')
                    if url and not url.startswith('chrome://') and not url.startswith('chrome-error://'):
                        print(f"[OAuth] URL from CDP: {url}")
                        return url
                    else:
                        print(f"[OAuth] CDP returned non-useful URL: {url}")
        except Exception as e:
            print(f"[OAuth] CDP method failed: {e}")
        
        # Method 2: xdotool + xclip fallback
        try:
            # Focus address bar with Ctrl+L
            subprocess.run([
                'docker', 'exec', docker_name,
                'xdotool', 'key', 'ctrl+l'
            ], timeout=5, check=True)
            time.sleep(0.5)
            
            # Select all with Ctrl+A
            subprocess.run([
                'docker', 'exec', docker_name,
                'xdotool', 'key', 'ctrl+a'
            ], timeout=5, check=True)
            time.sleep(0.3)
            
            # Copy with Ctrl+C
            subprocess.run([
                'docker', 'exec', docker_name,
                'xdotool', 'key', 'ctrl+c'
            ], timeout=5, check=True)
            time.sleep(0.5)
            
            # Read clipboard using xclip inside the container
            result = subprocess.run([
                'docker', 'exec', docker_name,
                'xclip', '-selection', 'clipboard', '-o'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0 and result.stdout.strip():
                url = result.stdout.strip()
                print(f"[OAuth] URL from clipboard: {url}")
                return url
            else:
                print(f"[OAuth] xclip failed or empty: {result.stderr}")
                return None
            
        except subprocess.TimeoutExpired:
            print("[OAuth] xdotool command timed out")
            return None
        except subprocess.CalledProcessError as e:
            print(f"[OAuth] Command failed with exit status {e.returncode}")
            if e.stderr:
                print(f"[OAuth] Error output: {e.stderr}")
            return None
        except Exception as e:
            print(f"[OAuth] Error capturing URL: {e}")
            return None
