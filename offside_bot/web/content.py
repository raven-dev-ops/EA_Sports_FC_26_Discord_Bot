from __future__ import annotations

from pathlib import Path


def escape_html(value: object) -> str:
    text = str(value) if value is not None else ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def repo_read_text(filename: str) -> str | None:
    path = Path(__file__).resolve().parents[2] / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:
        return None


def markdown_to_html(text: str) -> str:
    try:
        import markdown  # type: ignore[import-not-found]
    except Exception:
        return f"<pre>{escape_html(text)}</pre>"
    return markdown.markdown(text, extensions=["extra"], output_format="html")
