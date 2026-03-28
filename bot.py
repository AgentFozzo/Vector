"""
bot.py – Vector Bot entry point.
Loads all cogs and starts the bot with both slash and prefix command support.
"""
import logging
import nextcord
from nextcord.ext import commands
from config import Config

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vector")

# ── Intents ──────────────────────────────────────────────────────────
intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True

# ── Bot instance ─────────────────────────────────────────────────────
bot = commands.Bot(
    command_prefix=Config.PREFIX,
    intents=intents,
    help_command=None,  # We provide our own /help
)

# ── Cogs to load ─────────────────────────────────────────────────────
INITIAL_COGS = [
    "cogs.admin",
    "cogs.monitor",
    "cogs.scheduler",
    "cogs.smart",
    "cogs.updater",
    "cogs.homeassistant",
]


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    log.info(f"Connected to {len(bot.guilds)} guild(s)")
    log.info(f"Slash commands registered for guild(s): {Config.GUILD_IDS}")
    await bot.change_presence(
        activity=nextcord.Activity(type=nextcord.ActivityType.watching, name="the server")
    )


def main():
    # Load cogs
    for cog in INITIAL_COGS:
        try:
            bot.load_extension(cog)
            log.info(f"Loaded cog: {cog}")
        except Exception as e:
            log.error(f"Failed to load cog {cog}: {e}")

    if not Config.TOKEN:
        log.error("DISCORD_TOKEN is not set! Check your .env file.")
        return

    bot.run(Config.TOKEN)


if __name__ == "__main__":
    main()
