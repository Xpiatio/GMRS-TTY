#!/usr/bin/env python3
"""Fail if any version reference in the tree disagrees with gmrs_tty/__init__.py.

The version is written in more than one place: gmrs_tty.__version__ (the
canonical source, read by build-deb.sh and the user-manual generator) and the
README release callout. Bumping only some of them ships a release that
misreports itself.

Deliberately a *consistency* check, not a "grep for the old version" check —
docs legitimately name past releases, so scanning for stale strings would cry
wolf on prose that is correct.

Run from the repo root:
    python3 scripts/check_version_sync.py

Adding a new place the version is written? Add it to STAMPS here (or derive it
from gmrs_tty.__version__ so it cannot drift, which is better).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Single-occurrence stamps: (path, regex with one capture group, description).
STAMPS = (
    (
        "README.md",
        re.compile(r"^> \*\*Latest release:\*\* v(\d+\.\d+\.\d+)", re.M),
        "release callout",
    ),
)

failures: list[str] = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def canonical_version() -> str:
    match = re.search(
        r'^__version__ = "(\d+\.\d+\.\d+)"', read("gmrs_tty/__init__.py"), re.M
    )
    if not match:
        sys.exit("gmrs_tty/__init__.py has no usable __version__")
    return match.group(1)


def check_stamps(expected: str) -> None:
    for rel, pattern, description in STAMPS:
        found = pattern.findall(read(rel))
        if not found:
            failures.append(
                f"{rel}: no {description} found — did the format change? "
                f"Update the pattern in {Path(__file__).name}."
            )
            continue
        for actual in found:
            if actual != expected:
                failures.append(
                    f"{rel}: {description} says {actual}, expected {expected}"
                )


def check_tag_matches(expected: str) -> None:
    """When the build was triggered by a version tag, the tag must agree too."""
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        return
    tag = ref[len("refs/tags/"):]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return
    if tag != f"v{expected}":
        failures.append(
            f"tag {tag} does not match gmrs_tty.__version__ {expected} — "
            "the tag would publish artifacts that disagree with the tree"
        )


def main() -> int:
    expected = canonical_version()
    check_stamps(expected)
    check_tag_matches(expected)

    if failures:
        print(f"Version references disagree with gmrs_tty/__init__.py ({expected}):\n")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print(f"All version references agree: {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
