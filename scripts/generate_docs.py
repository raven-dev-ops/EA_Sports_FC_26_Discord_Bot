"""
Generate markdown documentation for commands from the shared command catalog.

Usage:
  python -m scripts.generate_docs           # writes docs/commands.md
  python -m scripts.generate_docs --check   # exits non-zero if docs are stale
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from utils.command_catalog import commands_by_category

DOC_PATH = pathlib.Path("docs/commands.md")


def render_markdown() -> str:
    lines: list[str] = ["# Command Reference", ""]
    for category, cmds in commands_by_category().items():
        lines.append(f"## {category}")
        lines.append("")
        for cmd in cmds:
            lines.append(f"### {cmd.name}")
            lines.append("")
            lines.append(f"- Description: {cmd.description}")
            lines.append(f"- Permissions: {cmd.permissions}")
            if cmd.example:
                lines.append(f"- Example: `{cmd.example}`")
            lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_doc() -> bool:
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = render_markdown()
    old = DOC_PATH.read_text() if DOC_PATH.exists() else ""
    if old == content:
        return False
    DOC_PATH.write_text(content, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Exit non-zero if docs would change.")
    args = parser.parse_args()
    changed = write_doc()
    if args.check and changed:
        print("Docs are out of date; please re-run without --check.")
        sys.exit(1)
    if changed:
        print(f"Updated {DOC_PATH}")
    else:
        print(f"{DOC_PATH} is up to date.")


if __name__ == "__main__":
    main()
