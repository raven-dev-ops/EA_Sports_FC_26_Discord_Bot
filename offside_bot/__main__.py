import asyncio
import logging
import os
import pkgutil
import signal
import sys
from typing import Any, TypeAlias

import discord
from discord.ext import commands

from config import Settings, load_settings
from config.settings import summarize_settings
from database import close_client, get_collection, guild_db_context, set_current_guild_id
from interactions.admin_portal import post_admin_portal
from interactions.coach_portal import post_coach_portal
from interactions.fc25_stats_modals import refresh_fc25_stats_for_user
from interactions.listing_instructions import post_listing_channel_instructions
from interactions.manager_portal import post_manager_portal
from interactions.premium_coaches_report import post_premium_coaches_report
from interactions.recruit_portal import post_recruit_portal
from migrations import apply_migrations
from services.channel_setup_service import cleanup_staff_monitor_channel, ensure_offside_channels
from services.error_reporting_service import capture_exception, init_error_reporting
from services.fc25_stats_feature import fc25_stats_enabled
from services.fc25_stats_service import list_links
from services.guild_config_service import get_guild_config, set_guild_config
from services.guild_install_service import (
    ensure_guild_install_indexes,
    mark_guild_install,
    refresh_guild_installs,
)
from services.heartbeat_service import upsert_worker_heartbeat
from services.recovery_service import run_startup_recovery
from services.role_setup_service import ensure_offside_roles
from services.scheduler import Scheduler
from services.subscription_service import ensure_subscription_indexes
from utils.access_control import enforce_paid_access
from utils.command_registry import validate_command_tree
from utils.discord_wrappers import fetch_channel, send_message
from utils.errors import log_interaction_error, new_error_id, send_interaction_error
from utils.flags import feature_enabled
from utils.logging import log_command_event
from utils.metrics import now_ms, record_command
from utils.moderation import enforce_safe_inputs
from utils.permissions import enforce_command_permissions

LOG_FORMAT = "%(asctime)s level=%(levelname)s name=%(name)s msg=\"%(message)s\""
LOG_CHANNEL_FORMAT = "%(levelname)s %(name)s: %(message)s"
MAX_LOG_MESSAGE_LENGTH = 1800

BotLike: TypeAlias = commands.Bot | commands.AutoShardedBot


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.captureWarnings(True)


def install_excepthook() -> None:
    def _hook(exc_type, exc_value, exc_traceback):
        logging.error(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        if isinstance(exc_value, BaseException):
            capture_exception(exc_value)
    sys.excepthook = _hook


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    def _handle(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        msg = context.get("message", "Asyncio task exception")
        exc = context.get("exception")
        logging.error("%s", msg, exc_info=exc)
        if isinstance(exc, BaseException):
            capture_exception(exc)
    loop.set_exception_handler(_handle)


def install_signal_handlers(bot: BotLike) -> None:
    """
    Install SIGTERM/SIGINT handlers to trigger a graceful shutdown.
    """
    try:
        loop = asyncio.get_running_loop()

        def _request_close() -> None:
            asyncio.create_task(bot.close())

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _request_close)
    except (NotImplementedError, RuntimeError):
        logging.debug("Signal handlers not installed on this platform.")


async def mark_command_start(interaction: discord.Interaction) -> bool:
    """
    Tree check that timestamps the start of a command for latency metrics.
    """
    if getattr(interaction, "_started_at_ms", None) is None:
        setattr(interaction, "_started_at_ms", now_ms())
    return True


async def set_guild_db_context(interaction: discord.Interaction) -> bool:
    """
    Bind the current task to the interaction's guild for per-guild database routing.
    """
    set_current_guild_id(interaction.guild_id)
    return True


class DiscordLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(("discord", "asyncio"))


class DiscordLogHandler(logging.Handler):
    def __init__(self, bot: BotLike) -> None:
        super().__init__(level=logging.INFO)
        self.bot = bot
        self._channel: discord.abc.Messageable | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if not getattr(self.bot, "test_mode", False):
            return
        channel_id = getattr(self.bot, "staff_monitor_channel_id", None)
        if not channel_id:
            return
        try:
            message = self.format(record)
        except Exception:
            return
        if len(message) > MAX_LOG_MESSAGE_LENGTH:
            message = f"{message[:MAX_LOG_MESSAGE_LENGTH]}..."
        loop = self.bot.loop
        if loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._send(message), loop)

    async def _send(self, message: str) -> None:
        if not getattr(self.bot, "test_mode", False):
            return
        channel_id = getattr(self.bot, "staff_monitor_channel_id", None)
        if not channel_id:
            return
        channel = self._channel
        if channel is None or getattr(channel, "id", None) != channel_id:
            channel = await fetch_channel(self.bot, channel_id)
            self._channel = channel
        if channel:
            await send_message(channel, f"```{message}```")


def attach_discord_log_handler(bot: BotLike) -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, DiscordLogHandler):
            return
    handler = DiscordLogHandler(bot)
    handler.setFormatter(logging.Formatter(LOG_CHANNEL_FORMAT))
    handler.addFilter(DiscordLogFilter())
    root_logger.addHandler(handler)


async def load_cogs(bot: BotLike) -> None:
    try:
        import cogs
    except Exception:
        logging.info("No cogs package found; skipping cog loading.")
        return

    for module in pkgutil.iter_modules(cogs.__path__, cogs.__name__ + "."):
        try:
            await bot.load_extension(module.name)
            logging.info("Loaded cog %s", module.name)
        except Exception:
            logging.exception("Failed to load cog %s", module.name)


class OffsideCommandTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        for check in (
            set_guild_db_context,
            enforce_paid_access,
            mark_command_start,
            enforce_safe_inputs,
            enforce_command_permissions,
        ):
            try:
                ok = await check(interaction)
            except Exception:
                ok = False
            if not ok:
                return False
        return True


class OffsideBot(commands.AutoShardedBot):
    settings: Settings
    test_mode: bool
    staff_monitor_channel_id: int | None
    scheduler: Scheduler

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scheduler = Scheduler()
        self._auto_setup_lock = asyncio.Lock()

    async def post_portals(self, *, guilds: list[discord.Guild] | None = None) -> None:
        try:
            await post_admin_portal(self, guilds=guilds)
            logging.info("Posted admin/staff portal embed.")
        except Exception:
            logging.exception("Failed to post admin portal.")
        await asyncio.sleep(0.5)
        try:
            await post_manager_portal(self, guilds=guilds)
            logging.info("Posted managers portal embed.")
        except Exception:
            logging.exception("Failed to post managers portal.")
        await asyncio.sleep(0.5)
        try:
            await post_coach_portal(self, guilds=guilds)
            logging.info("Posted coach portal embed.")
        except Exception:
            logging.exception("Failed to post coach portal.")
        await asyncio.sleep(0.5)
        try:
            await post_recruit_portal(self, guilds=guilds)
            logging.info("Posted recruit portal embed.")
        except Exception:
            logging.exception("Failed to post recruit portal.")
        await asyncio.sleep(0.5)
        try:
            await post_premium_coaches_report(self, guilds=guilds)
            logging.info("Posted pro coaches report embed.")
        except Exception:
            logging.exception("Failed to post pro coaches report.")
        await asyncio.sleep(0.5)
        try:
            await post_listing_channel_instructions(self, guilds=guilds)
            logging.info("Posted listing channel instruction embeds.")
        except Exception:
            logging.exception("Failed to post listing channel instruction embeds.")

    async def _auto_setup_guild(self, guild: discord.Guild) -> None:
        settings = getattr(self, "settings", None)
        if settings is None:
            return
        if not settings.mongodb_uri:
            logging.warning("Auto-setup skipped (guild=%s): MongoDB not configured.", guild.id)
            return

        bot_user = self.user
        if bot_user and guild.me is None:
            try:
                await guild.fetch_member(bot_user.id)
            except discord.DiscordException:
                pass

        me = guild.me
        if me is None:
            logging.warning("Auto-setup skipped (guild=%s): bot member unavailable.", guild.id)
            return

        test_mode = bool(getattr(self, "test_mode", False))
        actions: list[str] = []

        with guild_db_context(guild.id):
            if settings.mongodb_per_guild_db:
                try:
                    latest = apply_migrations(settings=settings, logger=logging.getLogger(__name__))
                    logging.info("Schema migrations complete (guild=%s; version=%s).", guild.id, latest)
                except Exception:
                    logging.exception("Auto-setup skipped (guild=%s): migrations failed.", guild.id)
                    return
                try:
                    run_startup_recovery(logger=logging.getLogger(__name__))
                except Exception:
                    logging.exception("Auto-setup (guild=%s): startup recovery failed.", guild.id)

            try:
                collection = get_collection(settings, record_type="guild_settings", guild_id=guild.id)
            except Exception:
                logging.exception(
                    "Auto-setup skipped (guild=%s): failed to connect to MongoDB.",
                    guild.id,
                )
                return

        existing: dict[str, Any] = {}
        try:
            existing = get_guild_config(guild.id, collection=collection)
        except Exception:
            logging.exception("Auto-setup (guild=%s): failed to load guild config.", guild.id)

        updated: dict[str, Any] = dict(existing)

        if me.guild_permissions.manage_roles:
            try:
                updated = await ensure_offside_roles(
                    guild,
                    settings=settings,
                    existing_config=updated,
                    actions=actions,
                )
            except discord.DiscordException:
                logging.exception("Auto-setup (guild=%s): role setup failed.", guild.id)
        else:
            actions.append("Role setup skipped (missing Manage Roles permission).")

        if me.guild_permissions.manage_channels:
            try:
                updated, channel_actions = await ensure_offside_channels(
                    guild,
                    settings=settings,
                    existing_config=updated,
                    test_mode=test_mode,
                )
                actions.extend(channel_actions)
            except discord.DiscordException:
                logging.exception("Auto-setup (guild=%s): channel setup failed.", guild.id)
        else:
            actions.append("Channel setup skipped (missing Manage Channels permission).")

        if updated != existing:
            try:
                set_guild_config(guild.id, updated, source="auto_setup", collection=collection)
            except Exception:
                logging.exception("Auto-setup (guild=%s): failed to persist guild config.", guild.id)

        for action in actions:
            logging.info("Auto-setup (guild=%s): %s", guild.id, action)

        if test_mode:
            staff_monitor = updated.get("channel_staff_monitor_id")
            if isinstance(staff_monitor, int) and not getattr(self, "staff_monitor_channel_id", None):
                self.staff_monitor_channel_id = staff_monitor

    async def _auto_setup_all_guilds(self) -> None:
        if getattr(self, "_auto_setup_done", False):
            return
        async with self._auto_setup_lock:
            if getattr(self, "_auto_setup_done", False):
                return
            for guild in list(self.guilds):
                await self._auto_setup_guild(guild)
                await asyncio.sleep(0.25)
            self._auto_setup_done = True

    async def _cleanup_test_mode_channels(self) -> None:
        if getattr(self, "test_mode", False):
            return
        settings = getattr(self, "settings", None)
        if settings is None or not settings.mongodb_uri:
            return
        for guild in self.guilds:
            me = guild.me
            if me is None or not me.guild_permissions.manage_channels:
                continue

            try:
                collection = get_collection(settings, record_type="guild_settings", guild_id=guild.id)
            except Exception:
                continue
            existing = {}
            try:
                existing = get_guild_config(guild.id, collection=collection)
            except Exception:
                continue
            if not existing.get("channel_staff_monitor_id"):
                continue
            updated, actions = await cleanup_staff_monitor_channel(
                guild,
                existing_config=existing,
            )
            for action in actions:
                logging.info("Test-mode cleanup (guild=%s): %s", guild.id, action)
            if updated != existing:
                try:
                    set_guild_config(guild.id, updated, source="test_mode_cleanup", collection=collection)
                except Exception:
                    logging.exception("Failed to persist guild cleanup (guild=%s).", guild.id)

    async def setup_hook(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            install_asyncio_exception_handler(loop)
            install_signal_handlers(self)
        except RuntimeError:
            logging.debug("Asyncio loop not ready for handlers yet.")
        await load_cogs(self)
        attach_discord_log_handler(self)
        try:
            await self.tree.sync()
            logging.info("Synced app commands.")
            validate_command_tree(self)
        except Exception:
            logging.exception("Failed to sync app commands.")
        await self._start_scheduler()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        settings = getattr(self, "settings", None)
        if settings is not None and settings.mongodb_uri:
            try:
                mark_guild_install(settings, guild_id=guild.id, installed=True, guild_name=guild.name)
            except Exception:
                logging.exception("Failed to record guild install (guild=%s).", guild.id)
        async with self._auto_setup_lock:
            await self._auto_setup_guild(guild)
        try:
            await self.post_portals(guilds=[guild])
        except Exception:
            logging.exception("Failed to post portals on guild join (guild=%s).", guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        settings = getattr(self, "settings", None)
        if settings is not None and settings.mongodb_uri:
            try:
                mark_guild_install(settings, guild_id=guild.id, installed=False, guild_name=guild.name)
            except Exception:
                logging.exception("Failed to record guild removal (guild=%s).", guild.id)

    async def on_ready(self) -> None:
        user = self.user
        if user:
            logging.info("Bot ready as %s (ID: %s).", user, user.id)
        else:
            logging.info("Bot ready (user not available yet).")
        try:
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="Offside dashboards",
                ),
            )
        except discord.DiscordException:
            pass
        settings = getattr(self, "settings", None)
        if settings is not None and settings.mongodb_uri:
            try:
                refresh_guild_installs(
                    settings,
                    guilds=[(g.id, g.name) for g in self.guilds],
                )
            except Exception:
                logging.exception("Failed to refresh guild install status.")
        await self._auto_setup_all_guilds()
        if not getattr(self, "_test_mode_cleanup_done", False):
            await self._cleanup_test_mode_channels()
            self._test_mode_cleanup_done = True
        if not getattr(self, "_portals_posted", False):
            await self.post_portals()
            self._portals_posted = True

    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: discord.app_commands.Command
    ) -> None:
        duration_ms = None
        started = getattr(interaction, "_started_at_ms", None)
        if started is not None:
            duration_ms = now_ms() - started
        log_command_event(interaction, status="completed")
        record_command(command.qualified_name, status="ok", duration_ms=duration_ms)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        error_id = new_error_id()
        log_interaction_error(error, interaction, source="app_command", error_id=error_id)
        capture_exception(error, guild_id=interaction.guild_id)
        try:
            command_name = interaction.command.qualified_name if interaction.command else "unknown"
            record_command(command_name, status="error")
        except Exception:
            logging.debug("Failed to record command error metric.")
        await send_interaction_error(interaction, error_id=error_id)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:  # type: ignore[override]
        logging.error("Unhandled error in event %s", event_method, exc_info=sys.exc_info())
        exc = sys.exc_info()[1]
        if isinstance(exc, BaseException):
            capture_exception(exc)

    async def _start_scheduler(self) -> None:
        settings = getattr(self, "settings", None)
        if settings is not None and settings.mongodb_uri:
            async def heartbeat() -> None:
                upsert_worker_heartbeat(settings, worker="bot")
            try:
                self.scheduler.add_job("worker_heartbeat", 30.0, heartbeat)
            except RuntimeError:
                pass
            try:
                from services.ops_tasks_service import ensure_ops_task_indexes

                ensure_ops_task_indexes(settings)
            except Exception:
                logging.exception("Failed to ensure ops task indexes.")
            try:
                self.scheduler.add_job("ops_tasks", 3.0, self._ops_tasks_job)
            except RuntimeError:
                pass
        if feature_enabled("metrics_log", settings):
            async def log_metrics():
                return None
            try:
                self.scheduler.add_job("metrics_log", 300.0, log_metrics)
            except RuntimeError:
                pass
        if feature_enabled("fc25_stats", settings):
            try:
                self.scheduler.add_job("fc25_refresh", 1800.0, self._fc25_refresh_job)
            except RuntimeError:
                pass
        await self.scheduler.start()

    async def _ops_tasks_job(self) -> None:
        settings = getattr(self, "settings", None)
        if settings is None or not settings.mongodb_uri:
            return
        if not self.is_ready():
            return

        from services.audit_log_service import record_audit_event
        from services.ops_tasks_service import (
            OPS_TASK_ACTION_DELETE_GUILD_DATA,
            OPS_TASK_ACTION_REPOST_PORTALS,
            OPS_TASK_ACTION_RUN_SETUP,
            claim_next_ops_task,
            mark_ops_task_failed,
            mark_ops_task_succeeded,
        )

        task = claim_next_ops_task(settings, worker="bot")
        if not task:
            return

        task_id = str(task.get("_id") or "")
        guild_id_raw = task.get("guild_id")
        guild_id = int(guild_id_raw) if isinstance(guild_id_raw, int) else 0
        action = str(task.get("action") or "").strip().lower()

        if not task_id or not guild_id:
            return

        write_guild_audit = action != OPS_TASK_ACTION_DELETE_GUILD_DATA

        if write_guild_audit:
            try:
                audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
                record_audit_event(
                    guild_id=guild_id,
                    category="ops",
                    action="ops_task.started",
                    source="worker",
                    details={"task_id": task_id, "task_action": action},
                    collection=audit_col,
                )
            except Exception:
                pass

        try:
            if action == OPS_TASK_ACTION_RUN_SETUP:
                guild = self.get_guild(guild_id)
                if guild is None:
                    raise RuntimeError("Bot is not in this guild.")
                async with self._auto_setup_lock:
                    await self._auto_setup_guild(guild)
                result = {"message": "Auto-setup complete."}
            elif action == OPS_TASK_ACTION_REPOST_PORTALS:
                guild = self.get_guild(guild_id)
                if guild is None:
                    raise RuntimeError("Bot is not in this guild.")
                await self.post_portals(guilds=[guild])
                result = {"message": "Portals reposted."}
            elif action == OPS_TASK_ACTION_DELETE_GUILD_DATA:
                from services.guild_data_service import delete_guild_data

                result = delete_guild_data(settings, guild_id=guild_id)
            else:
                raise RuntimeError(f"Unknown ops action: {action}")

            mark_ops_task_succeeded(settings, task_id=task_id, result=result)
            if write_guild_audit:
                try:
                    audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
                    record_audit_event(
                        guild_id=guild_id,
                        category="ops",
                        action="ops_task.completed",
                        source="worker",
                        details={"task_id": task_id, "task_action": action, "result": result},
                        collection=audit_col,
                    )
                except Exception:
                    pass
        except Exception as exc:
            mark_ops_task_failed(settings, task_id=task_id, error=str(exc))
            if write_guild_audit:
                try:
                    audit_col = get_collection(settings, record_type="audit_event", guild_id=guild_id)
                    record_audit_event(
                        guild_id=guild_id,
                        category="ops",
                        action="ops_task.failed",
                        source="worker",
                        details={"task_id": task_id, "task_action": action, "error": str(exc)},
                        collection=audit_col,
                    )
                except Exception:
                    pass

    async def _fc25_refresh_job(self) -> None:
        from datetime import datetime, timezone

        settings = getattr(self, "settings", None)
        if settings is None:
            return
        if not settings.mongodb_uri:
            return

        min_age_seconds = max(300, int(settings.fc25_stats_cache_ttl_seconds))
        max_per_guild = max(1, min(10, int(settings.fc25_stats_rate_limit_per_guild) // 2))
        now = datetime.now(timezone.utc)
        test_mode = bool(getattr(self, "test_mode", False))

        for guild in self.guilds:
            if not fc25_stats_enabled(settings, guild_id=guild.id):
                continue
            try:
                collection = get_collection(settings, record_type="fc25_stats_link", guild_id=guild.id)
            except Exception:
                continue
            try:
                links = list_links(guild.id, verified_only=True, limit=200, collection=collection)
            except Exception:
                continue

            refreshed = 0
            for link in links:
                if refreshed >= max_per_guild:
                    break
                user_id = link.get("user_id")
                if not isinstance(user_id, int):
                    continue
                last = link.get("last_fetched_at")
                if isinstance(last, datetime):
                    age = (now - last).total_seconds()
                    if age < min_age_seconds:
                        continue
                try:
                    status = await refresh_fc25_stats_for_user(
                        self,
                        settings,
                        guild_id=guild.id,
                        user_id=user_id,
                        test_mode=test_mode,
                        reason="scheduled",
                    )
                except Exception:
                    logging.exception(
                        "FC25 scheduled refresh failed (guild=%s user=%s).",
                        guild.id,
                        user_id,
                    )
                    continue
                if status == "feature_disabled":
                    continue
                if status in {"refreshed", "cached"}:
                    refreshed += 1

    async def close(self) -> None:
        try:
            await self.scheduler.stop()
        except Exception:
            logging.exception("Scheduler stop failed.")
        await super().close()


def build_bot(settings: Settings) -> OffsideBot:
    intents = discord.Intents.default()
    # Keep privileged intents disabled until explicitly needed.

    bot = OffsideBot(
        command_prefix="!",
        intents=intents,
        application_id=settings.discord_application_id,
        shard_count=settings.shard_count if settings.use_sharding else None,
        tree_cls=OffsideCommandTree,
    )
    bot.settings = settings
    bot.test_mode = settings.test_mode
    bot.staff_monitor_channel_id = settings.channel_staff_monitor_id
    return bot


def register_commands(bot: OffsideBot) -> None:
    @bot.tree.command(name="ping", description="Check bot responsiveness.")
    async def ping(interaction: discord.Interaction) -> None:
        if getattr(interaction, "_started_at_ms", None) is None:
            setattr(interaction, "_started_at_ms", now_ms())
        await interaction.response.send_message("pong", ephemeral=True)


def main() -> None:
    setup_logging()
    settings: Settings
    try:
        settings = load_settings()
    except RuntimeError as exc:
        logging.error("Configuration error: %s", exc)
        raise
    init_error_reporting(settings=settings, service_name="bot")
    install_excepthook()
    logging.info("Loaded configuration (non-secret): %s", summarize_settings(settings))
    if settings.mongodb_uri:
        try:
            ensure_subscription_indexes(settings)
            ensure_guild_install_indexes(settings)
        except Exception:
            logging.exception("Failed to ensure database indexes.")
            raise
    if settings.mongodb_per_guild_db:
        logging.info(
            "Per-guild MongoDB mode enabled; migrations/recovery will run per guild on startup/join."
        )
    else:
        # Run migrations and recovery before starting the bot (shared DB mode).
        try:
            latest = apply_migrations(settings=settings, logger=logging.getLogger(__name__))
            logging.info("Schema migrations complete; current version %s.", latest)
        except Exception:
            logging.exception("Failed during migrations.")
            raise
        try:
            run_startup_recovery(logger=logging.getLogger(__name__))
        except Exception:
            logging.exception("Startup recovery encountered an error.")
            raise

    bot = build_bot(settings)
    register_commands(bot)

    try:
        bot.run(settings.discord_token)
    except KeyboardInterrupt:
        logging.info("Shutdown requested, exiting.")
    except Exception:
        logging.exception("Bot exited with an error.")
        raise
    finally:
        logging.info("Bot shutdown complete.")
        close_client()


if __name__ == "__main__":
    main()
