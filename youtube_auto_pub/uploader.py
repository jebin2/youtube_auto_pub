"""
YouTube Uploader for uploading videos to YouTube.

Provides a clean, configurable interface for:
- Authenticating with YouTube API
- Uploading videos with metadata
- Setting thumbnails
"""

import os
import json
import time
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

from youtube_auto_pub.config import YouTubeConfig
from youtube_auto_pub.notifier import Notifier
from youtube_auto_pub.token_manager import TokenManager


@dataclass
class VideoMetadata:
    """Metadata for a YouTube video upload.
    
    Attributes:
        title: Video title (max 100 characters)
        description: Video description
        tags: List of tags for the video
        category_id: YouTube category ID (e.g., "22" for People & Blogs)
        privacy_status: "public", "private", or "unlisted"
        made_for_kids: Whether the video is made for kids
        publish_at: ISO 8601 datetime string for scheduled publishing
    """
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    category_id: str = "22"  # People & Blogs
    privacy_status: str = "private"
    made_for_kids: bool = False
    publish_at: Optional[str] = None


class YouTubeUploader:
    """Upload videos to YouTube with automatic credential management.
    
    This class handles:
    - Loading and refreshing OAuth credentials
    - Uploading videos with resumable uploads
    - Setting video thumbnails
    - Managing multiple credential sets
    
    Example:
        config = YouTubeConfig(encrypt_path="./credentials")
        uploader = YouTubeUploader(config)
        
        # Get authenticated service
        service = uploader.get_service(
            token_path="yttoken.json",
            client_path="ytcredentials.json"
        )
        
        # Upload a video
        metadata = VideoMetadata(
            title="My Video",
            description="Video description",
            tags=["tag1", "tag2"]
        )
        video_id = uploader.upload_video(
            service=service,
            video_path="/path/to/video.mp4",
            metadata=metadata,
            thumbnail_path="/path/to/thumbnail.jpg"
        )
    """
    
    def __init__(self, config: YouTubeConfig):
        """Initialize YouTube uploader.
        
        Args:
            config: YouTubeConfig instance for credential paths
        """
        self.config = config
        self.token_manager = TokenManager(self.config)
        self.notifier = Notifier()
        self._services: dict = {}

    def _extract_client_id(self, client_path: str) -> Optional[str]:
        """Extract the client_id from a client_secrets.json file.
        
        Args:
            client_path: Path to client_secrets.json file
            
        Returns:
            The client_id string, or None if not found
        """
        try:
            if not os.path.exists(client_path):
                return None
            with open(client_path, 'r') as f:
                data = json.load(f)
            # Handle both "installed" and "web" client types
            for key in ['installed', 'web']:
                if key in data and 'client_id' in data[key]:
                    return data[key]['client_id']
            return None
        except Exception as e:
            print(f"[Uploader] Error extracting client_id: {e}")
            return None

    def _is_token_for_client(self, token_path: str, client_id: str) -> bool:
        """Check if the token was created for the given client_id.
        
        Args:
            token_path: Path to token.json file
            client_id: The expected client_id
            
        Returns:
            True if the token matches the client_id, False otherwise
        """
        try:
            if not os.path.exists(token_path):
                return True  # No token exists, so it's fine
            with open(token_path, 'r') as f:
                data = json.load(f)
            token_client_id = data.get('client_id')
            if token_client_id is None:
                # Old token format might not have client_id, assume it's invalid
                print("[Uploader] Token missing client_id field, will re-authenticate.")
                return False
            return token_client_id == client_id
        except Exception as e:
            print(f"[Uploader] Error checking token client_id: {e}")
            return False




    def get_service(
        self,
        cache_key: Optional[str] = None,
        skip_auth_flow: bool = False
    ) -> Any:
        """Get an authenticated YouTube API service.
        
        This method:
        1. Downloads encrypted credentials from HuggingFace Hub
        2. Loads/refreshes OAuth tokens
        3. Initiates auth flow if needed (unless skip_auth_flow=True)
        4. Returns an authenticated YouTube service
        
        Args:
            cache_key: Optional key to cache the service for reuse
            skip_auth_flow: If True, return None instead of triggering auth flow
            
        Returns:
            Authenticated YouTube API service object, or None if skip_auth_flow=True and no valid creds
        """
        scopes = self.config.scopes
        token_path = self.config.token_filename
        client_path = self.config.client_secret_filename
        
        # Return cached service if available
        if cache_key and cache_key in self._services:
            print(f"[Uploader] Using cached service for: {cache_key}")
            return self._services[cache_key]
        
        print("[Uploader] Checking for stored credentials...")
        
        # Download and decrypt credential files
        local_token_path = self.token_manager.download_and_decrypt(token_path)
        local_client_path = self.token_manager.download_and_decrypt(client_path)
        
        # Check for local client secrets override/update
        # Look for client secret in multiple locations:
        # 1. Current working directory
        # 2. Config's project_path (if set)
        # 3. /app directory (Docker mounted files)
        # 4. Absolute path if provided
        possible_local_paths = [client_path]
        
        # Add project_path based location if config has it
        if hasattr(self.config, 'project_path') and self.config.project_path:
            project_client_path = os.path.join(self.config.project_path, client_path)
            possible_local_paths.append(project_client_path)

        # Add explicitly provided local client secret path (highest priority)
        if hasattr(self.config, 'local_client_secret_path') and self.config.local_client_secret_path:
             possible_local_paths.append(self.config.local_client_secret_path)
        
        # Check /app directory for Docker mounted files
        app_client_path = os.path.join('/app', client_path)
        if app_client_path not in possible_local_paths:
            possible_local_paths.append(app_client_path)
        
        # Also check encrypt_path for the original file
        if self.config.encrypt_path:
            encrypt_client_path = os.path.join(self.config.encrypt_path, client_path)
            if encrypt_client_path != local_client_path:
                possible_local_paths.append(encrypt_client_path)
        
        # Try each possible location
        stored_id = self._extract_client_id(local_client_path)
        
        print(f"[Uploader DEBUG] CWD: {os.getcwd()}")
        print(f"[Uploader DEBUG] Target local_client_path: {local_client_path} (Exists: {os.path.exists(local_client_path)})")
        if os.path.exists(os.path.dirname(local_client_path)):
             print(f"[Uploader DEBUG] Contents of {os.path.dirname(local_client_path)}: {os.listdir(os.path.dirname(local_client_path))}")
        else:
             print(f"[Uploader DEBUG] Directory {os.path.dirname(local_client_path)} does not exist.")

        print(f"[Uploader DEBUG] Checking possible local paths for secret: {possible_local_paths}")

        for check_path in possible_local_paths:
            if os.path.exists(check_path) and os.path.abspath(check_path) != os.path.abspath(local_client_path):
                local_id = self._extract_client_id(check_path)
                
                # Copy local client secret if:
                # 1. No stored file exists (fresh start - stored_id is None), OR
                # 2. Client ID has changed (need re-auth)
                if local_id and (stored_id is None or local_id != stored_id):
                    if stored_id is None:
                        print(f"[Uploader] 📋 Using local client secret from '{check_path}' (fresh start)")
                    else:
                        print(f"[Uploader] 🔄 Detected local client secret update in '{check_path}'.")
                        print(f"[Uploader] New Client ID: ...{local_id[-10:] if local_id else 'None'}")
                        print(f"[Uploader] Old Client ID: ...{stored_id[-10:] if stored_id else 'None'}")
                        print("[Uploader] Overwriting cached secret and forcing re-authentication.")
                    
                    try:
                        # Ensure destination directory exists
                        os.makedirs(os.path.dirname(local_client_path), exist_ok=True)
                        # Overwrite the stored/decrypted file with the local one
                        shutil.copy(check_path, local_client_path)
                        
                        # Delete existing token to force re-auth (only if client changed)
                        if stored_id is not None and os.path.exists(local_token_path):
                            os.remove(local_token_path)
                            print(f"[Uploader] Deleted stale token: {local_token_path}")
                        
                        # Update stored_id for subsequent checks
                        stored_id = local_id
                        break  # Found and applied update, stop checking
                    except Exception as e:
                        print(f"[Uploader] Error updating local client secret: {e}")
        
        # Validate that token was created for the current client
        current_client_id = self._extract_client_id(local_client_path)
        if current_client_id:
            if not self._is_token_for_client(local_token_path, current_client_id):
                print("[Uploader] ⚠ Client secret has changed. Deleting old token to force re-authentication.")
                try:
                    if os.path.exists(local_token_path):
                        os.remove(local_token_path)
                        print(f"[Uploader] Deleted stale token: {local_token_path}")
                except Exception as e:
                    print(f"[Uploader] Error deleting token: {e}")
        
        creds = None
        
        # Load existing credentials
        if os.path.exists(local_token_path):
            try:
                creds = Credentials.from_authorized_user_file(local_token_path, scopes)
                print("[Uploader] Found existing credentials.")
            except Exception as e:
                print(f"[Uploader] Error loading credentials: {e}")

        # Refresh expired credentials.
        # Transient failures (network blips, 5xx from Google) are retried with
        # backoff and then raised so the caller's retry loop can try again
        # later - they must NOT trigger a full re-authentication.
        # Only a genuinely dead grant (revoked/expired refresh token) falls
        # through to the auth flow.
        if creds and creds.expired and creds.refresh_token:
            creds = self._refresh_with_retry(creds, local_token_path)

        # Run auth flow if needed
        if not creds or not creds.valid:
            if not creds or not creds.refresh_token:
                if skip_auth_flow:
                    print("[Uploader] No valid credentials. Skipping auth flow (skip_auth_flow=True).")
                    return None
                print("[Uploader] No valid credentials or refresh token. Initiating authentication flow.")
                try:
                    creds = self._run_auth_flow()
                except Exception as e:
                    self.notifier.notify(
                        title="YouTube authorization failed",
                        message=(
                            "Automated (re)authorization did not complete: "
                            f"{e}\nThe pipeline will retry on the next cycle."
                        ),
                        priority="urgent",
                        dedupe_key="yt-auth-failed",
                    )
                    raise

        # Upload updated credentials
        self.token_manager.encrypt_and_upload([local_token_path, local_client_path])
        
        print("[Uploader] Building YouTube service...")
        service = build('youtube', 'v3', credentials=creds)
        print("[Uploader] YouTube service built successfully.")
        
        # Fetch and display the authenticated channel info
        try:
            channel_response = service.channels().list(
                part='snippet',
                mine=True
            ).execute()
            
            if channel_response.get('items'):
                channel_title = channel_response['items'][0]['snippet']['title']
                print(f"[Uploader] ✓ Authenticated as: {channel_title}")
            else:
                print("[Uploader] ✓ Authenticated (channel info not available)")
        except Exception as e:
            print(f"[Uploader] ✓ Authenticated (could not fetch channel info: {e})")
        

        
        # Cache the service
        if cache_key:
            self._services[cache_key] = service
        
        return service

    def _refresh_with_retry(self, creds: Credentials, local_token_path: str) -> Optional[Credentials]:
        """Refresh OAuth credentials, retrying transient errors with backoff.

        Returns:
            Refreshed credentials on success, or None if the refresh token is
            permanently invalid (revoked/expired) and re-authentication is
            required.

        Raises:
            RuntimeError: If refresh keeps failing for transient reasons.
                Callers should let this propagate so the outer loop retries
                later instead of discarding a still-valid refresh token.
        """
        delays = [2, 4, 8, 16]
        last_error = None
        for attempt, delay in enumerate([0] + delays):
            if delay:
                print(f"[Uploader] Retrying token refresh in {delay}s (attempt {attempt}/{len(delays)})...")
                time.sleep(delay)
            try:
                print("[Uploader] Refreshing expired credentials...")
                creds.refresh(Request())
                print("[Uploader] Credentials refreshed successfully.")
                with open(local_token_path, 'w') as token:
                    token.write(creds.to_json())
                    print(f"[Uploader] Credentials saved to {local_token_path}.")
                return creds
            except RefreshError as e:
                message = str(e).lower()
                if 'invalid_grant' in message or 'invalid_rapt' in message or 'deleted_client' in message:
                    print(f"[Uploader] Refresh token permanently invalid ({e}). Re-authentication required.")
                    self.notifier.notify(
                        title="YouTube re-authorization needed",
                        message=(
                            "The stored YouTube refresh token was rejected by Google "
                            f"({e}).\nCommon causes: OAuth consent screen still in "
                            "'Testing' status (tokens expire after 7 days - publish "
                            "the app to Production), password change, or manual "
                            "revocation.\nStarting the re-authorization flow now."
                        ),
                        priority="urgent",
                        dedupe_key="yt-token-invalid",
                    )
                    return None
                last_error = e
                print(f"[Uploader] Transient refresh error: {e}")
            except Exception as e:
                last_error = e
                print(f"[Uploader] Transient refresh error: {e}")

        self.notifier.notify(
            title="YouTube token refresh failing",
            message=(
                f"Token refresh failed {len(delays) + 1} times in a row "
                f"(last error: {last_error}).\nThe refresh token is kept and the "
                "pipeline will retry on the next cycle. Check network/Google API "
                "status if this persists."
            ),
            priority="high",
            dedupe_key="yt-refresh-transient",
        )
        raise RuntimeError(f"Token refresh failed after retries: {last_error}")

    def _run_auth_flow(self) -> Credentials:
        """Run OAuth authentication flow.

        When an interactive terminal is attached, the consent URL is printed
        and the redirect URL is read from stdin (one-time setup). Otherwise
        the URL is delivered through the configured notification channels and
        the redirect URL is awaited via the ntfy reply topic, a HuggingFace
        upload, or a local file. No browser is ever launched by this package.

        Returns:
            Authenticated credentials
        """
        from youtube_auto_pub.auth_worker import process_auth_via_code

        interactive = sys.stdin.isatty()
        process_auth_via_code(
            self.config,
            prompt=interactive,
            notifier=None if interactive else self.notifier
        )
        return Credentials.from_authorized_user_file(self.config.token_file_path, self.config.scopes)

    def upload_video(
        self,
        service: Any,
        video_path: str,
        metadata: VideoMetadata,
        thumbnail_path: Optional[str] = None
    ) -> Optional[str]:
        """Upload a video to YouTube.
        
        Args:
            service: Authenticated YouTube API service
            video_path: Path to the video file
            metadata: VideoMetadata with title, description, etc.
            thumbnail_path: Optional path to thumbnail image
            
        Returns:
            Video ID if successful, None otherwise
        """
        request_body = {
            'snippet': {
                'categoryId': metadata.category_id,
                'title': metadata.title[:100],  # Max 100 chars
                'description': metadata.description,
                'tags': metadata.tags,
            },
            'status': {
                'privacyStatus': metadata.privacy_status,
                'madeForKids': metadata.made_for_kids,
                'selfDeclaredMadeForKids': metadata.made_for_kids,
            }
        }
        
        if metadata.publish_at:
            request_body['status']['publishAt'] = metadata.publish_at

        # Upload the video (resumable, with retry on transient errors)
        media_file = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = service.videos().insert(
            part='snippet,status',
            body=request_body,
            media_body=media_file
        )

        print(f"[Uploader] Uploading video: {video_path}")
        response = None
        retriable_status_codes = (500, 502, 503, 504)
        max_retries = int(os.getenv("UPLOAD_MAX_RETRIES", "5"))
        retry = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f'[Uploader] Uploaded {int(status.progress() * 100)}% of the video.')
                retry = 0  # progress made, reset the retry budget
            except HttpError as e:
                if e.resp.status in retriable_status_codes and retry < max_retries:
                    retry += 1
                    sleep_seconds = min(2 ** retry, 64)
                    print(f"[Uploader] Retriable HTTP {e.resp.status} during upload. "
                          f"Retry {retry}/{max_retries} in {sleep_seconds}s...")
                    time.sleep(sleep_seconds)
                    continue
                print(f"[Uploader] Error during video upload: {e}")
                self._notify_upload_failure(video_path, metadata.title, e)
                return None
            except Exception as e:
                if retry < max_retries:
                    retry += 1
                    sleep_seconds = min(2 ** retry, 64)
                    print(f"[Uploader] Transient error during upload: {e}. "
                          f"Retry {retry}/{max_retries} in {sleep_seconds}s...")
                    time.sleep(sleep_seconds)
                    continue
                print(f"[Uploader] Error during video upload: {e}")
                self._notify_upload_failure(video_path, metadata.title, e)
                return None

        video_id = response['id']
        print(f'[Uploader] Video uploaded successfully with ID: {video_id}')

        # Upload thumbnail if provided
        if thumbnail_path and video_id:
            self.set_thumbnail(service, video_id, thumbnail_path)

        return video_id

    def _notify_upload_failure(self, video_path: str, title: str, error: Exception) -> None:
        """Alert the user that an upload failed after exhausting retries."""
        self.notifier.notify(
            title="YouTube upload failed",
            message=(
                f"Video: {title}\nFile: {video_path}\nError: {error}\n"
                "The pipeline will retry on the next cycle."
            ),
            priority="high",
            dedupe_key=f"yt-upload-failed:{os.path.basename(video_path)}",
        )

    def add_end_screen_video(
        self,
        service: Any,
        video_id: str,
        related_video_id: str,
    ) -> bool:
        """Add a related video end screen element to a video.

        Args:
            service: Authenticated YouTube API service
            video_id: YouTube video ID to add the end screen to
            related_video_id: YouTube video ID of the related video to link

        Returns:
            True if successful, False otherwise
        """
        try:
            # Fetch video duration to calculate end screen timing
            details = service.videos().list(
                part='contentDetails',
                id=video_id
            ).execute()

            if not details.get('items'):
                print(f"[Uploader] Could not fetch details for video: {video_id}")
                return False

            import re
            iso_duration = details['items'][0]['contentDetails']['duration']
            match = re.match(
                r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration
            )
            if not match:
                print(f"[Uploader] Could not parse video duration: {iso_duration}")
                return False

            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            seconds = int(match.group(3) or 0)
            duration_ms = (hours * 3600 + minutes * 60 + seconds) * 1000

            if duration_ms < 25000:
                print(f"[Uploader] Video too short ({duration_ms}ms) for end screen (min 25s).")
                return False

            end_offset_ms = duration_ms
            start_offset_ms = max(duration_ms - 20000, duration_ms - duration_ms + 5000)

            body = {
                "videoId": video_id,
                "items": [
                    {
                        "endScreenItemType": "VIDEO",
                        "videoId": related_video_id,
                        "left": 0.0,
                        "top": 0.25,
                        "width": 0.35,
                        "startOffsetMs": start_offset_ms,
                        "endOffsetMs": end_offset_ms,
                    }
                ],
            }

            service.videoEndScreens().insert(
                part="id,snippet",
                body=body,
            ).execute()

            print(f"[Uploader] End screen video linked: {related_video_id} -> {video_id}")
            return True
        except Exception as e:
            print(f"[Uploader] Error adding end screen video: {e}")
            return False

    def set_thumbnail(
        self,
        service: Any,
        video_id: str,
        thumbnail_path: str
    ) -> bool:
        """Set thumbnail for a video.
        
        Args:
            service: Authenticated YouTube API service
            video_id: YouTube video ID
            thumbnail_path: Path to thumbnail image
            
        Returns:
            True if successful, False otherwise
        """
        try:
            print(f"[Uploader] Uploading thumbnail: {thumbnail_path}")
            service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print(f"[Uploader] Thumbnail uploaded successfully for video ID: {video_id}")
            return True
        except Exception as e:
            print(f"[Uploader] Error during thumbnail upload: {e}")
            return False
