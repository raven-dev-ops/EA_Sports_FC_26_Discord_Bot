from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"

_ENV: Environment | None = None


def templates_dir() -> Path:
    return _TEMPLATES_DIR


def static_dir() -> Path:
    return _STATIC_DIR


def static_url(path: str) -> str:
    cleaned = (path or "").lstrip("/")
    return f"/static/{cleaned}"


def env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        _ENV.globals["static_url"] = static_url
    return _ENV


def render(template_name: str, /, **context: Any) -> str:
    template = env().get_template(template_name)
    return template.render(**context)


def safe_html(html: str) -> Markup:
    return Markup(html)

