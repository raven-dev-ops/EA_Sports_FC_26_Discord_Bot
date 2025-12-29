import asyncio
import logging
import os
import pkgutil
import signal
import sys

import discord
from discord.ext import commands

from config import Settings, load_settings
from config.settings import summarize_settings
from database import close_client
from interactions.admin_portal import post_admin_portal
from interactions.coach_portal import post_coach_portal
from migrations import apply_migrations
from services.recovery_service import run_startup_recovery
from services.scheduler import Scheduler
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
    sys.excepthook = _hook


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    def _handle(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        msg = context.get("message", "Asyncio task exception")
        exc = context.get("exception")
        logging.error("%s", msg, exc_info=exc)
    loop.set_exception_handler(_handle)


def install_signal_handlers(bot: commands.Bot) -> None:
    """
    Install SIGTERM/SIGINT handlers to trigger a graceful shutdown.
    """
    try:
        loop = bot.loop
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(bot.close()))
    except (NotImplementedError, RuntimeError):
        logging.debug("Signal handlers not installed on this platform.")


async def mark_command_start(interaction: discord.Interaction) -> bool:
    """
    Tree check that timestamps the start of a command for latency metrics.
    """
    if not hasattr(interaction, "_started_at_ms"):
        interaction._started_at_ms = now_ms()
    return True


class DiscordLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(("discord", "asyncio"))


class DiscordLogHandler(logging.Handler):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(level=logging.INFO)
        self.bot = bot
        self._channel: discord.abc.Messageable | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if not getattr(self.bot, "test_mode", False):
            return
        channel_id = getattr(self.bot, "test_channel_id", None)
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
        channel_id = getattr(self.bot, "test_channel_id", None)
        if not channel_id:
            return
        channel = self._channel
        if channel is None or getattr(channel, "id", None) != channel_id:
            channel = await fetch_channel(self.bot, channel_id)
            self._channel = channel
        if channel:
            await send_message(channel, f"```{message}```")


def attach_discord_log_handler(bot: commands.Bot) -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, DiscordLogHandler):
            return
    handler = DiscordLogHandler(bot)
    handler.setFormatter(logging.Formatter(LOG_CHANNEL_FORMAT))
    handler.addFilter(DiscordLogFilter())
    root_logger.addHandler(handler)


async def load_cogs(bot: commands.Bot) -> None:
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


class OffsideBot(commands.AutoShardedBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scheduler = Scheduler()

    async def post_portals(self) -> None:
        try:
            await post_admin_portal(self)
            logging.info("Posted admin/staff portal embed.")
        except Exception:
            logging.exception("Failed to post admin portal.")
        await asyncio.sleep(0.5)
        try:
            await post_coach_portal(self)
            logging.info("Posted coach portal embed.")
        except Exception:
            logging.exception("Failed to post coach portal.")

    async def setup_hook(self) -> None:
        await load_cogs(self)
        attach_discord_log_handler(self)
        # Global permission guard
        self.tree.add_check(mark_command_start)
        self.tree.add_check(enforce_safe_inputs)
        self.tree.add_check(enforce_command_permissions)
        try:
            await self.tree.sync()
            logging.info("Synced app commands.")
            validate_command_tree(self)
        except Exception:
            logging.exception("Failed to sync app commands.")
        await self._start_scheduler()

    async def on_ready(self) -> None:
        user = self.user
        if user:
            logging.info("Bot ready as %s (ID: %s).", user, user.id)
        else:
            logging.info("Bot ready (user not available yet).")
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
        try:
            command_name = interaction.command.qualified_name if interaction.command else "unknown"
            record_command(command_name, status="error")
        except Exception:
            logging.debug("Failed to record command error metric.")
        await send_interaction_error(interaction, error_id=error_id)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:  # type: ignore[override]
        logging.error("Unhandled error in event %s", event_method, exc_info=sys.exc_info())

    async def _start_scheduler(self) -> None:
        settings = getattr(self, "settings", None)
        if feature_enabled("metrics_log", settings):
            async def log_metrics():
                return None
            try:
                self.scheduler.add_job("metrics_log", 300.0, log_metrics)
            except RuntimeError:
                pass
        await self.scheduler.start()

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
    )
    bot.settings = settings
    bot.test_mode = settings.test_mode
    bot.test_channel_id = settings.discord_test_channel_id
    install_asyncio_exception_handler(bot.loop)
    return bot


def register_commands(bot: OffsideBot) -> None:
    @bot.tree.command(name="ping", description="Check bot responsiveness.")
    async def ping(interaction: discord.Interaction) -> None:
        interaction._started_at_ms = getattr(interaction, "_started_at_ms", now_ms())
        await interaction.response.send_message("pong", ephemeral=True)


def main() -> None:
    setup_logging()
    install_excepthook()
    settings: Settings
    try:
        settings = load_settings()
    except RuntimeError as exc:
        logging.error("Configuration error: %s", exc)
        raise
    logging.info("Loaded configuration (non-secret): %s", summarize_settings(settings))
    # Run migrations and recovery before starting the bot.
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
    install_signal_handlers(bot)
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
