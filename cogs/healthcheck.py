"""
cogs/healthcheck.py – /uptime: one-glance health dashboard.
Pings Unraid SSH, Home Assistant API, and TCG Suite API in parallel.
"""
import logging
import asyncio
import time

import nextcord
from nextcord.ext import commands
from config import Config

try:
    import aiohttp
except ImportError:
    aiohttp = None

log = logging.getLogger("vector.healthcheck")


async def _check_ssh() -> tuple[str, str, float]:
    """Check SSH connectivity to Unraid. Returns (name, status, latency_ms)."""
    if not Config.UNRAID_HOST:
        return "Unraid SSH", "not configured", -1

    loop = asyncio.get_running_loop()
    start = time.monotonic()
    try:
        from cogs.monitor import _ssh_exec
        result = await loop.run_in_executor(None, _ssh_exec, "echo ok")
        elapsed = (time.monotonic() - start) * 1000
        if result.strip() == "ok":
            return "Unraid SSH", "connected", elapsed
        return "Unraid SSH", "unexpected response", elapsed
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return "Unraid SSH", f"error: {e}", elapsed


async def _check_http(name: str, url: str, timeout: int = 5) -> tuple[str, str, float]:
    """Check HTTP endpoint. Returns (name, status, latency_ms)."""
    if not url:
        return name, "not configured", -1

    if aiohttp is None:
        return name, "aiohttp not installed", -1

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            # For HA, add the auth header
            headers = {}
            if name == "Home Assistant" and Config.HA_TOKEN:
                headers["Authorization"] = f"Bearer {Config.HA_TOKEN}"

            async with session.get(url, headers=headers) as resp:
                elapsed = (time.monotonic() - start) * 1000
                if resp.status < 400:
                    return name, "connected", elapsed
                return name, f"HTTP {resp.status}", elapsed
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        return name, "timeout", elapsed
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return name, f"error: {type(e).__name__}", elapsed


class HealthCheck(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @nextcord.slash_command(name="uptime", description="Health check all connected services", guild_ids=Config.GUILD_IDS)
    async def uptime_slash(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        embed = await self._build_uptime_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="uptime")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def uptime_cmd(self, ctx):
        async with ctx.typing():
            embed = await self._build_uptime_embed()
        await ctx.reply(embed=embed)

    async def _build_uptime_embed(self) -> nextcord.Embed:
        # Run all checks in parallel
        checks = await asyncio.gather(
            _check_ssh(),
            _check_http(
                "Home Assistant",
                f"{Config.HA_URL.rstrip('/')}/api/" if Config.HA_URL else "",
            ),
            _check_http(
                "TCG Suite",
                f"{Config.TCG_SUITE_URL}/api/sync/data" if Config.TCG_SUITE_URL else "",
            ),
        )

        all_ok = all(c[1] == "connected" for c in checks if c[2] >= 0)
        embed = nextcord.Embed(
            title="Service Health",
            color=0x57F287 if all_ok else 0xFEE75C,
        )

        for name, status, latency in checks:
            if latency < 0:
                icon = "⚪"
                value = f"_{status}_"
            elif status == "connected":
                icon = "🟢"
                value = f"**Online** — `{latency:.0f}ms`"
            elif status == "timeout":
                icon = "🔴"
                value = "**Timeout**"
            else:
                icon = "🔴"
                value = f"**{status}**"

            embed.add_field(name=f"{icon} {name}", value=value, inline=False)

        # Bot uptime
        admin_cog = self.bot.get_cog("Admin")
        if admin_cog and hasattr(admin_cog, "start_time"):
            uptime_secs = int(time.time() - admin_cog.start_time)
            hours, remainder = divmod(uptime_secs, 3600)
            minutes, seconds = divmod(remainder, 60)
            embed.add_field(
                name="🤖 Vector Bot",
                value=f"**Online** — uptime `{hours}h {minutes}m {seconds}s` | latency `{round(self.bot.latency * 1000)}ms`",
                inline=False,
            )

        return embed


def setup(bot):
    bot.add_cog(HealthCheck(bot))
