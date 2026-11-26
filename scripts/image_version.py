"""Calculate the image's SemVer from the current commit's first-parent history."""

import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(("git", *args), text=True).strip()


def version_at(ref):
    value = git("show", f"{ref}:VERSION")
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("VERSION must contain MAJOR.MINOR.PATCH with no leading zeros.")
    baseline = tuple(map(int, value.split(".")))
    anchor = git("log", "--first-parent", "-1", "--format=%H", ref, "--", "VERSION")
    count = int(git("rev-list", "--first-parent", "--count", f"{anchor}..{ref}"))
    major, minor, patch = baseline
    return (major, minor, patch + count), baseline, anchor


def main():
    version, baseline, anchor = version_at("HEAD")
    parent = f"{anchor}^1"
    previous_exists = subprocess.run(
        ("git", "cat-file", "-e", f"{parent}:VERSION"),
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if previous_exists:
        previous, _, _ = version_at(parent)
        if baseline <= previous:
            raise ValueError(f"VERSION must advance beyond {'.'.join(map(str, previous))}.")
    print(".".join(map(str, version)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
