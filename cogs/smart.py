"""
cogs/smart.py – Mention-triggered keyword responses and /ask command.
No AI API required – just pattern matching with curated responses.
"""
import re
import random
import logging

import nextcord
from nextcord.ext import commands
from config import Config

log = logging.getLogger("vector.smart")

# ── Intent definitions ────────────────────────────────────────────────
# Each intent has patterns (regex) and responses ({user} is replaced).
INTENTS = [
    {
        "name": "greeting",
        "patterns": [
            r"\b(hi|hello|hey|howdy|sup|yo|what'?s up|greetings)\b",
        ],
        "responses": [
            "Hey {user}! What's going on?",
            "Hello {user}! How can I help?",
            "Yo {user}! What do you need?",
            "Hey! What's up {user}?",
        ],
    },
    {
        "name": "goodbye",
        "patterns": [
            r"\b(bye|goodbye|see ya|later|peace|cya|gtg|gotta go)\b",
        ],
        "responses": [
            "Later {user}! Take it easy.",
            "See ya {user}!",
            "Peace out {user}!",
            "Catch you later {user}!",
        ],
    },
    {
        "name": "thanks",
        "patterns": [
            r"\b(thanks|thank you|thx|ty|appreciate)\b",
        ],
        "responses": [
            "No problem {user}!",
            "Anytime {user}!",
            "You got it {user}!",
            "Happy to help {user}!",
        ],
    },
    {
        "name": "how_are_you",
        "patterns": [
            r"\bhow (are you|you doing|are things|is it going)\b",
        ],
        "responses": [
            "I'm running smooth! All systems green. How about you {user}?",
            "Doing great, {user}! CPU temp is chill and RAM is plenty.",
            "I'm good! Just keeping an eye on the server. What's up {user}?",
        ],
    },
    {
        "name": "who_are_you",
        "patterns": [
            r"\b(who are you|what are you|what do you do)\b",
        ],
        "responses": [
            "I'm Vector! I help manage this server – monitoring, reminders, and whatever you need. Try `/help` to see what I can do.",
            "Name's Vector. I keep tabs on the server, handle reminders, and try to be useful. `/help` has the full list!",
        ],
    },
    {
        "name": "server_status",
        "patterns": [
            r"\b(server|status|how'?s the server|server doing)\b",
        ],
        "responses": [
            "Want the full rundown? Try `/server` for live stats, {user}!",
            "Use `/server` to see CPU, RAM, and load – or `/docker` for container status!",
        ],
    },
    {
        "name": "help",
        "patterns": [
            r"\b(help|commands|what can you do)\b",
        ],
        "responses": [
            "Try `/help` for the full command list, {user}! I can monitor your server, set reminders, and more.",
            "Here's a quick rundown: `/server` for stats, `/remindme` for reminders, `/docker` for containers. Use `/help` for everything!",
        ],
    },
    {
        "name": "joke",
        "patterns": [
            r"\b(joke|funny|make me laugh|humor)\b",
        ],
        "responses": [
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "There are 10 types of people in the world: those who understand binary and those who don't.",
            "A SQL query walks into a bar, sees two tables, and asks: 'Can I JOIN you?'",
            "Why was the JavaScript developer sad? Because he didn't Node how to Express himself.",
            "I told my wife she was drawing her eyebrows too high. She looked surprised.",
        ],
    },
    {
        "name": "minecraft",
        "patterns": [
            r"\b(minecraft|mc server|creeper|enderman|nether)\b",
        ],
        "responses": [
            "The MC server should be running! Check `/docker` to verify the container status.",
            "Minecraft stuff? I can check if the server container is up – try `/docker`!",
        ],
    },
    {
        "name": "fallback",
        "patterns": [],  # Matches anything not caught above
        "responses": [
            "Hmm, not sure what you mean {user}. Try `/help` to see what I can do!",
            "I didn't quite catch that, {user}. Use `/ask` or `/help` if you need something specific!",
            "Not sure about that one. I'm better with server stuff – try `/help`!",
        ],
    },
]


def match_intent(text: str) -> dict:
    """Find the best matching intent for the given text."""
    text_lower = text.lower()
    for intent in INTENTS:
        if not intent["patterns"]:  # Skip fallback
            continue
        for pattern in intent["patterns"]:
            if re.search(pattern, text_lower):
                return intent
    return INTENTS[-1]  # Fallback


class Smart(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Mention handler ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        # Ignore own messages and other bots
        if message.author.bot:
            return

        # Only respond to mentions
        if not self.bot.user or self.bot.user not in message.mentions:
            return

        # Strip the mention from the text
        clean = message.content
        for mention_pattern in [f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"]:
            clean = clean.replace(mention_pattern, "").strip()

        if not clean:
            clean = "hello"

        intent = match_intent(clean)
        response = random.choice(intent["responses"])
        response = response.replace("{user}", message.author.display_name)

        await message.reply(response)

    # ── /ask ──────────────────────────────────────────────────────────

    @nextcord.slash_command(name="ask", description="Ask Vector something", guild_ids=Config.GUILD_IDS)
    async def ask_slash(self, interaction: nextcord.Interaction, question: str):
        intent = match_intent(question)
        response = random.choice(intent["responses"])
        response = response.replace("{user}", interaction.user.display_name)
        await interaction.response.send_message(response)

    @commands.command(name="ask")
    async def ask_cmd(self, ctx, *, question: str):
        intent = match_intent(question)
        response = random.choice(intent["responses"])
        response = response.replace("{user}", ctx.author.display_name)
        await ctx.reply(response)


def setup(bot):
    bot.add_cog(Smart(bot))
