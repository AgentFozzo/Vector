"""
config.py – Loads settings from .env and exposes them as Config attributes.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Discord
    TOKEN = os.getenv("DISCORD_TOKEN", "")
    PREFIX = os.getenv("BOT_PREFIX", "!")
    GUILD_IDS = [int(g) for g in os.getenv("GUILD_IDS", "").split(",") if g.strip()]
    OWNER_IDS = [int(o) for o in os.getenv("OWNER_IDS", "").split(",") if o.strip() and o.strip() != "YOUR_OWNER_ID"]

    # Unraid SSH
    UNRAID_HOST = os.getenv("UNRAID_HOST", "")
    UNRAID_USER = os.getenv("UNRAID_USER", "root")
    UNRAID_PASS = os.getenv("UNRAID_PASS", "")

    # GitHub auto-update
    GITHUB_REPO = os.getenv("GITHUB_REPO", "")
    GITHUB_SECRET = os.getenv("GITHUB_SECRET", "")
    WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "9001"))
    POLL_INTERVAL_MINS = int(os.getenv("POLL_INTERVAL_MINS", "5"))
