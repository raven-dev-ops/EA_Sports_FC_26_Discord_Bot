from offside_bot.web_templates import render


def test_dashboard_templates_render() -> None:
    templates = [
        (
            "pages/dashboard/server_picker.html",
            {
                "cards": [
                    {
                        "id": "123",
                        "name": "Test Guild",
                        "icon_url": "",
                        "fallback": "TG",
                        "eligible": True,
                        "plan_label": "FREE",
                        "plan_class": "free",
                        "install_label": "INSTALLED",
                        "install_class": "ok",
                        "show_upgrade": True,
                        "show_invite": False,
                        "invite_class": "secondary",
                    }
                ],
                "invite_href": "https://example.com/invite",
            },
        ),
        (
            "pages/dashboard/guild_analytics.html",
            {
                "guild_id": 123,
                "plan_label": "FREE",
                "plan_class": "free",
                "db_name": "testdb",
                "generated_at": "2025-01-01T00:00:00Z",
                "analytics_json_href": "/api/guild/123/analytics.json",
                "settings_href": "/guild/123/settings",
                "permissions_href": "/guild/123/permissions",
                "audit_href": "/guild/123/audit",
                "record_counts": [{"record_type": "submission_message", "count": 2}],
                "collection_counts": [{"collection": "submissions", "count": 2}],
            },
        ),
        (
            "pages/dashboard/guild_overview.html",
            {
                "guild_id": 123,
                "db_name": "testdb",
                "test_mode": "false",
                "checks": [
                    {
                        "name": "Bot installed",
                        "status": {"label": "OK", "kind": "ok"},
                        "details": "Installed",
                        "fix_href": "/guild/123/settings",
                    }
                ],
                "metrics": [{"label": "Roster submissions", "value": "1"}],
                "mongodb_configured": True,
                "actions_disabled": False,
                "csrf_token": "csrf",
                "settings_href": "/guild/123/settings",
            },
        ),
        (
            "pages/dashboard/guild_settings.html",
            {
                "installed": False,
                "guild_id": 123,
                "invite_href": "https://example.com/invite",
            },
        ),
        (
            "pages/dashboard/guild_ops.html",
            {
                "guild_id": 123,
                "notices": [],
                "mongodb_configured": False,
                "heartbeat_text": "missing",
                "actions_disabled": True,
                "csrf_token": "csrf",
                "tasks": [],
                "deletion_state": {"mode": "disabled", "reason": "MongoDB is not configured."},
                "deletion_note": None,
            },
        ),
        (
            "pages/dashboard/guild_setup_wizard.html",
            {
                "guild_id": 123,
                "plan_label": "FREE",
                "plan_class": "free",
                "ready_status": {"label": "NOT READY", "kind": "warn"},
                "ready_details": "Complete the steps below to finish setup.",
                "actions_disabled": True,
                "csrf_token": "csrf",
                "steps": [
                    {
                        "title": "Step 1: Permissions",
                        "status": {"label": "WARN", "kind": "warn"},
                        "details": "Install the bot to validate permissions.",
                        "action_label": "Open",
                        "action_href": "/guild/123/permissions",
                    }
                ],
                "tasks": [],
                "tasks_error": None,
                "queued": False,
            },
        ),
        (
            "pages/dashboard/guild_permissions.html",
            {
                "guild_id": 123,
                "invite_href": "https://example.com/invite",
                "blocked_message": "Bot is not installed in this server yet.",
                "is_admin": False,
                "top_role_name": "",
                "top_role_pos": "0",
                "settings_href": "/guild/123/settings",
                "guild_permissions": [],
                "role_hierarchy": [],
                "channel_access": [],
            },
        ),
        (
            "pages/dashboard/guild_audit.html",
            {
                "guild_id": 123,
                "limit": 10,
                "rows": [],
                "download_href": "/guild/123/audit.csv?limit=10",
            },
        ),
        (
            "pages/dashboard/locked_pro.html",
            {
                "title": "Ops",
                "message": "Locked.",
                "benefits": [{"name": "Automation", "desc": "Run tasks faster."}],
                "upgrade_href": "/app/upgrade?guild_id=123",
                "guild_id": 123,
            },
        ),
        (
            "pages/dashboard/locked_owner.html",
            {
                "title": "Billing",
                "message": "Owner only.",
                "guild_id": 123,
            },
        ),
        (
            "pages/dashboard/billing.html",
            {
                "has_guild": True,
                "guild_id": 123,
                "status_message": "",
                "current_plan_label": "FREE",
                "current_plan_class": "free",
                "manage_portal": False,
                "guild_options": [{"value": "123", "label": "Test Guild", "selected": True}],
                "upgrade_disabled": False,
                "upgrade_text": "Upgrade to Pro",
                "csrf_token": "csrf",
            },
        ),
        (
            "pages/dashboard/billing_success.html",
            {
                "guild_id": 123,
                "message": "Pro enabled for this server.",
                "plan_label": "PRO",
                "plan_class": "pro",
                "billing_href": "/app/billing?guild_id=123",
                "analytics_href": "/guild/123",
                "settings_href": "/guild/123/settings",
            },
        ),
    ]

    for template_name, context in templates:
        html = render(template_name, **context)
        assert isinstance(html, str)
        assert html.strip()
