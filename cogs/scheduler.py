"""
cogs/scheduler.py – Personal reminders and scheduled announcements.
Persists to data/reminders.json so they survive restarts.
Supports: 10m, 2h, 1d, 14:30 (next occurrence), tomorrow, etc.
"""
import json
import os
import re
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import nextcord
from nextcord.ext import commands, tasks
from config import Config

log = logging.getLogger("vector.scheduler")

DATA_DIR = Path("data")
REMINDERS_FILE = DATA_DIR / "reminders.json"

# Time parsing patterns
RELATIVE_RE = re.compile(r"^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)$", re.IGNORECASE)
CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_time(time_str: str) -> timedelta | datetime | None:
    """Parse a time string into a timedelta (relative) or datetime (absolute)."""
    time_str = time_str.strip()

    # Relative: 10m, 2h, 1d, 1w
    match = RELATIVE_RE.match(time_str)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)[0].lower()
        if unit == "m":
            return timedelta(minutes=amount)
        elif unit == "h":
            return timedelta(hours=amount)
        elif unit == "d":
            return timedelta(days=amount)
        elif unit == "w":
            return timedelta(weeks=amount)

    # Absolute: 14:30
    match = CLOCK_RE.match(time_str)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)  # Next occurrence
        return target

    return None


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminders: list[dict] = []
        self._load_reminders()
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    # ── Persistence ───────────────────────────────────────────────────

    def _load_reminders(self):
        DATA_DIR.mkdir(exist_ok=True)
        if REMINDERS_FILE.exists():
            try:
                with open(REMINDERS_FILE, "r") as f:
                    self.reminders = json.load(f)
                log.info(f"Loaded {len(self.reminders)} reminders")
            except Exception as e:
                log.error(f"Failed to load reminders: {e}")
                self.reminders = []

    def _save_reminders(self):
        DATA_DIR.mkdir(exist_ok=True)
        with open(REMINDERS_FILE, "w") as f:
            json.dump(self.reminders, f, indent=2)

    # ── Reminder checker (runs every 15 seconds) ─────────────────────

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        now = datetime.now().timestamp()
        due = [r for r in self.reminders if r["due"] <= now]

        for reminder in due:
            try:
                channel = self.bot.get_channel(reminder["channel_id"])
                if channel:
                    if reminder.get("type") == "announce":
                        await channel.send(f"**Scheduled Announcement:**\n{reminder['message']}")
                    else:
                        user = self.bot.get_user(reminder["user_id"])
                        mention = user.mention if user else f"<@{reminder['user_id']}>"
                        await channel.send(f"⏰ {mention} Reminder: **{reminder['message']}**")
            except Exception as e:
                log.error(f"Failed to deliver reminder: {e}")

            self.reminders.remove(reminder)

        if due:
            self._save_reminders()

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── /remindme ─────────────────────────────────────────────────────

    def _create_reminder(self, user_id: int, channel_id: int, time_str: str, message: str) -> str:
        parsed = parse_time(time_str)
        if parsed is None:
            return "Invalid time format. Use `10m`, `2h`, `1d`, `14:30`, etc."

        if isinstance(parsed, timedelta):
            due = datetime.now() + parsed
        else:
            due = parsed

        self.reminders.append({
            "user_id": user_id,
            "channel_id": channel_id,
            "message": message,
            "due": due.timestamp(),
            "type": "reminder",
            "created": datetime.now().isoformat(),
        })
        self._save_reminders()

        due_str = due.strftime("%b %d at %I:%M %p")
        return f"Got it! I'll remind you on **{due_str}**: {message}"

    @nextcord.slash_command(name="remindme", description="Set a personal reminder", guild_ids=Config.GUILD_IDS)
    async def remindme_slash(self, interaction: nextcord.Interaction, time: str, message: str):
        result = self._create_reminder(interaction.user.id, interaction.channel_id, time, message)
        await interaction.response.send_message(result, ephemeral=True)

    @commands.command(name="remindme")
    async def remindme_cmd(self, ctx, time: str, *, message: str):
        result = self._create_reminder(ctx.author.id, ctx.channel.id, time, message)
        await ctx.reply(result)

    # ── /announce ─────────────────────────────────────────────────────

    def _create_announcement(self, user_id: int, channel_id: int, time_str: str, message: str) -> str:
        if user_id not in Config.OWNER_IDS:
            return "Only bot admins can schedule announcements."

        parsed = parse_time(time_str)
        if parsed is None:
            return "Invalid time format. Use `10m`, `2h`, `1d`, `14:30`, etc."

        if isinstance(parsed, timedelta):
            due = datetime.now() + parsed
        else:
            due = parsed

        self.reminders.append({
            "user_id": user_id,
            "channel_id": channel_id,
            "message": message,
            "due": due.timestamp(),
            "type": "announce",
            "created": datetime.now().isoformat(),
        })
        self._save_reminders()

        due_str = due.strftime("%b %d at %I:%M %p")
        return f"Announcement scheduled for **{due_str}**"

    @nextcord.slash_command(name="announce", description="Schedule a channel announcement", guild_ids=Config.GUILD_IDS)
    async def announce_slash(self, interaction: nextcord.Interaction, time: str, message: str):
        result = self._create_announcement(interaction.user.id, interaction.channel_id, time, message)
        await interaction.response.send_message(result, ephemeral=True)

    @commands.command(name="announce")
    async def announce_cmd(self, ctx, time: str, *, message: str):
        result = self._create_announcement(ctx.author.id, ctx.channel.id, time, message)
        await ctx.reply(result)

    # ── /reminders ────────────────────────────────────────────────────

    def _list_reminders(self, user_id: int) -> nextcord.Embed:
        user_reminders = [r for r in self.reminders if r["user_id"] == user_id]

        embed = nextcord.Embed(title="Your Reminders", color=0x5865F2)
        if not user_reminders:
            embed.description = "You have no active reminders."
            return embed

        for i, r in enumerate(user_reminders, 1):
            due = datetime.fromtimestamp(r["due"]).strftime("%b %d at %I:%M %p")
            rtype = "📢" if r.get("type") == "announce" else "⏰"
            embed.add_field(
                name=f"#{i} {rtype} {due}",
                value=r["message"][:100],
                inline=False,
            )
        return embed

    @nextcord.slash_command(name="reminders", description="List your active reminders", guild_ids=Config.GUILD_IDS)
    async def reminders_slash(self, interaction: nextcord.Interaction):
        embed = self._list_reminders(interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="reminders")
    async def reminders_cmd(self, ctx):
        embed = self._list_reminders(ctx.author.id)
        await ctx.reply(embed=embed)

    # ── /cancelreminder ───────────────────────────────────────────────

    def _cancel_reminder(self, user_id: int, number: int) -> str:
        user_reminders = [r for r in self.reminders if r["user_id"] == user_id]
        if number < 1 or number > len(user_reminders):
            return f"Invalid reminder number. You have {len(user_reminders)} reminder(s)."

        target = user_reminders[number - 1]
        self.reminders.remove(target)
        self._save_reminders()
        return f"Cancelled reminder #{number}: {target['message'][:50]}"

    @nextcord.slash_command(name="cancelreminder", description="Cancel a reminder by number", guild_ids=Config.GUILD_IDS)
    async def cancel_slash(self, interaction: nextcord.Interaction, number: int):
        result = self._cancel_reminder(interaction.user.id, number)
        await interaction.response.send_message(result, ephemeral=True)

    @commands.command(name="cancelreminder")
    async def cancel_cmd(self, ctx, number: int):
        result = self._cancel_reminder(ctx.author.id, number)
        await ctx.reply(result)


def setup(bot):
    bot.add_cog(Scheduler(bot))
