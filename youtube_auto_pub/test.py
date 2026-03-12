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
    branches = ["main", "feature/video-revamp"]

    # verify remote
    current_remote = run(["git", "remote", "get-url", "origin"], check=False).stdout.strip()

    if "Elvoro" not in current_remote:
        die(
            f"Remote mismatch.\n"
            f"Current: {current_remote}\n"
            f"Expected: Elvoro\n"
            f"Aborting."
        )

    print(f"→ Remote verified: Elvoro")

    # configure git identity (required in CI)
    run(["git", "config", "--global", "user.name", "github-actions"])
    run(["git", "config", "--global", "user.email", "actions@github.com"])

    print("→ Fetching branches")
    run(["git", "fetch", "--all", "--prune"], check=False)

    for branch in branches:
        try:
            print(f"\n→ Processing '{branch}'")

            # check if branch exists on remote
            exists = run(
                ["git", "ls-remote", "--heads", "origin", branch],
                check=False
            )

            if not exists.stdout.strip():
                print(f"→ Branch '{branch}' does not exist on remote. Skipping.")
                continue

            # create orphan branch
            run(["git", "checkout", "--orphan", "temp-wipe"])

            # remove files
            run(["git", "rm", "-rf", "."], check=False)
            run(["git", "clean", "-fd"], check=False)

            print(f"→ Creating empty commit for '{branch}'")
            run(["git", "commit", "--allow-empty", "-m", "wipe history"])

            print(f"→ Force pushing to '{branch}'")

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
            print(f"ERROR processing '{branch}': {e}")
            continue

    print("\n✅ Done. All specified branches wiped.")

main()
if __name__ == "__main__":
    main()
