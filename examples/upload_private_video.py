"""Live smoke test: upload a tiny PRIVATE video to your channel for real.

Exercises the whole chain end-to-end - encrypted credentials from
HuggingFace, token refresh (or first-time auth), resumable upload - using
your actual account. The video is private, marked as a test, and can be
deleted automatically afterwards.

Requires the usual env vars: HF_TOKEN, HF_YT_CRED_REPO_ID, ENCRYPT_KEY
(and NTFY_TOPIC if you want to see the notifications fire).

Usage:
    python examples/upload_private_video.py                  # 2s generated clip (needs ffmpeg)
    python examples/upload_private_video.py my_video.mp4     # your own file
    python examples/upload_private_video.py --delete-after   # upload, verify, delete
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

from youtube_auto_pub import YouTubeConfig, YouTubeUploader, VideoMetadata


def make_test_clip(path: str) -> None:
    """Generate a 2-second colour-bar clip with a beep."""
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found. Install it, or pass a video file:\n"
                 "    python examples/upload_private_video.py my_video.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-shortest", path],
        check=True,
    )
    print(f"Generated test clip: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a private test video to YouTube.")
    parser.add_argument("video", nargs="?", help="Video file (default: generate a 2s clip)")
    parser.add_argument("--delete-after", action="store_true",
                        help="Delete the video again after a successful upload")
    args = parser.parse_args()

    tmp_dir = None
    video_path = args.video
    if not video_path:
        tmp_dir = tempfile.mkdtemp(prefix="yt_smoke_")
        video_path = os.path.join(tmp_dir, "test.mp4")
        make_test_clip(video_path)
    elif not os.path.exists(video_path):
        sys.exit(f"File not found: {video_path}")

    try:
        uploader = YouTubeUploader(YouTubeConfig())
        service = uploader.get_service()

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        video_id = uploader.upload_video(
            service,
            video_path,
            VideoMetadata(
                title=f"youtube_auto_pub smoke test {stamp}",
                description="Uploaded by examples/upload_private_video.py - safe to delete.",
                tags=["youtube_auto_pub", "smoke-test"],
                privacy_status="private",
            ),
        )

        if not video_id:
            sys.exit("Upload failed - see the log and notifications above.")

        print(f"\n✓ Uploaded (private): https://youtube.com/watch?v={video_id}")

        if args.delete_after:
            service.videos().delete(id=video_id).execute()
            print("✓ Deleted again - full round trip complete.")
        else:
            print("  It is only visible to you. Delete it in YouTube Studio,")
            print("  or rerun with --delete-after for an automatic round trip.")
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
