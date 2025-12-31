"""
Validate release metadata for versioning and changelog consistency.

Usage:
  python -m scripts.check_release_metadata
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

VERSION_PATH = Path("VERSION")
CHANGELOG_PATH = Path("CHANGELOG.md")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _fail(message: str) -> None:
    print(f"Release metadata check failed: {message}", file=sys.stderr)
    sys.exit(1)


def _read_version() -> str:
    if not VERSION_PATH.exists():
        _fail("VERSION file is missing.")
    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not version:
        _fail("VERSION file is empty.")
    if not SEMVER_RE.fullmatch(version):
        _fail(f"VERSION '{version}' is not valid SemVer (MAJOR.MINOR.PATCH).")
    return version


def _top_changelog_version(text: str) -> str:
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
    if not match:
        _fail("CHANGELOG.md does not contain a release heading.")
    return match.group(1)


def _check_tag(version: str) -> None:
    ref = os.getenv("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        return
    tag = ref.split("/", 2)[2]
    expected = f"v{version}"
    if tag != expected:
        _fail(f"Tag '{tag}' does not match VERSION '{version}' (expected '{expected}').")


def main() -> None:
    version = _read_version()
    if not CHANGELOG_PATH.exists():
        _fail("CHANGELOG.md is missing.")
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    top_version = _top_changelog_version(changelog)
    if top_version != version:
        _fail(f"Top CHANGELOG.md version '{top_version}' does not match VERSION '{version}'.")
    _check_tag(version)
    print("Release metadata checks passed.")


if __name__ == "__main__":
    main()
