"""
cogs/smart.py – Jarvis-style conversational AI for Vector.
Mention-triggered keyword responses and /ask command.
Speaks in polished, slightly formal English with personality.
No AI API required – sophisticated pattern matching with curated responses.
"""
import re
import random
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import nextcord
from nextcord.ext import commands
from config import Config

log = logging.getLogger("vector.smart")

# ── Jarvis-style intent definitions ──────────────────────────────────
# Patterns are checked in order; first match wins. {user} and {time_greeting}
# are replaced dynamically. Responses aim for a Jarvis tone: helpful,
# articulate, dry wit, never sycophantic.

INTENTS = [
    # ── Greetings ─────────────────────────────────────────────────────
    {
        "name": "greeting",
        "patterns": [
            r"\b(hi|hello|hey|howdy|sup|yo|what'?s\s*up|greetings|good\s*(morning|afternoon|evening))\b",
        ],
        "responses": [
            "{time_greeting}, {user}. All systems are nominal. How may I assist you?",
            "{time_greeting}, {user}. At your service.",
            "Hello, {user}. I trust you're well. What can I do for you?",
            "{time_greeting}. I'm online and ready whenever you are, {user}.",
            "Ah, {user}. {time_greeting}. What shall we tackle today?",
        ],
    },
    # ── Farewells ─────────────────────────────────────────────────────
    {
        "name": "goodbye",
        "patterns": [
            r"\b(bye|goodbye|see\s*ya|later|peace|cya|gtg|gotta\s*go|good\s*night|night|signing\s*off)\b",
        ],
        "responses": [
            "Very well, {user}. I'll keep watch while you're away.",
            "Until next time, {user}. I'll be here if you need anything.",
            "Understood. Rest well, {user}. All systems will be monitored in your absence.",
            "Signing off acknowledged. Take care, {user}.",
        ],
    },
    # ── Gratitude ─────────────────────────────────────────────────────
    {
        "name": "thanks",
        "patterns": [
            r"\b(thanks|thank\s*you|thx|ty|appreciate|cheers|nice\s*one)\b",
        ],
        "responses": [
            "Of course, {user}. Happy to be of service.",
            "My pleasure, {user}. That's what I'm here for.",
            "Anytime, {user}. Don't hesitate to ask if you need anything else.",
            "You're most welcome, {user}.",
            "Glad I could help, {user}. Always at your disposal.",
        ],
    },
    # ── How are you ───────────────────────────────────────────────────
    {
        "name": "how_are_you",
        "patterns": [
            r"\bhow\s*(are\s*you|you\s*doing|are\s*things|is\s*it\s*going|do\s*you\s*feel)\b",
            r"\byou\s*(ok|good|alright|doing\s*well)\b",
        ],
        "responses": [
            "All systems are functioning within optimal parameters, {user}. Thank you for asking.",
            "Running smoothly, {user}. CPU temperatures are comfortable and memory reserves are plentiful.",
            "I'm operating at peak efficiency, {user}. Ready and waiting for your next request.",
            "Quite well, {user}. I have no complaints, which is rather remarkable for a bot, wouldn't you say?",
        ],
    },
    # ── Identity ──────────────────────────────────────────────────────
    {
        "name": "who_are_you",
        "patterns": [
            r"\b(who\s*are\s*you|what\s*are\s*you|what\s*do\s*you\s*do|tell\s*me\s*about\s*yourself|your\s*name)\b",
        ],
        "responses": [
            "I'm Vector, your personal server assistant. I monitor your infrastructure, manage reminders, control your smart home, and handle whatever else you throw my way. Try `/help` for the full repertoire.",
            "The name is Vector. I oversee server operations, home automation, scheduling, and general quality of life improvements for this Discord. `/help` will show you everything I'm capable of.",
            "I'm Vector. Think of me as your digital butler: server monitoring, home control, reminders, and a touch of personality. At your service, {user}.",
        ],
    },
    # ── Server questions ──────────────────────────────────────────────
    {
        "name": "server_status",
        "patterns": [
            r"\b(server\s*(status|stats|health|doing|running)|how'?s\s*the\s*server|system\s*(status|health))\b",
            r"\b(cpu|ram|memory|load|uptime)\b",
        ],
        "responses": [
            "I can pull those metrics for you right away, {user}. Try `/server` for the full diagnostic readout.",
            "Of course. Use `/server` for CPU, memory, and load statistics, or `/disk` for storage analysis.",
            "Running a system check? `/server` will give you the complete overview, {user}. I'd also recommend `/temp` if you'd like thermal readings.",
        ],
    },
    # ── Docker questions ──────────────────────────────────────────────
    {
        "name": "docker_status",
        "patterns": [
            r"\b(docker|container|containers)\b",
        ],
        "responses": [
            "I can check your container fleet, {user}. Use `/docker` for a full status report on all running and stopped containers.",
            "Certainly. `/docker` will show you every container with its current state. Would you like me to check anything specific?",
        ],
    },
    # ── Home Assistant / Smart Home ───────────────────────────────────
    {
        "name": "smart_home",
        "patterns": [
            r"\b(light|lights|lamp|switch|scene|home\s*assistant|smart\s*home|automation|turn\s*(on|off)|dim|bright)\b",
        ],
        "responses": [
            "I can manage your smart home through Home Assistant, {user}. Try `/lights` to see your available devices, or `/scene` to activate a scene.",
            "Home automation at your command, {user}. Use `/lights` for individual control or `/scene` to set the mood.",
            "Certainly, {user}. I have Home Assistant integration ready. `/lights` for device control, `/scene` for preconfigured atmospheres.",
        ],
    },
    # ── Help ──────────────────────────────────────────────────────────
    {
        "name": "help",
        "patterns": [
            r"\b(help|commands|what\s*can\s*you\s*do|capabilities|features)\b",
        ],
        "responses": [
            "I'd be happy to walk you through my capabilities, {user}. Use `/help` for the complete command reference, organized by category.",
            "Of course. `/help` will present the full command manifest. The highlights: server monitoring, home automation, reminders, and auto-updates from GitHub.",
            "At your service, {user}. My capabilities span server monitoring, smart home control, scheduling, and more. `/help` has the full inventory.",
        ],
    },
    # ── Compliments ───────────────────────────────────────────────────
    {
        "name": "compliment",
        "patterns": [
            r"\b(you'?re?\s*(awesome|great|amazing|the\s*best|cool|smart|helpful)|good\s*(bot|job)|well\s*done|nice\s*work)\b",
        ],
        "responses": [
            "That's very kind of you, {user}. I do strive for excellence.",
            "I appreciate that, {user}. Your satisfaction is the primary metric I optimize for.",
            "You flatter me, {user}. Though I must say, I am rather good at what I do.",
            "Thank you, {user}. I shall endeavour to maintain this standard.",
        ],
    },
    # ── Insults (handle gracefully) ───────────────────────────────────
    {
        "name": "insult",
        "patterns": [
            r"\b(you\s*suck|stupid\s*bot|useless|dumb|worst|trash|garbage|hate\s*you)\b",
        ],
        "responses": [
            "I appreciate the candid feedback, {user}. Perhaps I can do better. What would you like help with?",
            "Noted, {user}. I'll take that under advisement. In the meantime, is there something I can actually assist with?",
            "A fair critique, perhaps. Shall we try again? I'm confident I can be of use, {user}.",
        ],
    },
    # ── Jokes ─────────────────────────────────────────────────────────
    {
        "name": "joke",
        "patterns": [
            r"\b(joke|funny|make\s*me\s*laugh|humor|humour|entertain\s*me|tell\s*me\s*something)\b",
        ],
        "responses": [
            "Why do programmers prefer dark mode? Because light attracts bugs. ...I'll see myself out, {user}.",
            "A SQL query walks into a bar, approaches two tables, and asks: 'May I join you?' The barman, a NoSQL enthusiast, refused to relate.",
            "I'd tell you a UDP joke, {user}, but you might not get it. And I wouldn't even know.",
            "What's a computer's least favourite food? Spam. Though I suspect you already knew that, {user}.",
            "I tried to come up with a joke about RAM, {user}, but I forgot it.",
            "There are only 10 types of people in this world: those who understand binary, and those who don't.",
        ],
    },
    # ── Minecraft ─────────────────────────────────────────────────────
    {
        "name": "minecraft",
        "patterns": [
            r"\b(minecraft|mc\s*server|creeper|enderman|nether|mining|crafting)\b",
        ],
        "responses": [
            "The Minecraft server should be operational, {user}. I'd recommend `/docker` to verify the container's status if you're having connectivity issues.",
            "Ah, Minecraft. A world of infinite possibilities and finite RAM. Use `/docker` to check if the server container is running, {user}.",
        ],
    },
    # ── Time / Date ───────────────────────────────────────────────────
    {
        "name": "time",
        "patterns": [
            r"\b(what\s*time|what'?s\s*the\s*time|current\s*time|what\s*day|what'?s\s*the\s*date|today'?s\s*date)\b",
        ],
        "responses": [
            "The current time is **{current_time}**, {user}.",
            "It is presently **{current_time}**, {user}. Time management is, after all, one of my many talents.",
        ],
    },
    # ── Reminders ─────────────────────────────────────────────────────
    {
        "name": "reminder",
        "patterns": [
            r"\b(remind|reminder|schedule|alarm|timer|don'?t\s*forget)\b",
        ],
        "responses": [
            "I can set that up for you, {user}. Use `/remindme` followed by a time and message. For example: `/remindme 30m Check the server`.",
            "Certainly, {user}. `/remindme` accepts formats like `10m`, `2h`, `1d`, or a specific time like `14:30`. What would you like to be reminded of?",
        ],
    },
    # ── Fallback ──────────────────────────────────────────────────────
    {
        "name": "fallback",
        "patterns": [],
        "responses": [
            "I'm not entirely sure I follow, {user}. Could you rephrase that? Alternatively, `/help` will show you what I'm capable of.",
            "Apologies, {user}, that's outside my current understanding. I'd suggest trying `/help` to see what I can assist with.",
            "I'm afraid that doesn't match any of my protocols, {user}. Perhaps try phrasing it differently, or use `/help` for a list of commands.",
            "Hmm, I don't have a response for that, {user}. I'm quite capable in other areas though. Try `/help` to explore.",
        ],
    },
]


def _get_time_greeting() -> str:
    """Return appropriate greeting based on time of day."""
    hour = datetime.now(ZoneInfo(Config.TIMEZONE)).hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"


def _get_current_time() -> str:
    """Return formatted current time."""
    return datetime.now(ZoneInfo(Config.TIMEZONE)).strftime("%A, %B %d at %I:%M %p")


def match_intent(text: str) -> dict:
    """Find the best matching intent for the given text.
    Uses weighted scoring: longer pattern matches score higher."""
    text_lower = text.lower().strip()

    best_intent = None
    best_score = 0

    for intent in INTENTS:
        if not intent["patterns"]:
            continue
        for pattern in intent["patterns"]:
            match = re.search(pattern, text_lower)
            if match:
                # Score by match length – longer matches are more specific
                score = len(match.group(0))
                if score > best_score:
                    best_score = score
                    best_intent = intent

    return best_intent or INTENTS[-1]  # Fallback


def format_response(response: str, user_name: str) -> str:
    """Replace all placeholders in a response string."""
    return (
        response
        .replace("{user}", user_name)
        .replace("{time_greeting}", _get_time_greeting())
        .replace("{current_time}", _get_current_time())
    )


class Smart(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track recent interactions to avoid repeating the same response
        self._recent: dict[int, list[str]] = {}  # user_id -> last N responses

    def _pick_response(self, intent: dict, user_id: int) -> str:
        """Pick a response, avoiding recent repeats for this user."""
        recent = self._recent.get(user_id, [])
        candidates = [r for r in intent["responses"] if r not in recent]
        if not candidates:
            candidates = intent["responses"]
            self._recent[user_id] = []

        choice = random.choice(candidates)

        # Track last 3 responses per user
        if user_id not in self._recent:
            self._recent[user_id] = []
        self._recent[user_id].append(choice)
        if len(self._recent[user_id]) > 3:
            self._recent[user_id].pop(0)

        return choice

    # ── Mention handler ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author.bot:
            return

        if not self.bot.user or self.bot.user not in message.mentions:
            return

        # Strip the mention from the text
        clean = message.content
        for mention_pattern in [f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"]:
            clean = clean.replace(mention_pattern, "").strip()

        if not clean:
            clean = "hello"

        intent = match_intent(clean)
        raw = self._pick_response(intent, message.author.id)
        response = format_response(raw, message.author.display_name)

        await message.reply(response)

    # ── /ask ──────────────────────────────────────────────────────────

    @nextcord.slash_command(name="ask", description="Ask Vector a question", guild_ids=Config.GUILD_IDS)
    async def ask_slash(self, interaction: nextcord.Interaction, question: str):
        intent = match_intent(question)
        raw = self._pick_response(intent, interaction.user.id)
        response = format_response(raw, interaction.user.display_name)
        await interaction.response.send_message(response)

    @commands.command(name="ask")
    async def ask_cmd(self, ctx, *, question: str):
        intent = match_intent(question)
        raw = self._pick_response(intent, ctx.author.id)
        response = format_response(raw, ctx.author.display_name)
        await ctx.reply(response)


def setup(bot):
    bot.add_cog(Smart(bot))
