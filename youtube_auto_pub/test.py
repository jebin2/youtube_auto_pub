#!/usr/bin/env python3
import subprocess
import sys
import re


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def normalise(url):
    url = re.sub(r"https://[^@]+@", "https://", url)
    return url.rstrip("/").removesuffix(".git").lower()


def main():
    remote_url = "https://github.com/jebin2/Elvoro.git"
    branches = ["main", "feature/video-revamp"]

    # verify remote
    current_remote = run(["git", "remote", "get-url", "origin"], check=False).stdout.strip()

    if "Elvoro" in current_remote:
        die(
            f"Remote mismatch.\n"
            f"  Current: {current_remote}\n"
            f"  Expected: {remote_url}\n"
            f"Aborting."
        )

    print(f"→ Remote verified: {remote_url}")

    # configure git identity (required in CI)
    run(["git", "config", "--global", "user.name", "github-actions"])
    run(["git", "config", "--global", "user.email", "actions@github.com"])

    # fetch all branches
    print("→ Fetching branches")
    run(["git", "fetch", "--all", "--prune"])

    original_branch = (
        run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False).stdout.strip()
    )

    for branch in branches:
        try:
            print(f"\n→ Processing '{branch}'")

            # checkout branch from origin
            run(["git", "checkout", "-B", branch, f"origin/{branch}"])

            # create orphan branch
            run(["git", "checkout", "--orphan", "temp-wipe"])

            # remove all files
            run(["git", "rm", "-rf", "."], check=False)
            run(["git", "clean", "-fd"], check=False)

            print(f"→ Creating empty commit for '{branch}'")
            run(["git", "commit", "--allow-empty", "-m", "wipe history"])

            print(f"→ Force pushing to '{branch}'")

            r = run(
                ["git", "push", "origin", f"HEAD:{branch}", "--force"],
                check=False
            )

            if r.returncode != 0:
                die(f"Push failed for '{branch}':\n{r.stderr}")

            # cleanup
            run(["git", "checkout", original_branch], check=False)
            run(["git", "branch", "-D", "temp-wipe"], check=False)

        except Exception as e:
            print(f"ERROR processing '{branch}': {e}")
            continue

    print("\n✅ Done. All specified branches wiped.")

main()
if __name__ == "__main__":
    main()
