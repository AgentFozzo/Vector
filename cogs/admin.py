"""
cogs/admin.py – Core admin commands: help, ping, status, reload, shutdown.
"""
import time
import platform
import nextcord
from nextcord.ext import commands
from config import Config

# Maps cog class names to user-friendly category names
COG_DISPLAY_NAMES = {
    "Admin": "Admin",
    "Monitor": "Monitoring",
    "HomeAssistant": "Home",
    "ShipWatch": "Shipping",
    "Scheduler": "Scheduler",
    "Smart": "Smart",
    "Updater": "Updates",
    "HealthCheck": "Health",
    "SSHRun": "SSH",
}


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    # ── Helpers ───────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        return user_id in Config.OWNER_IDS

    def _get_categories(self) -> dict[str, list[str]]:
        """Dynamically build command categories from loaded cogs."""
        categories: dict[str, list[str]] = {}
        for cog_name, cog in self.bot.cogs.items():
            display = COG_DISPLAY_NAMES.get(cog_name, cog_name)
            cmds = []
            # Prefix commands
            for cmd in cog.get_commands():
                cmds.append(cmd.name)
            # Slash commands (nextcord application commands on the cog)
            for attr_name in dir(cog):
                attr = getattr(cog, attr_name, None)
                if isinstance(attr, nextcord.SlashApplicationCommand):
                    if attr.name not in cmds:
                        cmds.append(attr.name)
            if cmds:
                categories[display] = sorted(set(cmds))
        return dict(sorted(categories.items()))

    def _build_help_embed(self, category: str = None) -> nextcord.Embed:
        embed = nextcord.Embed(
            title="Vector Bot – Commands",
            color=0x5865F2,
        )
        cats = self._get_categories()
        if category:
            key = category.title()
            matched = {k: v for k, v in cats.items() if k.lower() == key.lower()}
            if matched:
                cats = matched
            else:
                embed.description = f"Unknown category `{category}`. Available: {', '.join(cats.keys())}"
                return embed

        for cat_name, cmds in cats.items():
            cmd_list = "\n".join(f"`/{c}`" for c in cmds)
            embed.add_field(name=cat_name, value=cmd_list, inline=True)

        embed.set_footer(text="All commands also work with ! prefix")
        return embed

    def _build_status_embed(self) -> nextcord.Embed:
        uptime_secs = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)

        embed = nextcord.Embed(title="Vector Status", color=0x57F287)
        embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="nextcord", value=nextcord.__version__, inline=True)
        embed.add_field(name="Cogs Loaded", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        return embed

    # ── /help ─────────────────────────────────────────────────────────

    @nextcord.slash_command(name="help", description="Show all commands", guild_ids=Config.GUILD_IDS)
    async def help_slash(self, interaction: nextcord.Interaction, category: str = None):
        embed = self._build_help_embed(category)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="help")
    async def help_cmd(self, ctx, category: str = None):
        embed = self._build_help_embed(category)
        await ctx.reply(embed=embed)

    # ── /ping ─────────────────────────────────────────────────────────

    @nextcord.slash_command(name="ping", description="Check bot latency", guild_ids=Config.GUILD_IDS)
    async def ping_slash(self, interaction: nextcord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! `{latency}ms`")

    @commands.command(name="ping")
    async def ping_cmd(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.reply(f"Pong! `{latency}ms`")

    # ── /status ───────────────────────────────────────────────────────

    @nextcord.slash_command(name="status", description="Bot info and stats", guild_ids=Config.GUILD_IDS)
    async def status_slash(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(embed=self._build_status_embed())

    @commands.command(name="status")
    async def status_cmd(self, ctx):
        await ctx.reply(embed=self._build_status_embed())

    # ── /reload ───────────────────────────────────────────────────────

    @nextcord.slash_command(name="reload", description="Reload one or all cogs", guild_ids=Config.GUILD_IDS)
    async def reload_slash(self, interaction: nextcord.Interaction, cog: str = None):
        if not self._is_admin(interaction.user.id):
            await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
            return
        result = self._do_reload(cog)
        await interaction.response.send_message(result, ephemeral=True)

    @commands.command(name="reload")
    async def reload_cmd(self, ctx, cog: str = None):
        if not self._is_admin(ctx.author.id):
            await ctx.reply("You don't have permission to do that.")
            return
        result = self._do_reload(cog)
        await ctx.reply(result)

    def _do_reload(self, cog: str = None) -> str:
        if cog:
            ext = f"cogs.{cog}" if not cog.startswith("cogs.") else cog
            try:
                self.bot.reload_extension(ext)
                return f"Reloaded `{ext}`"
            except Exception as e:
                return f"Failed to reload `{ext}`: {e}"
        else:
            results = []
            for ext in list(self.bot.extensions):
                try:
                    self.bot.reload_extension(ext)
                    results.append(f"Reloaded `{ext}`")
                except Exception as e:
                    results.append(f"Failed `{ext}`: {e}")
            return "\n".join(results) or "No cogs loaded."

    # ── /shutdown ─────────────────────────────────────────────────────

    @nextcord.slash_command(name="shutdown", description="Shut the bot down", guild_ids=Config.GUILD_IDS)
    async def shutdown_slash(self, interaction: nextcord.Interaction):
        if not self._is_admin(interaction.user.id):
            await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
            return
        await interaction.response.send_message("Shutting down...")
        await self.bot.close()

    @commands.command(name="shutdown")
    async def shutdown_cmd(self, ctx):
        if not self._is_admin(ctx.author.id):
            await ctx.reply("You don't have permission to do that.")
            return
        await ctx.reply("Shutting down...")
        await self.bot.close()


def setup(bot):
    bot.add_cog(Admin(bot))
