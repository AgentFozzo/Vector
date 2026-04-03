"""
cogs/sshrun.py – Admin-only /run command for executing SSH commands on Unraid.
Output is truncated to fit Discord's message limit.
"""
import logging
import asyncio
import re

import nextcord
from nextcord.ext import commands
from config import Config

log = logging.getLogger("vector.sshrun")

# Commands that are too dangerous even for admins
BLOCKED_PATTERNS = [
    r"\brm\s+-rf\s+/\s*$",      # rm -rf /
    r"\bmkfs\b",                  # format filesystem
    r"\bdd\s+.*of=/dev/",        # dd to raw device
    r":\(\)\{.*\|.*\}",          # fork bomb
    r"\bshutdown\b",             # server shutdown
    r"\breboot\b",               # server reboot
    r"\binit\s+0\b",             # halt
]


def _is_blocked(cmd: str) -> bool:
    """Check if a command matches any blocked pattern."""
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return False


class SSHRun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @nextcord.slash_command(name="run", description="Execute a command on the server via SSH (admin only)", guild_ids=Config.GUILD_IDS)
    async def run_slash(self, interaction: nextcord.Interaction, command: str):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        if not Config.UNRAID_HOST:
            await interaction.response.send_message("Unraid SSH is not configured.", ephemeral=True)
            return

        if _is_blocked(command):
            await interaction.response.send_message(
                "That command is blocked for safety reasons.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        output = await self._exec_command(command)
        await interaction.followup.send(output)

    @commands.command(name="run")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def run_cmd(self, ctx, *, command: str):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return

        if not Config.UNRAID_HOST:
            await ctx.reply("Unraid SSH is not configured.")
            return

        if _is_blocked(command):
            await ctx.reply("That command is blocked for safety reasons.")
            return

        async with ctx.typing():
            output = await self._exec_command(command)
        await ctx.reply(output)

    async def _exec_command(self, command: str) -> str:
        """Execute a command via SSH and return formatted output."""
        from cogs.monitor import _ssh_exec, _ssh_available

        if not _ssh_available():
            return "SSH is not configured."

        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None, _ssh_exec,
                f"{command} 2>&1"
            )
            if not raw:
                return f"```\n$ {command}\n(no output)\n```"

            # Truncate to fit Discord limit
            max_len = 1850 - len(command)
            truncated = raw[:max_len]
            if len(raw) > max_len:
                truncated += "\n... (truncated)"

            return f"```\n$ {command}\n{truncated}\n```"
        except Exception as e:
            return f"SSH error: {e}"


def setup(bot):
    bot.add_cog(SSHRun(bot))
