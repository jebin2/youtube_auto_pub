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
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

from youtube_auto_pub.config import YouTubeConfig
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

        # Refresh expired credentials
        if creds and creds.expired and creds.refresh_token:
            try:
                print("[Uploader] Refreshing expired credentials...")
                creds.refresh(Request())
                print("[Uploader] Credentials refreshed successfully.")
                with open(local_token_path, 'w') as token:
                    token.write(creds.to_json())
                    print(f"[Uploader] Credentials saved to {local_token_path}.")
            except Exception as e:
                print(f"[Uploader] Error refreshing token: {e}")
                creds = None

        # Run auth flow if needed
        if not creds or not creds.valid:
            if not creds or not creds.refresh_token:
                if skip_auth_flow:
                    print("[Uploader] No valid credentials. Skipping auth flow (skip_auth_flow=True).")
                    return None
                print("[Uploader] No valid credentials or refresh token. Initiating authentication flow.")
                creds = self._run_auth_flow()

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

    def _run_auth_flow(self) -> Credentials:
        """Run OAuth authentication flow.
        
        Returns:
            Authenticated credentials
        """
        from youtube_auto_pub.auth_worker import process_auth_via_code
        from youtube_auto_pub.oauth_automater import GoogleOAuthAutomator
        
        if self.config.headless_mode:
            # Headless mode - use code-based auth
            process_auth_via_code(
                self.config,
                prompt=not self.config.is_docker
            )
            return Credentials.from_authorized_user_file(self.config.token_file_path, self.config.scopes)
        else:
            # GUI mode - use subprocess + browser automation
            cmd = [
                sys.executable, '-u', '-m', 'youtube_auto_pub.auth_worker', 
                '-c', self.config.client_id_path, 
                '-t', self.config.token_file_path, 
                '-s', ','.join(self.config.scopes)
            ]
            
            # Use file-mode if we suspect network isolation (e.g. Docker)
            if self.config.is_docker or True: # Force file mode for better stability in remote envs
                 cmd.append('--file-mode')
                 
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )
            
            for line in process.stdout:
                print(f"[Auth] {line.strip()}")  # Debug output
                # Check for both formats
                if "Please visit this URL to authorize this application:" in line:
                    # Format: Please visit this URL to authorize this application: https://...
                    auth_url = f'https://{line.strip().split("https://")[-1]}'
                    automator = GoogleOAuthAutomator(config=self.config)
                    automator.authorize_oauth(auth_url)
                elif "authorization_url####" in line:
                    # Format: authorization_url####https://...
                    auth_url = line.strip().split("####")[-1]
                    automator = GoogleOAuthAutomator(config=self.config)
                    automator.authorize_oauth(auth_url)
                elif "Credentials saved to" in line:
                    return Credentials.from_authorized_user_file(self.config.token_file_path, self.config.scopes)
            
            # Wait for process to complete
            process.wait()
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

        # Upload the video
        media_file = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = service.videos().insert(
            part='snippet,status',
            body=request_body,
            media_body=media_file
        )

        print(f"[Uploader] Uploading video: {video_path}")
        response = None
        
        try:
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f'[Uploader] Uploaded {int(status.progress() * 100)}% of the video.')
        except Exception as e:
            print(f"[Uploader] Error during video upload: {e}")
            return None

        video_id = response['id']
        print(f'[Uploader] Video uploaded successfully with ID: {video_id}')

        # Upload thumbnail if provided
        if thumbnail_path and video_id:
            self.set_thumbnail(service, video_id, thumbnail_path)

        return video_id

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
