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

    # ── Docker container autocomplete ─────────────────────────────────

    async def _autocomplete_container(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for Docker container names via SSH."""
        if not _ssh_available():
            return []
        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(
                None, _ssh_exec,
                "docker ps -a --format '{{.Names}}' | sort"
            )
            if not raw:
                return []
            current_lower = current.lower()
            names = [n.strip() for n in raw.strip().split("\n") if n.strip()]
            return [n for n in names if current_lower in n.lower()][:25]
        except Exception:
            return []

    # ── /dockerrestart ────────────────────────────────────────────────

    async def _docker_action(self, container: str, action: str) -> tuple[bool, str]:
        """Run a docker action (start/stop/restart) on a container."""
        if not _ssh_available():
            return False, "Docker control requires Unraid SSH to be configured."

        allowed = {"start", "stop", "restart"}
        if action not in allowed:
            return False, f"Invalid action. Use: {', '.join(allowed)}"

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, _ssh_exec,
                f"docker {action} {container} 2>&1"
            )
            # Verify new status
            status = await loop.run_in_executor(
                None, _ssh_exec,
                f"docker inspect -f '{{{{.State.Status}}}}' {container} 2>&1"
            )
            icon = "🟢" if status == "running" else "🔴" if status in ("exited", "stopped") else "🟡"
            return True, f"{icon} **{container}** — `docker {action}` complete. Status: **{status}**"
        except Exception as e:
            return False, f"Failed to {action} `{container}`: {e}"

    @nextcord.slash_command(name="dockerrestart", description="Restart a Docker container", guild_ids=Config.GUILD_IDS)
    async def dockerrestart_slash(self, interaction: nextcord.Interaction, container: str = nextcord.SlashOption(description="Container name", autocomplete=True)):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()
        success, msg = await self._docker_action(container, "restart")
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await interaction.followup.send(embed=embed)

    @dockerrestart_slash.on_autocomplete("container")
    async def dockerrestart_ac(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_container(interaction, current)

    @commands.command(name="dockerrestart")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def dockerrestart_cmd(self, ctx, *, container: str):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return
        async with ctx.typing():
            success, msg = await self._docker_action(container, "restart")
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await ctx.reply(embed=embed)

    # ── /dockerstop ───────────────────────────────────────────────────

    @nextcord.slash_command(name="dockerstop", description="Stop a Docker container", guild_ids=Config.GUILD_IDS)
    async def dockerstop_slash(self, interaction: nextcord.Interaction, container: str = nextcord.SlashOption(description="Container name", autocomplete=True)):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()
        success, msg = await self._docker_action(container, "stop")
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await interaction.followup.send(embed=embed)

    @dockerstop_slash.on_autocomplete("container")
    async def dockerstop_ac(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_container(interaction, current)

    @commands.command(name="dockerstop")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def dockerstop_cmd(self, ctx, *, container: str):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return
        async with ctx.typing():
            success, msg = await self._docker_action(container, "stop")
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await ctx.reply(embed=embed)

    # ── /dockerstart ──────────────────────────────────────────────────

    @nextcord.slash_command(name="dockerstart", description="Start a Docker container", guild_ids=Config.GUILD_IDS)
    async def dockerstart_slash(self, interaction: nextcord.Interaction, container: str = nextcord.SlashOption(description="Container name", autocomplete=True)):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()
        success, msg = await self._docker_action(container, "start")
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await interaction.followup.send(embed=embed)

    @dockerstart_slash.on_autocomplete("container")
    async def dockerstart_ac(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_container(interaction, current)

    @commands.command(name="dockerstart")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def dockerstart_cmd(self, ctx, *, container: str):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return
        async with ctx.typing():
            success, msg = await self._docker_action(container, "start")
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await ctx.reply(embed=embed)

    # ── /logs ─────────────────────────────────────────────────────────

    @nextcord.slash_command(name="logs", description="Tail Docker container logs", guild_ids=Config.GUILD_IDS)
    async def logs_slash(self, interaction: nextcord.Interaction, container: str = nextcord.SlashOption(description="Container name", autocomplete=True), lines: int = nextcord.SlashOption(description="Number of lines (default 20)", required=False, default=20)):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()

        lines = max(1, min(lines, 50))
        result = await self._get_container_logs(container, lines)
        await interaction.followup.send(result)

    @logs_slash.on_autocomplete("container")
    async def logs_ac(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_container(interaction, current)

    @commands.command(name="logs")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def logs_cmd(self, ctx, container: str, lines: int = 20):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return
        lines = max(1, min(lines, 50))
        async with ctx.typing():
            result = await self._get_container_logs(container, lines)
        await ctx.reply(result)

    async def _get_container_logs(self, container: str, lines: int) -> str:
        if not _ssh_available():
            return "Docker logs require Unraid SSH to be configured."

        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None, _ssh_exec,
                f"docker logs --tail {lines} {container} 2>&1"
            )
            if not raw:
                return f"No log output from `{container}`."
            # Truncate to fit Discord's 2000-char limit
            truncated = raw[:1900]
            if len(raw) > 1900:
                truncated += "\n... (truncated)"
            return f"**{container}** — last {lines} lines:\n```\n{truncated}\n```"
        except Exception as e:
            return f"Failed to get logs for `{container}`: {e}"

    # ── /speedtest ────────────────────────────────────────────────────

    @nextcord.slash_command(name="speedtest", description="Run a network speed test on the server", guild_ids=Config.GUILD_IDS)
    async def speedtest_slash(self, interaction: nextcord.Interaction):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = await self._run_speedtest()
        await interaction.followup.send(embed=embed)

    @commands.command(name="speedtest")
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def speedtest_cmd(self, ctx):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return
        async with ctx.typing():
            embed = await self._run_speedtest()
        await ctx.reply(embed=embed)

    async def _run_speedtest(self) -> nextcord.Embed:
        embed = nextcord.Embed(title="Speed Test", color=0x5865F2)

        if _ssh_available():
            loop = asyncio.get_running_loop()
            try:
                raw = await loop.run_in_executor(
                    None, _ssh_exec,
                    "speedtest-cli --simple 2>&1 || echo 'speedtest-cli not installed'"
                )
                if "not installed" in raw or "not found" in raw:
                    embed.description = "speedtest-cli is not installed on the server.\nInstall with: `pip install speedtest-cli`"
                    embed.color = 0xED4245
                else:
                    for line in raw.strip().split("\n"):
                        if ":" in line:
                            key, val = line.split(":", 1)
                            embed.add_field(name=key.strip(), value=f"`{val.strip()}`", inline=True)
                embed.set_footer(text=f"Via SSH to {Config.UNRAID_HOST}")
            except Exception as e:
                embed.description = f"SSH error: {e}"
                embed.color = 0xED4245
        else:
            try:
                import subprocess
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["speedtest-cli", "--simple"],
                        capture_output=True, text=True, timeout=60,
                    ),
                )
                raw = (result.stdout + result.stderr).strip()
                if result.returncode != 0 or "not found" in raw:
                    embed.description = "speedtest-cli is not installed.\nInstall with: `pip install speedtest-cli`"
                    embed.color = 0xED4245
                else:
                    for line in raw.strip().split("\n"):
                        if ":" in line:
                            key, val = line.split(":", 1)
                            embed.add_field(name=key.strip(), value=f"`{val.strip()}`", inline=True)
                embed.set_footer(text="Local speedtest")
            except Exception as e:
                embed.description = f"Error: {e}"
                embed.color = 0xED4245

        return embed


def setup(bot):
    bot.add_cog(Monitor(bot))
