"""
cogs/updater.py – Auto-update from GitHub via webhook + polling, manual /update.
"""
import hmac
import hashlib
import subprocess
import logging
import asyncio

import nextcord
from nextcord.ext import commands, tasks
from config import Config

try:
    from aiohttp import web
except ImportError:
    web = None

log = logging.getLogger("vector.updater")


def _git_pull() -> str:
    """Pull latest from origin. Returns stdout+stderr."""
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30,
        )
        return (result.stdout + result.stderr).strip()
    except Exception as e:
        return f"Error: {e}"


def _git_version() -> dict:
    """Get current commit hash and message."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        msg = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return {"sha": sha, "message": msg, "branch": branch}
    except Exception as e:
        return {"sha": "unknown", "message": str(e), "branch": "unknown"}


class Updater(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._webhook_runner = None
        self._webhook_site = None

        # Start polling if configured
        if Config.POLL_INTERVAL_MINS > 0 and Config.GITHUB_REPO:
            self.poll_updates.change_interval(minutes=Config.POLL_INTERVAL_MINS)
            self.poll_updates.start()

    async def cog_unload(self):
        self.poll_updates.cancel()
        if self._webhook_runner:
            await self._webhook_runner.cleanup()

    async def cog_load(self):
        """Start the webhook server if configured."""
        if Config.GITHUB_SECRET and web:
            await self._start_webhook()

    # ── Webhook server ────────────────────────────────────────────────

    async def _start_webhook(self):
        try:
            app = web.Application()
            app.router.add_post("/webhook", self._handle_webhook)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, Config.WEBHOOK_HOST, Config.WEBHOOK_PORT)
            await site.start()

            self._webhook_runner = runner
            self._webhook_site = site
            log.info(f"Webhook server listening on port {Config.WEBHOOK_PORT}")
        except Exception as e:
            log.error(f"Failed to start webhook server: {e}")

    async def _handle_webhook(self, request):
        """Handle GitHub webhook push events."""
        if not Config.GITHUB_SECRET:
            return web.Response(status=403, text="No secret configured")

        # Verify HMAC signature
        signature = request.headers.get("X-Hub-Signature-256", "")
        body = await request.read()

        expected = "sha256=" + hmac.new(
            Config.GITHUB_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            log.warning("Webhook signature mismatch!")
            return web.Response(status=403, text="Invalid signature")

        # Process push event
        event = request.headers.get("X-GitHub-Event", "")
        if event == "push":
            log.info("Webhook push received – pulling updates...")
            await self._do_update()

        return web.Response(status=200, text="OK")

    # ── Polling ───────────────────────────────────────────────────────

    @tasks.loop(minutes=5)  # Interval changed in __init__
    async def poll_updates(self):
        """Check GitHub for new commits via git fetch."""
        try:
            loop = asyncio.get_running_loop()

            # Fetch remote
            fetch_result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "fetch", "origin"],
                    capture_output=True, text=True, timeout=30,
                ),
            )

            # Check if we're behind
            status = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "status", "-uno"],
                    capture_output=True, text=True, timeout=10,
                ),
            )

            if "behind" in status.stdout.lower():
                log.info("New commits detected via polling – pulling...")
                await self._do_update()
            else:
                log.debug("Poll check: already up to date.")
        except Exception as e:
            log.error(f"Poll check failed: {e}")

    @poll_updates.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # ── Update logic ──────────────────────────────────────────────────

    async def _do_update(self):
        """Pull from git and reload all cogs."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _git_pull)
        log.info(f"Git pull result: {result}")

        if "Already up to date" not in result:
            # Reload all cogs
            for ext in list(self.bot.extensions):
                try:
                    self.bot.reload_extension(ext)
                    log.info(f"Reloaded: {ext}")
                except Exception as e:
                    log.error(f"Failed to reload {ext}: {e}")

    # ── /update ───────────────────────────────────────────────────────

    @nextcord.slash_command(name="update", description="Pull latest code from GitHub and reload", guild_ids=Config.GUILD_IDS)
    async def update_slash(self, interaction: nextcord.Interaction):
        if interaction.user.id not in Config.OWNER_IDS:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        await interaction.response.defer()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _git_pull)

        # Reload cogs
        reloaded = []
        if "Already up to date" not in result:
            for ext in list(self.bot.extensions):
                try:
                    self.bot.reload_extension(ext)
                    reloaded.append(ext)
                except Exception as e:
                    reloaded.append(f"{ext} (FAILED: {e})")

        embed = nextcord.Embed(title="Update Result", color=0x57F287)
        embed.add_field(name="Git Pull", value=f"```\n{result[:500]}\n```", inline=False)
        if reloaded:
            embed.add_field(name="Reloaded", value="\n".join(f"`{r}`" for r in reloaded), inline=False)
        else:
            embed.add_field(name="Cogs", value="No reload needed", inline=False)

        await interaction.followup.send(embed=embed)

    @commands.command(name="update")
    async def update_cmd(self, ctx):
        if ctx.author.id not in Config.OWNER_IDS:
            await ctx.reply("Admin only.")
            return

        async with ctx.typing():
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _git_pull)

            reloaded = []
            if "Already up to date" not in result:
                for ext in list(self.bot.extensions):
                    try:
                        self.bot.reload_extension(ext)
                        reloaded.append(ext)
                    except Exception as e:
                        reloaded.append(f"{ext} (FAILED: {e})")

        msg = f"**Git Pull:**\n```\n{result[:500]}\n```"
        if reloaded:
            msg += "\n**Reloaded:** " + ", ".join(f"`{r}`" for r in reloaded)
        await ctx.reply(msg)

    # ── /version ──────────────────────────────────────────────────────

    @nextcord.slash_command(name="version", description="Show current git commit", guild_ids=Config.GUILD_IDS)
    async def version_slash(self, interaction: nextcord.Interaction):
        info = _git_version()
        embed = nextcord.Embed(title="Vector Version", color=0x5865F2)
        embed.add_field(name="Branch", value=f"`{info['branch']}`", inline=True)
        embed.add_field(name="Commit", value=f"`{info['sha']}`", inline=True)
        embed.add_field(name="Message", value=info["message"], inline=False)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="version")
    async def version_cmd(self, ctx):
        info = _git_version()
        await ctx.reply(f"**Branch:** `{info['branch']}` | **Commit:** `{info['sha']}` | {info['message']}")


def setup(bot):
    bot.add_cog(Updater(bot))
