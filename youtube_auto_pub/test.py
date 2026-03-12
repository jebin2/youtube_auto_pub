#!/usr/bin/env python3
import subprocess
import sys


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    remote_url = "https://github.com/jebin2/Elvoro.git"

    # Safety: confirm current repo's origin matches remote_url
    current_remote = run(["git", "remote", "get-url", "origin"], check=False).stdout.strip()
    # Normalise both URLs for comparison (strip token, trailing .git)
    def normalise(url):
        import re
        url = re.sub(r"https://[^@]+@", "https://", url)
        return url.rstrip("/").removesuffix(".git").lower()

    if "Elvoro" not in current_remote:
        die(f"Remote mismatch.\n  Current: {current_remote}\n  Expected: {remote_url}\nAborting.")

    print(f"  → Remote verified: {remote_url}")
    exit(0)
    original_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    for branch in ["main", "feature/video-revamp"]:
        try:
            print(f"\n  → Processing '{branch}'")
            run(["git", "checkout", branch])

            # Orphan = new branch with no history
            run(["git", "checkout", "--orphan", f"temp-wipe"])

            # Remove all tracked files from index and disk
            run(["git", "rm", "-rf", "."], check=False)

            print(f"  → Creating empty commit for '{branch}'")
            run(["git", "commit", "--allow-empty", "-m", "wipe"])

            print(f"  → Force pushing to {remote_url} branch '{branch}'")
            r = run(["git", "push", remote_url, f"HEAD:{branch}", "--force"], check=False)
            if r.returncode != 0:
                run(["git", "checkout", original_branch], check=False)
                run(["git", "branch", "-D", "temp-wipe"], check=False)
                die(f"Push failed on '{branch}':\n{r.stderr.strip()}")

            # Clean up temp orphan
            run(["git", "checkout", original_branch])
            run(["git", "branch", "-D", "temp-wipe"])
        except Exception as e:
            print(f"ERROR: {e}")
            continue

    print("\nDone. All branches wiped on remote.")

main()
if __name__ == "__main__":
    main()
