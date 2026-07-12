"""
OAuth authorization package.

- flow: build the consent URL, collect the response, exchange the code
- receivers: the ways a response can reach the pipeline (file / ntfy / HF)
- instructions: human-facing re-authorization message
- cli: `python -m youtube_auto_pub.auth` entry point
"""

from youtube_auto_pub.auth.flow import run_code_flow, run_local_server_flow
from youtube_auto_pub.auth.instructions import build_reauth_instructions

# Backwards-compatible aliases (pre-0.4 names)
process_auth = run_local_server_flow
process_auth_via_code = run_code_flow

__all__ = [
    "run_code_flow",
    "run_local_server_flow",
    "build_reauth_instructions",
    "process_auth",
    "process_auth_via_code",
]
