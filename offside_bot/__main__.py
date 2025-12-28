import logging
import pkgutil

import discord
from discord.ext import commands

from config import Settings, load_settings
from utils.errors import log_interaction_error, send_interaction_error

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


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
