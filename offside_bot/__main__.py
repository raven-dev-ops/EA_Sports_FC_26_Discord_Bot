import asyncio
import logging
import pkgutil

import discord
from discord.ext import commands

from config import Settings, load_settings
from utils.errors import log_interaction_error, send_interaction_error

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_CHANNEL_FORMAT = "%(levelname)s %(name)s: %(message)s"
MAX_LOG_MESSAGE_LENGTH = 1800


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


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
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except discord.DiscordException:
                    return
            self._channel = channel
        await channel.send(f"```{message}```")


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


class OffsideBot(commands.Bot):
    async def setup_hook(self) -> None:
        await load_cogs(self)
        attach_discord_log_handler(self)
        try:
            await self.tree.sync()
            logging.info("Synced app commands.")
        except Exception:
            logging.exception("Failed to sync app commands.")

    async def on_ready(self) -> None:
        user = self.user
        if user:
            logging.info("Bot ready as %s (ID: %s).", user, user.id)
        else:
            logging.info("Bot ready (user not available yet).")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        log_interaction_error(error, interaction, source="app_command")
        await send_interaction_error(interaction)


def build_bot(settings: Settings) -> OffsideBot:
    intents = discord.Intents.default()
    # Keep privileged intents disabled until explicitly needed.

    bot = OffsideBot(
        command_prefix="!",
        intents=intents,
        application_id=settings.discord_application_id,
    )
    bot.settings = settings
    bot.test_mode = settings.test_mode
    bot.test_channel_id = settings.discord_test_channel_id
    return bot


def register_commands(bot: OffsideBot) -> None:
    @bot.tree.command(name="ping", description="Check bot responsiveness.")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("pong", ephemeral=True)


def main() -> None:
    setup_logging()
    settings: Settings
    try:
        settings = load_settings()
    except RuntimeError as exc:
        logging.error("Configuration error: %s", exc)
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


if __name__ == "__main__":
    main()
