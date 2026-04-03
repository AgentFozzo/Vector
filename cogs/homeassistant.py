"""
cogs/homeassistant.py – Home Assistant integration for Vector.
Controls lights, switches, and scenes via the HA REST API.
Speaks in Vector's Jarvis tone.
"""
import logging
import asyncio
from typing import Optional

import nextcord
from nextcord.ext import commands
from config import Config

try:
    import aiohttp
except ImportError:
    aiohttp = None

log = logging.getLogger("vector.homeassistant")


class HomeAssistant(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.base_url = Config.HA_URL.rstrip("/") if Config.HA_URL else ""
        self.token = Config.HA_TOKEN
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazy-init aiohttp session with HA auth headers."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    async def cog_unload(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _ha_configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def _api_get(self, endpoint: str) -> dict | list | None:
        """GET from HA API."""
        session = await self._get_session()
        try:
            async with session.get(f"{self.base_url}/api/{endpoint}") as resp:
                if resp.status == 200:
                    return await resp.json()
                log.error(f"HA API GET {endpoint} returned {resp.status}")
                return None
        except Exception as e:
            log.error(f"HA API error: {e}")
            return None

    async def _api_post(self, endpoint: str, data: dict = None) -> dict | list | None:
        """POST to HA API."""
        session = await self._get_session()
        try:
            async with session.post(f"{self.base_url}/api/{endpoint}", json=data or {}) as resp:
                if resp.status in (200, 201):
                    return await resp.json()
                log.error(f"HA API POST {endpoint} returned {resp.status}")
                return None
        except Exception as e:
            log.error(f"HA API error: {e}")
            return None

    # ── Helper: get all entities of a domain ──────────────────────────

    async def _get_entities(self, domain: str) -> list[dict]:
        """Get all entities for a domain (light, switch, scene, etc.)."""
        states = await self._api_get("states")
        if not states:
            return []
        return [s for s in states if s["entity_id"].startswith(f"{domain}.")]

    def _friendly_name(self, entity: dict) -> str:
        """Get the friendly name or fall back to entity_id."""
        return entity.get("attributes", {}).get("friendly_name", entity["entity_id"])

    def _state_icon(self, state: str) -> str:
        """Return an icon for the entity state."""
        if state == "on":
            return "💡"
        elif state == "off":
            return "⚫"
        elif state == "unavailable":
            return "⚠️"
        return "🔵"

    # ── Autocomplete helpers ────────────────────────────────────────────

    async def _autocomplete_device(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for light/switch device names."""
        if not self._ha_configured():
            return []
        states = await self._api_get("states")
        if not states:
            return []

        current_lower = current.lower()
        choices = []
        for entity in states:
            eid = entity["entity_id"]
            if not any(eid.startswith(f"{d}.") for d in ["light", "switch", "fan", "cover"]):
                continue
            friendly = entity.get("attributes", {}).get("friendly_name", eid)
            if current_lower in friendly.lower() or current_lower in eid.lower():
                choices.append(friendly[:100])
            if len(choices) >= 25:
                break
        return choices

    async def _autocomplete_scene(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for scene names."""
        if not self._ha_configured():
            return []
        states = await self._api_get("states")
        if not states:
            return []

        current_lower = current.lower()
        choices = []
        for entity in states:
            eid = entity["entity_id"]
            if not eid.startswith("scene."):
                continue
            friendly = entity.get("attributes", {}).get("friendly_name", eid)
            if current_lower in friendly.lower() or current_lower in eid.lower():
                choices.append(friendly[:100])
            if len(choices) >= 25:
                break
        return choices

    # ── /lights ───────────────────────────────────────────────────────

    async def _build_lights_embed(self) -> nextcord.Embed:
        """Build an embed showing all lights and their states."""
        lights = await self._get_entities("light")
        switches = await self._get_entities("switch")
        all_devices = lights + switches

        embed = nextcord.Embed(
            title="Smart Home Devices",
            color=0xFFB347,
            description="Current state of all controllable devices.",
        )

        if not all_devices:
            embed.description = "No lights or switches found in Home Assistant. Verify your configuration."
            return embed

        for entity in sorted(all_devices, key=lambda e: self._friendly_name(e)):
            name = self._friendly_name(entity)
            state = entity.get("state", "unknown")
            icon = self._state_icon(state)
            attrs = entity.get("attributes", {})

            details = f"{icon} **{state.title()}**"

            # Add brightness if available
            brightness = attrs.get("brightness")
            if brightness is not None:
                pct = round((brightness / 255) * 100)
                details += f" ({pct}% brightness)"

            # Add color temp if available
            color_temp = attrs.get("color_temp")
            if color_temp is not None:
                details += f" | {color_temp}K"

            embed.add_field(
                name=name,
                value=f"{details}\n`{entity['entity_id']}`",
                inline=True,
            )

        embed.set_footer(text=f"Connected to {self.base_url}")
        return embed

    @nextcord.slash_command(name="lights", description="List all smart home lights and switches", guild_ids=Config.GUILD_IDS)
    async def lights_slash(self, interaction: nextcord.Interaction):
        if not self._ha_configured():
            await interaction.response.send_message(
                "Home Assistant is not configured. Please set `HA_URL` and `HA_TOKEN` in the `.env` file.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        embed = await self._build_lights_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="lights")
    async def lights_cmd(self, ctx):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured. Set `HA_URL` and `HA_TOKEN` in `.env`.")
            return
        async with ctx.typing():
            embed = await self._build_lights_embed()
        await ctx.reply(embed=embed)

    # ── /toggle ───────────────────────────────────────────────────────

    async def _toggle_entity(self, entity_id: str) -> tuple[bool, str]:
        """Toggle a light or switch. Returns (success, message)."""
        # Determine domain
        domain = entity_id.split(".")[0] if "." in entity_id else "light"

        result = await self._api_post(f"services/{domain}/toggle", {"entity_id": entity_id})
        if result is not None:
            # Get updated state
            await asyncio.sleep(0.5)
            states = await self._api_get(f"states/{entity_id}")
            new_state = states.get("state", "unknown") if states else "unknown"
            friendly = states.get("attributes", {}).get("friendly_name", entity_id) if states else entity_id
            return True, f"{self._state_icon(new_state)} **{friendly}** is now **{new_state}**."
        return False, f"Failed to toggle `{entity_id}`. Please verify the entity ID."

    @nextcord.slash_command(name="toggle", description="Toggle a light or switch on/off", guild_ids=Config.GUILD_IDS)
    async def toggle_slash(self, interaction: nextcord.Interaction, device: str = nextcord.SlashOption(description="Device name", autocomplete=True)):
        if not self._ha_configured():
            await interaction.response.send_message("Home Assistant is not configured.", ephemeral=True)
            return
        await interaction.response.defer()

        # Try to match by friendly name if no dot in input
        entity_id = await self._resolve_entity(device)
        success, msg = await self._toggle_entity(entity_id)
        color = 0x57F287 if success else 0xED4245
        embed = nextcord.Embed(description=msg, color=color)
        await interaction.followup.send(embed=embed)

    @toggle_slash.on_autocomplete("device")
    async def toggle_autocomplete(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_device(interaction, current)

    @commands.command(name="toggle")
    async def toggle_cmd(self, ctx, *, device: str):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured.")
            return
        async with ctx.typing():
            entity_id = await self._resolve_entity(device)
            success, msg = await self._toggle_entity(entity_id)
        color = 0x57F287 if success else 0xED4245
        embed = nextcord.Embed(description=msg, color=color)
        await ctx.reply(embed=embed)

    # ── /on and /off ──────────────────────────────────────────────────

    async def _set_entity(self, entity_id: str, turn_on: bool) -> tuple[bool, str]:
        """Turn a light/switch on or off."""
        domain = entity_id.split(".")[0] if "." in entity_id else "light"
        service = "turn_on" if turn_on else "turn_off"

        result = await self._api_post(f"services/{domain}/{service}", {"entity_id": entity_id})
        if result is not None:
            await asyncio.sleep(0.5)
            states = await self._api_get(f"states/{entity_id}")
            new_state = states.get("state", "unknown") if states else "unknown"
            friendly = states.get("attributes", {}).get("friendly_name", entity_id) if states else entity_id
            action = "activated" if turn_on else "deactivated"
            return True, f"{self._state_icon(new_state)} **{friendly}** has been {action}."
        action = "activate" if turn_on else "deactivate"
        return False, f"Unable to {action} `{entity_id}`. Please verify the entity ID."

    @nextcord.slash_command(name="on", description="Turn on a light or switch", guild_ids=Config.GUILD_IDS)
    async def on_slash(self, interaction: nextcord.Interaction, device: str = nextcord.SlashOption(description="Device name", autocomplete=True)):
        if not self._ha_configured():
            await interaction.response.send_message("Home Assistant is not configured.", ephemeral=True)
            return
        await interaction.response.defer()
        entity_id = await self._resolve_entity(device)
        success, msg = await self._set_entity(entity_id, True)
        color = 0x57F287 if success else 0xED4245
        embed = nextcord.Embed(description=msg, color=color)
        await interaction.followup.send(embed=embed)

    @on_slash.on_autocomplete("device")
    async def on_autocomplete(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_device(interaction, current)

    @commands.command(name="on")
    async def on_cmd(self, ctx, *, device: str):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured.")
            return
        async with ctx.typing():
            entity_id = await self._resolve_entity(device)
            success, msg = await self._set_entity(entity_id, True)
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await ctx.reply(embed=embed)

    @nextcord.slash_command(name="off", description="Turn off a light or switch", guild_ids=Config.GUILD_IDS)
    async def off_slash(self, interaction: nextcord.Interaction, device: str = nextcord.SlashOption(description="Device name", autocomplete=True)):
        if not self._ha_configured():
            await interaction.response.send_message("Home Assistant is not configured.", ephemeral=True)
            return
        await interaction.response.defer()
        entity_id = await self._resolve_entity(device)
        success, msg = await self._set_entity(entity_id, False)
        color = 0x57F287 if success else 0xED4245
        embed = nextcord.Embed(description=msg, color=color)
        await interaction.followup.send(embed=embed)

    @off_slash.on_autocomplete("device")
    async def off_autocomplete(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_device(interaction, current)

    @commands.command(name="off")
    async def off_cmd(self, ctx, *, device: str):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured.")
            return
        async with ctx.typing():
            entity_id = await self._resolve_entity(device)
            success, msg = await self._set_entity(entity_id, False)
        embed = nextcord.Embed(description=msg, color=0x57F287 if success else 0xED4245)
        await ctx.reply(embed=embed)

    # ── /brightness ───────────────────────────────────────────────────

    @nextcord.slash_command(name="brightness", description="Set a light's brightness (0-100)", guild_ids=Config.GUILD_IDS)
    async def brightness_slash(self, interaction: nextcord.Interaction, device: str = nextcord.SlashOption(description="Device name", autocomplete=True), level: int = nextcord.SlashOption(description="Brightness 0-100")):
        if not self._ha_configured():
            await interaction.response.send_message("Home Assistant is not configured.", ephemeral=True)
            return
        await interaction.response.defer()
        entity_id = await self._resolve_entity(device)
        level = max(0, min(100, level))
        brightness = round((level / 100) * 255)

        result = await self._api_post(
            f"services/light/turn_on",
            {"entity_id": entity_id, "brightness": brightness},
        )
        if result is not None:
            embed = nextcord.Embed(
                description=f"💡 **{device}** brightness set to **{level}%**.",
                color=0x57F287,
            )
        else:
            embed = nextcord.Embed(
                description=f"Unable to adjust brightness for `{entity_id}`.",
                color=0xED4245,
            )
        await interaction.followup.send(embed=embed)

    @brightness_slash.on_autocomplete("device")
    async def brightness_autocomplete(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_device(interaction, current)

    @commands.command(name="brightness")
    async def brightness_cmd(self, ctx, device: str, level: int):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured.")
            return
        async with ctx.typing():
            entity_id = await self._resolve_entity(device)
            level = max(0, min(100, level))
            brightness = round((level / 100) * 255)
            result = await self._api_post(
                f"services/light/turn_on",
                {"entity_id": entity_id, "brightness": brightness},
            )
        if result is not None:
            await ctx.reply(f"💡 **{device}** brightness set to **{level}%**.")
        else:
            await ctx.reply(f"Unable to adjust brightness for `{entity_id}`.")

    # ── /scene ────────────────────────────────────────────────────────

    async def _build_scenes_embed(self) -> nextcord.Embed:
        """List all available scenes."""
        scenes = await self._get_entities("scene")
        embed = nextcord.Embed(title="Available Scenes", color=0x9B59B6)

        if not scenes:
            embed.description = "No scenes found in Home Assistant."
            return embed

        for scene in sorted(scenes, key=lambda s: self._friendly_name(s)):
            name = self._friendly_name(scene)
            entity_id = scene["entity_id"]
            embed.add_field(
                name=f"🎬 {name}",
                value=f"`{entity_id}`",
                inline=True,
            )

        embed.set_footer(text="Use /scene <name> to activate a scene")
        return embed

    @nextcord.slash_command(name="scenes", description="List all available scenes", guild_ids=Config.GUILD_IDS)
    async def scenes_slash(self, interaction: nextcord.Interaction):
        if not self._ha_configured():
            await interaction.response.send_message("Home Assistant is not configured.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = await self._build_scenes_embed()
        await interaction.followup.send(embed=embed)

    @commands.command(name="scenes")
    async def scenes_cmd(self, ctx):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured.")
            return
        async with ctx.typing():
            embed = await self._build_scenes_embed()
        await ctx.reply(embed=embed)

    @nextcord.slash_command(name="scene", description="Activate a scene", guild_ids=Config.GUILD_IDS)
    async def scene_slash(self, interaction: nextcord.Interaction, name: str = nextcord.SlashOption(description="Scene name", autocomplete=True)):
        if not self._ha_configured():
            await interaction.response.send_message("Home Assistant is not configured.", ephemeral=True)
            return
        await interaction.response.defer()

        entity_id = await self._resolve_entity(name, domain="scene")
        result = await self._api_post("services/scene/turn_on", {"entity_id": entity_id})

        if result is not None:
            states = await self._api_get(f"states/{entity_id}")
            friendly = states.get("attributes", {}).get("friendly_name", name) if states else name
            embed = nextcord.Embed(
                description=f"🎬 Scene **{friendly}** has been activated. Enjoy the atmosphere.",
                color=0x9B59B6,
            )
        else:
            embed = nextcord.Embed(
                description=f"Unable to activate scene `{name}`. Please check the scene name with `/scenes`.",
                color=0xED4245,
            )
        await interaction.followup.send(embed=embed)

    @scene_slash.on_autocomplete("name")
    async def scene_autocomplete(self, interaction: nextcord.Interaction, current: str):
        return await self._autocomplete_scene(interaction, current)

    @commands.command(name="scene")
    async def scene_cmd(self, ctx, *, name: str):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured.")
            return
        async with ctx.typing():
            entity_id = await self._resolve_entity(name, domain="scene")
            result = await self._api_post("services/scene/turn_on", {"entity_id": entity_id})
        if result is not None:
            await ctx.reply(f"🎬 Scene **{name}** has been activated. Enjoy the atmosphere.")
        else:
            await ctx.reply(f"Unable to activate scene `{name}`. Check `/scenes` for available options.")

    # ── /ha (general status) ──────────────────────────────────────────

    @nextcord.slash_command(name="ha", description="Home Assistant connection status", guild_ids=Config.GUILD_IDS)
    async def ha_slash(self, interaction: nextcord.Interaction):
        if not self._ha_configured():
            await interaction.response.send_message(
                "Home Assistant is not configured. Set `HA_URL` and `HA_TOKEN` in `.env`.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        result = await self._api_get("")
        embed = nextcord.Embed(title="Home Assistant Status", color=0x41BDF5)

        if result and "message" in result:
            embed.add_field(name="Status", value="🟢 Connected", inline=True)
            embed.add_field(name="URL", value=f"`{self.base_url}`", inline=True)

            # Count entities
            states = await self._api_get("states")
            if states:
                lights = sum(1 for s in states if s["entity_id"].startswith("light."))
                switches = sum(1 for s in states if s["entity_id"].startswith("switch."))
                scenes = sum(1 for s in states if s["entity_id"].startswith("scene."))
                automations = sum(1 for s in states if s["entity_id"].startswith("automation."))

                embed.add_field(name="Lights", value=str(lights), inline=True)
                embed.add_field(name="Switches", value=str(switches), inline=True)
                embed.add_field(name="Scenes", value=str(scenes), inline=True)
                embed.add_field(name="Automations", value=str(automations), inline=True)
        else:
            embed.add_field(name="Status", value="🔴 Unable to connect", inline=True)
            embed.add_field(name="URL", value=f"`{self.base_url}`", inline=True)
            embed.description = "Check that your HA_URL and HA_TOKEN are correct."

        await interaction.followup.send(embed=embed)

    @commands.command(name="ha")
    async def ha_cmd(self, ctx):
        if not self._ha_configured():
            await ctx.reply("Home Assistant is not configured. Set `HA_URL` and `HA_TOKEN` in `.env`.")
            return
        async with ctx.typing():
            result = await self._api_get("")
        if result and "message" in result:
            await ctx.reply(f"🟢 Connected to Home Assistant at `{self.base_url}`")
        else:
            await ctx.reply(f"🔴 Unable to connect to Home Assistant at `{self.base_url}`")

    # ── Entity resolution (fuzzy match by friendly name) ──────────────

    async def _resolve_entity(self, query: str, domain: str = None) -> str:
        """Resolve a user-friendly name to an entity_id.
        If query already looks like an entity_id (contains a dot), return as-is.
        Otherwise, search all entities for a fuzzy match on friendly_name.
        """
        query = query.strip()

        # Already an entity_id
        if "." in query:
            return query

        # Search all states for a match
        states = await self._api_get("states")
        if not states:
            # Best guess: assume light domain
            d = domain or "light"
            return f"{d}.{query.lower().replace(' ', '_')}"

        query_lower = query.lower()
        best_match = None
        best_score = 0

        for entity in states:
            eid = entity["entity_id"]
            # Filter by domain if specified
            if domain and not eid.startswith(f"{domain}."):
                continue
            # Only search controllable domains if no domain specified
            if not domain and not any(eid.startswith(f"{d}.") for d in ["light", "switch", "scene", "automation", "fan", "cover"]):
                continue

            friendly = entity.get("attributes", {}).get("friendly_name", "").lower()
            eid_name = eid.split(".", 1)[1].replace("_", " ").lower()

            # Exact match on friendly name
            if query_lower == friendly:
                return eid
            # Exact match on entity name
            if query_lower == eid_name:
                return eid
            # Partial match scoring
            if query_lower in friendly:
                score = len(query_lower) / len(friendly) * 100
                if score > best_score:
                    best_score = score
                    best_match = eid
            elif query_lower in eid_name:
                score = len(query_lower) / len(eid_name) * 80
                if score > best_score:
                    best_score = score
                    best_match = eid

        if best_match:
            return best_match

        # Last resort: construct an entity_id
        d = domain or "light"
        return f"{d}.{query_lower.replace(' ', '_')}"


def setup(bot):
    bot.add_cog(HomeAssistant(bot))
