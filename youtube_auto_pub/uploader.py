"""
YouTube API operations: authenticated service acquisition and video
upload / thumbnail / end-screen calls.

Credential mechanics live in `credentials`, encrypted storage in
`token_manager`, and the authorization flow in `auth` - this module only
orchestrates them and talks to the YouTube API.
"""

import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_auto_pub import credentials
from youtube_auto_pub.auth import run_code_flow
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
    """Upload videos to YouTube with automatic credential management."""

    def __init__(self, config: YouTubeConfig):
        self.config = config
        self.token_manager = TokenManager(config)
        self.notifier = Notifier()
        self._services: dict = {}

    # ------------------------------------------------------------------ #
    # authentication
    # ------------------------------------------------------------------ #

    def get_service(
        self,
        cache_key: Optional[str] = None,
        skip_auth_flow: bool = False
    ) -> Any:
        """Get an authenticated YouTube API service.

        Downloads encrypted credentials from HuggingFace Hub, refreshes or
        (re)authorizes as needed, re-uploads the updated credentials, and
        returns a ready service object.

        Args:
            cache_key: Optional key to cache the service for reuse.
            skip_auth_flow: If True, return None instead of starting the
                authorization flow when there are no valid credentials.
        """
        if cache_key and cache_key in self._services:
            print(f"[Uploader] Using cached service for: {cache_key}")
            return self._services[cache_key]

        print("[Uploader] Checking for stored credentials...")
        token_path = self.token_manager.download_and_decrypt(self.config.token_filename)
        client_path = self.token_manager.download_and_decrypt(self.config.client_secret_filename)
        credentials.sync_local_client_secret(self.config, client_path, token_path)

        creds = credentials.load(token_path, self.config.scopes)
        if creds and creds.expired and creds.refresh_token:
            # Transient refresh failures raise (retry next cycle); only a
            # permanently dead grant returns None and falls through to re-auth.
            creds = credentials.refresh(creds, token_path, self.notifier)

        if not creds or not creds.valid:
            if skip_auth_flow:
                print("[Uploader] No valid credentials. Skipping auth flow (skip_auth_flow=True).")
                return None
            print("[Uploader] No valid credentials. Starting authorization flow.")
            creds = self._run_auth_flow()

        self.token_manager.encrypt_and_upload([token_path, client_path])

        service = build('youtube', 'v3', credentials=creds)
        self._print_channel_info(service)

        if cache_key:
            self._services[cache_key] = service
        return service

    def _run_auth_flow(self) -> Credentials:
        """Run the OAuth authorization flow (no browser automation).

        With a terminal attached the redirect URL is read from stdin
        (one-time setup); unattended, the consent URL goes out as a
        notification and the response is awaited via ntfy / HuggingFace /
        local file.
        """
        interactive = sys.stdin.isatty()
        try:
            run_code_flow(
                self.config,
                prompt=interactive,
                notifier=None if interactive else self.notifier
            )
            return Credentials.from_authorized_user_file(self.config.token_file_path, self.config.scopes)
        except Exception as e:
            self.notifier.notify(
                title="YouTube authorization failed",
                message=(
                    f"Authorization did not complete: {e}\n"
                    "The pipeline will retry on the next cycle."
                ),
                priority="urgent",
                dedupe_key="yt-auth-failed",
            )
            raise

    def _print_channel_info(self, service: Any) -> None:
        try:
            response = service.channels().list(part='snippet', mine=True).execute()
            if response.get('items'):
                print(f"[Uploader] ✓ Authenticated as: {response['items'][0]['snippet']['title']}")
            else:
                print("[Uploader] ✓ Authenticated (channel info not available)")
        except Exception as e:
            print(f"[Uploader] ✓ Authenticated (could not fetch channel info: {e})")

    # ------------------------------------------------------------------ #
    # YouTube operations
    # ------------------------------------------------------------------ #

    def upload_video(
        self,
        service: Any,
        video_path: str,
        metadata: VideoMetadata,
        thumbnail_path: Optional[str] = None
    ) -> Optional[str]:
        """Upload a video (resumable, retrying transient errors).

        Returns:
            Video ID if successful, None otherwise.
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

        if thumbnail_path and video_id:
            self.set_thumbnail(service, video_id, thumbnail_path)
        return video_id

    def set_thumbnail(self, service: Any, video_id: str, thumbnail_path: str) -> bool:
        """Set thumbnail for a video."""
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

    def add_end_screen_video(self, service: Any, video_id: str, related_video_id: str) -> bool:
        """Link a related video as an end-screen element (video must be >=25s)."""
        try:
            duration_ms = self._video_duration_ms(service, video_id)
            if duration_ms is None:
                return False
            if duration_ms < 25000:
                print(f"[Uploader] Video too short ({duration_ms}ms) for end screen (min 25s).")
                return False

            body = {
                "videoId": video_id,
                "items": [
                    {
                        "endScreenItemType": "VIDEO",
                        "videoId": related_video_id,
                        "left": 0.0,
                        "top": 0.25,
                        "width": 0.35,
                        "startOffsetMs": max(duration_ms - 20000, 5000),
                        "endOffsetMs": duration_ms,
                    }
                ],
            }
            service.videoEndScreens().insert(part="id,snippet", body=body).execute()
            print(f"[Uploader] End screen video linked: {related_video_id} -> {video_id}")
            return True
        except Exception as e:
            print(f"[Uploader] Error adding end screen video: {e}")
            return False

    def _video_duration_ms(self, service: Any, video_id: str) -> Optional[int]:
        details = service.videos().list(part='contentDetails', id=video_id).execute()
        if not details.get('items'):
            print(f"[Uploader] Could not fetch details for video: {video_id}")
            return None
        iso_duration = details['items'][0]['contentDetails']['duration']
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
        if not match:
            print(f"[Uploader] Could not parse video duration: {iso_duration}")
            return None
        hours, minutes, seconds = (int(g or 0) for g in match.groups())
        return (hours * 3600 + minutes * 60 + seconds) * 1000

    def _notify_upload_failure(self, video_path: str, title: str, error: Exception) -> None:
        self.notifier.notify(
            title="YouTube upload failed",
            message=(
                f"Video: {title}\nFile: {video_path}\nError: {error}\n"
                "The pipeline will retry on the next cycle."
            ),
            priority="high",
            dedupe_key=f"yt-upload-failed:{os.path.basename(video_path)}",
        )
