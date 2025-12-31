"""
Lightweight accessibility checks for key templates.

Usage:
  python -m scripts.check_a11y_templates
"""
from __future__ import annotations

from pathlib import Path

CHECKS = [
    ("offside_bot/templates/base.html", 'class="skip-link"', "Skip link missing in base layout."),
    ("offside_bot/templates/base.html", 'href="#main-content"', "Skip link target missing."),
    ("offside_bot/templates/layouts/public.html", 'id="main-content"', "Public layout missing main content id."),
    ("offside_bot/templates/layouts/app.html", 'id="main-content"', "App layout missing main content id."),
    ("offside_bot/templates/partials/app_shell.html", 'id="main-content"', "App shell missing main content id."),
    ("offside_bot/templates/layouts/public.html", 'aria-current="page"', "Public nav missing aria-current."),
    ("offside_bot/templates/partials/app_shell.html", 'aria-current="page"', "Sidebar nav missing aria-current."),
    ("offside_bot/templates/pages/commands.html", 'aria-live="polite"', "Commands page missing aria-live region."),
]


def main() -> None:
    failures: list[str] = []
    for path_str, needle, message in CHECKS:
        path = Path(path_str)
        if not path.exists():
            failures.append(f"{path_str}: file not found")
            continue
        content = path.read_text(encoding="utf-8")
        if needle not in content:
            failures.append(f"{path_str}: {message}")
    if failures:
        print("A11y template checks failed:")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(1)
    print("A11y template checks passed.")


if __name__ == "__main__":
    main()
