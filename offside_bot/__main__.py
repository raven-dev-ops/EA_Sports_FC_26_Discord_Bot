import logging
import os
import pkgutil

import discord
from discord.ext import commands


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def get_env(name: str, *, required: bool = False, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"{name} is required.")
    return value


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


def build_bot() -> OffsideBot:
    intents = discord.Intents.default()
    # Keep privileged intents disabled until explicitly needed.

    application_id_raw = get_env("DISCORD_APPLICATION_ID")
    application_id = int(application_id_raw) if application_id_raw else None

    return OffsideBot(command_prefix="!", intents=intents, application_id=application_id)


bot = build_bot()


@bot.tree.command(name="ping", description="Check bot responsiveness.")
async def ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("pong", ephemeral=True)


def main() -> None:
    setup_logging()
    token = get_env("DISCORD_TOKEN", required=True)
    try:
        bot.run(token)
    except KeyboardInterrupt:
        logging.info("Shutdown requested, exiting.")
    except Exception:
        logging.exception("Bot exited with an error.")
        raise
    finally:
        logging.info("Bot shutdown complete.")


if __name__ == "__main__":
    main()
