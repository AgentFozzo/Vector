"""
config.py – Loads settings from .env and exposes them as Config attributes.
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("vector.config")


def _parse_int_list(raw: str, name: str) -> list[int]:
    """Safely parse a comma-separated list of integers from env."""
    result = []
    for item in raw.split(","):
        item = item.strip()
        if not item or item.startswith("YOUR_") or item.startswith("your_"):
            continue
        try:
            result.append(int(item))
        except ValueError:
            log.warning(f"Invalid integer in {name}: {item!r}")
    return result


def _parse_int(raw: str, default: int, name: str) -> int:
    """Safely parse a single integer from env."""
    try:
        return int(raw)
    except (ValueError, TypeError):
        log.warning(f"Invalid integer for {name}: {raw!r}, using default {default}")
        return default


class Config:
    # Discord
    TOKEN = os.getenv("DISCORD_TOKEN", "")
    PREFIX = os.getenv("BOT_PREFIX", "!")
    GUILD_IDS = _parse_int_list(os.getenv("GUILD_IDS", ""), "GUILD_IDS")
    OWNER_IDS = _parse_int_list(os.getenv("OWNER_IDS", ""), "OWNER_IDS")

    # Timezone (IANA format)
    TIMEZONE = os.getenv("TIMEZONE", "America/Chicago")

    # Unraid SSH
    UNRAID_HOST = os.getenv("UNRAID_HOST", "")
    UNRAID_USER = os.getenv("UNRAID_USER", "root")
    UNRAID_PASS = os.getenv("UNRAID_PASS", "")

    # TCG Suite
    TCG_SUITE_URL = os.getenv("TCG_SUITE_URL", "http://localhost:5000")
    SHIP_NOTIFY_CHANNEL = os.getenv("SHIP_NOTIFY_CHANNEL", "")
    SHIP_NOTIFY_HOUR = _parse_int(os.getenv("SHIP_NOTIFY_HOUR", "7"), 7, "SHIP_NOTIFY_HOUR")

    # Home Assistant
    HA_URL = os.getenv("HA_URL", "")
    HA_TOKEN = os.getenv("HA_TOKEN", "")

    # GitHub auto-update
    GITHUB_REPO = os.getenv("GITHUB_REPO", "")
    GITHUB_SECRET = os.getenv("GITHUB_SECRET", "")
    WEBHOOK_PORT = _parse_int(os.getenv("WEBHOOK_PORT", "9001"), 9001, "WEBHOOK_PORT")
    WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
    POLL_INTERVAL_MINS = _parse_int(os.getenv("POLL_INTERVAL_MINS", "5"), 5, "POLL_INTERVAL_MINS")
