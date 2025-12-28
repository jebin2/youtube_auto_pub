"""
YouTube Uploader for uploading videos to YouTube.

Provides a clean, configurable interface for:
- Authenticating with YouTube API
- Uploading videos with metadata
- Setting thumbnails
"""

import os
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

from youtube_auto_pub.config import YouTubeConfig, YOUTUBE_SCOPES
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
    
    def __init__(self, config: Optional[YouTubeConfig] = None):
        """Initialize YouTube uploader.
        
        Args:
            config: YouTubeConfig instance for credential paths
        """
        self.config = config or YouTubeConfig()
        self.token_manager = TokenManager(self.config)
        self._services: dict = {}

    def get_service(
        self,
        token_path: str,
        client_path: str,
        scopes: Optional[List[str]] = None,
        cache_key: Optional[str] = None
    ) -> Any:
        """Get an authenticated YouTube API service.
        
        This method:
        1. Downloads encrypted credentials from HuggingFace Hub
        2. Loads/refreshes OAuth tokens
        3. Initiates auth flow if needed
        4. Returns an authenticated YouTube service
        
        Args:
            token_path: Filename of the token file (will be downloaded)
            client_path: Filename of the client secrets file (will be downloaded)
            scopes: OAuth scopes (defaults to YOUTUBE_SCOPES)
            cache_key: Optional key to cache the service for reuse
            
        Returns:
            Authenticated YouTube API service object
        """
        scopes = scopes or YOUTUBE_SCOPES
        
        # Return cached service if available
        if cache_key and cache_key in self._services:
            print(f"[Uploader] Using cached service for: {cache_key}")
            return self._services[cache_key]
        
        print("[Uploader] Checking for stored credentials...")
        
        # Download and decrypt credential files
        local_token_path = self.token_manager.download_and_decrypt(token_path)
        local_client_path = self.token_manager.download_and_decrypt(client_path)
        
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
                print("[Uploader] No valid credentials or refresh token. Initiating authentication flow.")
                creds = self._run_auth_flow(local_client_path, local_token_path, scopes)

        # Upload updated credentials
        self.token_manager.encrypt_and_upload([local_token_path, local_client_path])
        
        print("[Uploader] Building YouTube service...")
        service = build('youtube', 'v3', credentials=creds)
        print("[Uploader] YouTube service built successfully.")
        
        # Cache the service
        if cache_key:
            self._services[cache_key] = service
        
        return service

    def _run_auth_flow(
        self,
        client_path: str,
        token_path: str,
        scopes: List[str]
    ) -> Credentials:
        """Run OAuth authentication flow.
        
        Args:
            client_path: Path to client secrets file
            token_path: Path where token will be saved
            scopes: OAuth scopes
            
        Returns:
            Authenticated credentials
        """
        from youtube_auto_pub.auth_worker import process_auth_via_code
        from youtube_auto_pub.oauth_automater import GoogleOAuthAutomator
        
        if self.config.headless_mode:
            # Headless mode - use code-based auth
            process_auth_via_code(
                client_path, 
                token_path, 
                scopes, 
                prompt=not self.config.is_docker,
                config=self.config
            )
            return Credentials.from_authorized_user_file(token_path, scopes)
        else:
            # GUI mode - use subprocess + browser automation
            process = subprocess.Popen(
                ['python', '-u', '-m', 'youtube_auto_pub.auth_worker', 
                 '-c', client_path, '-t', token_path, '-s', ','.join(scopes)],
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
                    return Credentials.from_authorized_user_file(token_path, scopes)
            
            # Wait for process to complete
            process.wait()
            return Credentials.from_authorized_user_file(token_path, scopes)

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
