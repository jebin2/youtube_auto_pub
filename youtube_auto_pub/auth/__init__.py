"""
OAuth authorization package.

- flow: build the consent URL, collect the response, exchange the code
- receivers: the ways a response can reach the pipeline (file / ntfy / HF)
- instructions: human-facing re-authorization message
- cli: `python -m youtube_auto_pub.auth` entry point
"""

from youtube_auto_pub.auth.flow import run_code_flow
from youtube_auto_pub.auth.instructions import build_reauth_instructions

__all__ = ["run_code_flow", "build_reauth_instructions"]
