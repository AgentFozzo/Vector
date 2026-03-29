"""
cogs/shipwatch.py – Monitors pending TCG Suite orders and alerts
when ship-by dates are approaching. Checks daily at a configured
hour (default 7 AM) and notifies the owner in a specified channel.

Fetches order data from the TCG Suite sync API (same server, port 5000).
"""
import logging
import asyncio
from datetime import datetime, timedelta, date

import nextcord
from nextcord.ext import commands, tasks
from config import Config

try:
    import aiohttp
except ImportError:
    aiohttp = None

log = logging.getLogger("vector.shipwatch")


class ShipWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session = None
        self._last_check_date = None  # Track so we only alert once per day
        self.daily_check.start()

    def cog_unload(self):
        self.daily_check.cancel()
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def _fetch_orders(self) -> list:
        """Fetch current orders from TCG Suite sync API."""
        session = await self._get_session()
        try:
            url = f"{Config.TCG_SUITE_URL}/api/sync/data"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("orders", [])
                log.error(f"TCG Suite API returned {resp.status}")
                return []
        except Exception as e:
            log.error(f"Failed to fetch orders from TCG Suite: {e}")
            return []

    def _get_notify_channel(self):
        """Get the notification channel. Uses config or falls back to first text channel in first guild."""
        if Config.SHIP_NOTIFY_CHANNEL:
            try:
                return self.bot.get_channel(int(Config.SHIP_NOTIFY_CHANNEL))
            except (ValueError, TypeError):
                pass
        # Fallback: first text channel the bot can send to in the first guild
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    return channel
        return None

    def _build_alert_embed(self, due_today: list, due_tomorrow: list, overdue: list) -> nextcord.Embed:
        """Build a shipping alert embed."""
        embed = nextcord.Embed(
            title="Shipping Alert",
            color=0xED4245 if overdue else 0xFEE75C,
            timestamp=datetime.now(),
        )
        embed.set_footer(text="Vector Ship Watch")

        if overdue:
            lines = []
            for o in overdue:
                cards = ", ".join(o.get("cards", [])) if isinstance(o.get("cards"), list) else str(o.get("cards", ""))
                lines.append(f"**{o.get('buyer', 'Unknown')}** — {cards[:60]} (due {o.get('shipByDate', '?')})")
            embed.add_field(
                name=f"🚨 OVERDUE ({len(overdue)})",
                value="\n".join(lines[:10]) or "None",
                inline=False,
            )

        if due_today:
            lines = []
            for o in due_today:
                cards = ", ".join(o.get("cards", [])) if isinstance(o.get("cards"), list) else str(o.get("cards", ""))
                platform = o.get("platform", "")
                lines.append(f"**{o.get('buyer', 'Unknown')}** ({platform}) — {cards[:60]}")
            embed.add_field(
                name=f"📦 Ship TODAY ({len(due_today)})",
                value="\n".join(lines[:10]) or "None",
                inline=False,
            )

        if due_tomorrow:
            lines = []
            for o in due_tomorrow:
                cards = ", ".join(o.get("cards", [])) if isinstance(o.get("cards"), list) else str(o.get("cards", ""))
                platform = o.get("platform", "")
                lines.append(f"**{o.get('buyer', 'Unknown')}** ({platform}) — {cards[:60]}")
            embed.add_field(
                name=f"⏰ Ship TOMORROW ({len(due_tomorrow)})",
                value="\n".join(lines[:10]) or "None",
                inline=False,
            )

        # Mention the owner
        description_parts = []
        for owner_id in Config.OWNER_IDS:
            description_parts.append(f"<@{owner_id}>")
        if description_parts:
            embed.description = " ".join(description_parts) + " — you have shipments that need attention."

        return embed

    # ── Daily check loop (runs every 10 minutes, sends once per day at configured hour) ──

    @tasks.loop(minutes=10)
    async def daily_check(self):
        now = datetime.now()
        today = now.date()

        # Only send once per day, at or after the configured hour
        if now.hour < Config.SHIP_NOTIFY_HOUR:
            return
        if self._last_check_date == today:
            return

        log.info("Running daily ship-by date check...")
        self._last_check_date = today

        orders = await self._fetch_orders()
        if not orders:
            log.info("No orders found or couldn't fetch.")
            return

        # Filter pending orders with ship-by dates
        pending = [o for o in orders if o.get("status") == "Pending" and o.get("shipByDate")]

        overdue = []
        due_today = []
        due_tomorrow = []
        tomorrow = today + timedelta(days=1)

        for o in pending:
            try:
                ship_date = date.fromisoformat(o["shipByDate"])
            except (ValueError, TypeError):
                continue

            if ship_date < today:
                overdue.append(o)
            elif ship_date == today:
                due_today.append(o)
            elif ship_date == tomorrow:
                due_tomorrow.append(o)

        # Only send if there's something to alert about
        if not overdue and not due_today and not due_tomorrow:
            log.info("No upcoming shipments to alert about.")
            return

        channel = self._get_notify_channel()
        if not channel:
            log.error("No notification channel found!")
            return

        embed = self._build_alert_embed(due_today, due_tomorrow, overdue)
        await channel.send(embed=embed)
        log.info(f"Sent shipping alert: {len(overdue)} overdue, {len(due_today)} today, {len(due_tomorrow)} tomorrow")

    @daily_check.before_loop
    async def before_daily_check(self):
        await self.bot.wait_until_ready()

    # ── Manual check command ──────────────────────────────────────────

    @nextcord.slash_command(name="shipcheck", description="Check pending orders with upcoming ship-by dates", guild_ids=Config.GUILD_IDS)
    async def shipcheck_slash(self, interaction: nextcord.Interaction):
        await interaction.response.defer()

        orders = await self._fetch_orders()
        if not orders:
            await interaction.followup.send("Unable to fetch orders from TCG Suite, or no orders found.")
            return

        pending = [o for o in orders if o.get("status") == "Pending" and o.get("shipByDate")]
        if not pending:
            await interaction.followup.send("No pending orders with ship-by dates. You're all caught up.")
            return

        today = date.today()
        tomorrow = today + timedelta(days=1)
        overdue = []
        due_today = []
        due_tomorrow = []
        upcoming = []

        for o in pending:
            try:
                ship_date = date.fromisoformat(o["shipByDate"])
            except (ValueError, TypeError):
                continue
            if ship_date < today:
                overdue.append(o)
            elif ship_date == today:
                due_today.append(o)
            elif ship_date == tomorrow:
                due_tomorrow.append(o)
            else:
                upcoming.append(o)

        embed = self._build_alert_embed(due_today, due_tomorrow, overdue)

        if upcoming:
            lines = []
            for o in sorted(upcoming, key=lambda x: x.get("shipByDate", "")):
                cards = ", ".join(o.get("cards", [])) if isinstance(o.get("cards"), list) else str(o.get("cards", ""))
                lines.append(f"**{o.get('buyer', 'Unknown')}** — {cards[:50]} (due {o.get('shipByDate', '?')})")
            embed.add_field(
                name=f"📋 Later ({len(upcoming)})",
                value="\n".join(lines[:10]) or "None",
                inline=False,
            )

        if not overdue and not due_today and not due_tomorrow and not upcoming:
            embed = nextcord.Embed(
                title="Shipping Status",
                description="No pending orders with ship-by dates. You're all clear.",
                color=0x57F287,
            )

        await interaction.followup.send(embed=embed)

    @commands.command(name="shipcheck")
    async def shipcheck_cmd(self, ctx):
        """Prefix fallback for shipcheck."""
        # Reuse the slash logic
        orders = await self._fetch_orders()
        if not orders:
            await ctx.reply("Unable to fetch orders from TCG Suite, or no orders found.")
            return

        pending = [o for o in orders if o.get("status") == "Pending" and o.get("shipByDate")]
        today = date.today()
        tomorrow = today + timedelta(days=1)
        overdue = [o for o in pending if o.get("shipByDate") and self._parse_date(o["shipByDate"]) and self._parse_date(o["shipByDate"]) < today]
        due_today = [o for o in pending if o.get("shipByDate") and self._parse_date(o["shipByDate"]) == today]
        due_tomorrow = [o for o in pending if o.get("shipByDate") and self._parse_date(o["shipByDate"]) == tomorrow]

        if not overdue and not due_today and not due_tomorrow:
            await ctx.reply("No upcoming shipments. You're all caught up.")
            return

        embed = self._build_alert_embed(due_today, due_tomorrow, overdue)
        await ctx.reply(embed=embed)

    @staticmethod
    def _parse_date(d: str):
        try:
            return date.fromisoformat(d)
        except (ValueError, TypeError):
            return None


def setup(bot):
    bot.add_cog(ShipWatch(bot))
