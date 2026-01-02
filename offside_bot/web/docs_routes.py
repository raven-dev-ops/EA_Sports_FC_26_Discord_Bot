from __future__ import annotations

from typing import Any

from aiohttp import web

from offside_bot.web.content import escape_html, markdown_to_html, repo_read_text
from offside_bot.web_templates import render, safe_html

DOCS_PAGES: list[dict[str, str]] = [
    {
        "slug": "server-setup-checklist",
        "title": "Server setup checklist",
        "path": "docs/public/server-setup-checklist.md",
        "summary": "Step-by-step setup for new servers.",
    },
    {
        "slug": "billing",
        "title": "Billing",
        "path": "docs/public/billing.md",
        "summary": "Stripe setup, pricing, and subscription details.",
    },
    {
        "slug": "faq",
        "title": "FAQ",
        "path": "docs/public/faq.md",
        "summary": "Common questions about setup, pricing, and data.",
    },
    {
        "slug": "data-lifecycle",
        "title": "Data lifecycle",
        "path": "docs/public/data-lifecycle.md",
        "summary": "Retention, deletion, and data export guidance.",
    },
    {
        "slug": "analytics",
        "title": "Analytics",
        "path": "docs/public/analytics.md",
        "summary": "Funnel event schema and configuration.",
    },
    {
        "slug": "fc25-stats-policy",
        "title": "FC stats policy",
        "path": "docs/public/fc25-stats-policy.md",
        "summary": "Stats data handling policy and expectations.",
    },
]
DOCS_BY_SLUG = {page["slug"]: page for page in DOCS_PAGES}
DOCS_EXTRAS = [
    {
        "title": "Commands reference",
        "summary": "Slash command list grouped by category.",
        "href": "/commands",
    }
]
HELP_ALIASES = {
    "setup": "server-setup-checklist",
    "billing": "billing",
    "faq": "faq",
}


def _commands_group_for_category(category: str) -> str:
    key = (category or "").strip().lower()
    if key in {"roster", "recruitment"}:
        return "coach"
    if key == "staff":
        return "staff"
    if key == "operations":
        return "ops"
    if key == "tournament":
        return "tournament"
    return "other"


def _strip_inline_code(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        return text[1:-1].strip()
    return text


def _parse_commands_markdown(text: str) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    current_category: dict[str, Any] | None = None
    current_command: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("## "):
            name = line[3:].strip()
            current_category = {"name": name, "group": _commands_group_for_category(name), "commands": []}
            categories.append(current_category)
            current_command = None
            continue

        if line.startswith("### "):
            if current_category is None:
                continue
            signature = line[4:].strip()
            current_command = {"signature": signature, "description": "", "permissions": "", "example": ""}
            current_category["commands"].append(current_command)
            continue

        if line.startswith("- ") and current_command is not None:
            item = line[2:].strip()
            if ":" not in item:
                continue
            key, value = item.split(":", 1)
            normalized_key = key.strip().lower()
            normalized_value = value.strip()
            if normalized_key == "description":
                current_command["description"] = normalized_value
            elif normalized_key == "permissions":
                current_command["permissions"] = normalized_value
            elif normalized_key == "example":
                current_command["example"] = _strip_inline_code(normalized_value)
            continue

    for category in categories:
        for command in category.get("commands", []):
            blob = " ".join(
                part
                for part in [
                    str(command.get("signature") or ""),
                    str(command.get("description") or ""),
                    str(command.get("permissions") or ""),
                    str(command.get("example") or ""),
                ]
                if part
            )
            command["search_text"] = blob.lower()

    return [c for c in categories if c.get("commands")]


def _build_docs_index_entries(*, base_path: str) -> list[dict[str, str]]:
    docs = [
        {"title": page["title"], "summary": page["summary"], "href": f"{base_path}/{page['slug']}"}
        for page in DOCS_PAGES
    ]
    for item in DOCS_EXTRAS:
        entry = dict(item)
        if base_path != "/docs" and entry["href"].startswith("/docs"):
            entry["href"] = entry["href"].replace("/docs", base_path, 1)
        docs.append(entry)
    return docs


def _render_doc_page(
    doc: dict[str, str],
    *,
    back_href: str,
    back_label: str,
    session: Any | None,
) -> web.Response:
    text = repo_read_text(doc["path"])
    if text is None:
        raise web.HTTPNotFound(text=f"{doc['path']} not found.")
    html = markdown_to_html(text)
    summary = str(doc.get("summary") or "").strip()
    if summary:
        description = f"{summary} Offside help for EA Sports FC 26 Discord servers."
    else:
        description = "Offside help for EA Sports FC 26 Discord servers."
    content = f"""
      <section class="section">
        <div class="card hero-card">
          <a class="back-link" href="{escape_html(back_href)}">&larr; {escape_html(back_label)}</a>
          <h1 class="mt-6 text-hero-sm">{escape_html(doc["title"])}</h1>
        </div>
      </section>
      <section class="section">
        <div class="card prose">{html}</div>
      </section>
    """
    page_html = render(
        "pages/markdown_page.html",
        title=doc["title"],
        description=description,
        session=session,
        content=safe_html(content),
        active_nav="support",
    )
    return web.Response(text=page_html, content_type="text/html")


async def docs_index_page(request: web.Request) -> web.Response:
    docs = _build_docs_index_entries(base_path="/docs")
    page_html = render(
        "pages/docs_index.html",
        title="Docs for FC 26 Discord bot",
        description=(
            "Documentation for Offside, the EA Sports FC 26 Discord bot: server setup, billing, "
            "data lifecycle, FAQ, and commands."
        ),
        session=request.get("session"),
        docs=docs,
        active_nav="support",
    )
    return web.Response(text=page_html, content_type="text/html")


async def docs_page(request: web.Request) -> web.Response:
    slug = str(request.match_info.get("slug") or "").strip()
    doc = DOCS_BY_SLUG.get(slug)
    if not doc:
        raise web.HTTPNotFound(text="Doc not found.")
    return _render_doc_page(
        doc,
        back_href="/docs",
        back_label="Back to docs",
        session=request.get("session"),
    )


async def commands_page(request: web.Request) -> web.Response:
    text = repo_read_text("docs/public/commands.md")
    if text is None:
        raise web.HTTPNotFound(text="docs/public/commands.md not found.")

    categories = _parse_commands_markdown(text)
    page = render(
        "pages/commands.html",
        title="FC 26 Discord bot commands",
        description=(
            "Command reference for Offside, the EA Sports FC 26 Discord bot. "
            "Browse slash commands by category."
        ),
        session=request.get("session"),
        categories=categories,
        active_nav="support",
    )
    return web.Response(text=page, content_type="text/html")


async def help_index_page(request: web.Request) -> web.Response:
    docs = _build_docs_index_entries(base_path="/help")
    page_html = render(
        "pages/docs_index.html",
        title="Help center for FC 26 Discord bot",
        description=(
            "Help center for Offside, the EA Sports FC 26 Discord bot. "
            "Setup guides, billing info, data lifecycle, FAQ, and commands."
        ),
        session=request.get("session"),
        heading="Help center",
        subtitle="Setup guides, billing info, and answers for Offside.",
        docs=docs,
        active_nav="support",
    )
    return web.Response(text=page_html, content_type="text/html")


async def help_page(request: web.Request) -> web.Response:
    slug = str(request.match_info.get("slug") or "").strip()
    if slug == "commands":
        raise web.HTTPFound(location="/commands")
    slug = HELP_ALIASES.get(slug, slug)
    doc = DOCS_BY_SLUG.get(slug)
    if not doc:
        raise web.HTTPNotFound(text="Help doc not found.")
    return _render_doc_page(
        doc,
        back_href="/help",
        back_label="Back to help",
        session=request.get("session"),
    )
