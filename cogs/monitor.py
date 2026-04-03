"""
cogs/monitor.py – Server monitoring: CPU, RAM, disk, Docker, temps.
Uses SSH to Unraid when configured, falls back to local psutil.
"""
import logging
import asyncio
from pathlib import Path
import nextcord
from nextcord.ext import commands
from config import Config

log = logging.getLogger("vector.monitor")

# Lazy imports – only load if actually used
_paramiko = None
_psutil = None

# SSH known hosts file – auto-created on first connection
_KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"


def _get_paramiko():
    global _paramiko
    if _paramiko is None:
        import paramiko
        _paramiko = paramiko
    return _paramiko


def _get_psutil():
    global _psutil
    if _psutil is None:
        import psutil
        _psutil = psutil
    return _psutil


def _ssh_exec(cmd: str) -> str:
    """Run a command on Unraid via SSH and return stdout."""
    paramiko = _get_paramiko()
    ssh = paramiko.SSHClient()
    # Load known hosts if available, then fall back to auto-add for first connection
    if _KNOWN_HOSTS.exists():
        ssh.load_host_keys(str(_KNOWN_HOSTS))
    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
    try:
        ssh.connect(
            Config.UNRAID_HOST,
            username=Config.UNRAID_USER,
            password=Config.UNRAID_PASS,
            timeout=10,
        )
        # Save host key for future verification
        if _KNOWN_HOSTS.parent.exists():
            ssh.save_host_keys(str(_KNOWN_HOSTS))
        _, stdout, stderr = ssh.exec_command(cmd, timeout=15)
        return stdout.read().decode().strip()
    finally:
        ssh.close()


def _ssh_available() -> bool:
    return bool(Config.UNRAID_HOST)


class Monitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /server ───────────────────────────────────────────────────────

    async def _get_server_embed(self) -> nextcord.Embed:
        embed = nextcord.Embed(title="Server Stats", color=0x5865F2)

        if _ssh_available():
            loop = asyncio.get_running_loop()
            try:
                cpu = await loop.run_in_executor(None, _ssh_exec, "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
                mem = await loop.run_in_executor(None, _ssh_exec, "free -h | awk '/Mem:/{printf \"%s / %s (%.0f%%)\", $3, $2, $3/$2*100}'")
                load = await loop.run_in_executor(None, _ssh_exec, "cat /proc/loadavg | awk '{print $1, $2, $3}'")
                uptime = await loop.run_in_executor(None, _ssh_exec, "uptime -p")

                embed.add_field(name="CPU Usage", value=f"`{cpu}%`", inline=True)
                embed.add_field(name="Memory", value=f"`{mem}`", inline=True)
                embed.add_field(name="Load Avg", value=f"`{load}`", inline=True)
                embed.add_field(name="Uptime", value=f"`{uptime}`", inline=False)
                embed.set_footer(text=f"Via SSH to {Config.UNRAID_HOST}")
            except Exception as e:
                embed.description = f"SSH error: {e}"
                log.error(f"SSH server stats error: {e}")
        else:
            psutil = _get_psutil()
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            load = ", ".join(str(round(x, 2)) for x in psutil.getloadavg())

            embed.add_field(name="CPU Usage", value=f"`{cpu}%`", inline=True)
            embed.add_field(name="Memory", value=f"`{mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB ({mem.percent}%)`", inline=True)
            embed.add_field(name="Load Avg", value=f"`{load}`", inline=True)
            embed.set_footer(text="Local stats (no Unraid SSH configured)")

        return embed

    @nextcord.slash_command(name="server", description="CPU, RAM, disk, load average", guild_ids=Config.GUILD_IDS)
    async def server_slash(self, interaction: nextcord.Interaction):
        await interaction.response.defer()  # SSH can take a moment
        embed = await self._get_server_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="server")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def server_cmd(self, ctx):
        async with ctx.typing():
            embed = await self._get_server_embed()
        await ctx.reply(embed=embed)

    # ── /disk ─────────────────────────────────────────────────────────

    async def _get_disk_embed(self) -> nextcord.Embed:
        embed = nextcord.Embed(title="Disk Usage", color=0xFEE75C)

        if _ssh_available():
            loop = asyncio.get_running_loop()
            try:
                raw = await loop.run_in_executor(
                    None, _ssh_exec,
                    "df -h --output=target,size,used,avail,pcent -x tmpfs -x devtmpfs -x overlay | tail -n +2 | head -20"
                )
                if raw:
                    lines = raw.strip().split("\n")
                    for line in lines:
                        parts = line.split()
                        if len(parts) >= 5:
                            mount, size, used, avail, pct = parts[0], parts[1], parts[2], parts[3], parts[4]
                            pct_num = int(pct.replace("%", ""))
                            bar_len = 10
                            filled = round(pct_num / 100 * bar_len)
                            bar = "█" * filled + "░" * (bar_len - filled)
                            embed.add_field(
                                name=mount,
                                value=f"`{bar}` {pct}\n{used} / {size} ({avail} free)",
                                inline=True,
                            )
                else:
                    embed.description = "No disk data returned."
                embed.set_footer(text=f"Via SSH to {Config.UNRAID_HOST}")
            except Exception as e:
                embed.description = f"SSH error: {e}"
        else:
            psutil = _get_psutil()
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    pct = usage.percent
                    bar_len = 10
                    filled = round(pct / 100 * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    embed.add_field(
                        name=part.mountpoint,
                        value=f"`{bar}` {pct}%\n{usage.used // (1024**3)}GB / {usage.total // (1024**3)}GB",
                        inline=True,
                    )
                except PermissionError:
                    pass
            embed.set_footer(text="Local stats")

        return embed

    @nextcord.slash_command(name="disk", description="All mount points with usage bars", guild_ids=Config.GUILD_IDS)
    async def disk_slash(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        embed = await self._get_disk_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="disk")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def disk_cmd(self, ctx):
        async with ctx.typing():
            embed = await self._get_disk_embed()
        await ctx.reply(embed=embed)

    # ── /docker ───────────────────────────────────────────────────────

    async def _get_docker_embed(self) -> nextcord.Embed:
        embed = nextcord.Embed(title="Docker Containers", color=0x2496ED)

        if _ssh_available():
            loop = asyncio.get_running_loop()
            try:
                raw = await loop.run_in_executor(
                    None, _ssh_exec,
                    "docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}' | sort"
                )
                if raw:
                    for line in raw.strip().split("\n"):
                        parts = line.split("|")
                        if len(parts) >= 3:
                            name, status, image = parts[0], parts[1], parts[2]
                            icon = "🟢" if "Up" in status else "🔴"
                            embed.add_field(
                                name=f"{icon} {name}",
                                value=f"`{image}`\n{status}",
                                inline=True,
                            )
                else:
                    embed.description = "No containers found."
                embed.set_footer(text=f"Via SSH to {Config.UNRAID_HOST}")
            except Exception as e:
                embed.description = f"SSH error: {e}"
        else:
            embed.description = "Docker monitoring requires Unraid SSH to be configured."

        return embed

    @nextcord.slash_command(name="docker", description="Container list with status", guild_ids=Config.GUILD_IDS)
    async def docker_slash(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        embed = await self._get_docker_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="docker")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def docker_cmd(self, ctx):
        async with ctx.typing():
            embed = await self._get_docker_embed()
        await ctx.reply(embed=embed)

    # ── /temp ─────────────────────────────────────────────────────────

    async def _get_temp_embed(self) -> nextcord.Embed:
        embed = nextcord.Embed(title="Temperatures", color=0xED4245)

        if _ssh_available():
            loop = asyncio.get_running_loop()
            try:
                # CPU temp
                cpu_temp = await loop.run_in_executor(
                    None, _ssh_exec,
                    "sensors 2>/dev/null | grep -i 'core\\|tctl\\|cpu' | head -5 || echo 'sensors not available'"
                )
                if cpu_temp and "not available" not in cpu_temp:
                    embed.add_field(name="CPU Temps", value=f"```\n{cpu_temp}\n```", inline=False)

                # Drive temps via smartctl
                drives = await loop.run_in_executor(
                    None, _ssh_exec,
                    "for d in /dev/sd?; do echo \"$(basename $d): $(smartctl -A $d 2>/dev/null | grep -i temp | head -1 | awk '{print $NF}')C\"; done 2>/dev/null"
                )
                if drives:
                    embed.add_field(name="Drive Temps", value=f"```\n{drives}\n```", inline=False)

                if not embed.fields:
                    embed.description = "No temperature data available. Install `lm-sensors` for CPU temps."
                embed.set_footer(text=f"Via SSH to {Config.UNRAID_HOST}")
            except Exception as e:
                embed.description = f"SSH error: {e}"
        else:
            psutil = _get_psutil()
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            if temps:
                for name, entries in temps.items():
                    values = "\n".join(f"  {e.label or 'Sensor'}: {e.current}°C" for e in entries)
                    embed.add_field(name=name, value=f"```\n{values}\n```", inline=False)
            else:
                embed.description = "No temperature sensors found locally."
            embed.set_footer(text="Local stats")

        return embed

    @nextcord.slash_command(name="temp", description="CPU and drive temperatures", guild_ids=Config.GUILD_IDS)
    async def temp_slash(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        embed = await self._get_temp_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="temp")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def temp_cmd(self, ctx):
        async with ctx.typing():
            embed = await self._get_temp_embed()
        await ctx.reply(embed=embed)


def setup(bot):
    bot.add_cog(Monitor(bot))
