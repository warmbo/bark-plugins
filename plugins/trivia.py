"""
Trivia — a single-file Bark plugin: a fun multiplayer trivia game.

Features
--------
- Free-for-all channel game: anyone clicks the answer buttons on an
  interactive embed (no sign-up, no DMs).
- Questions from the Open Trivia Database (opentdb.com, no API key) with a
  built-in fallback bank when the API is unreachable or rate-limited.
- Category + difficulty selection, both per-game (slash options) and as
  server defaults (dashboard settings).
- Per-server persistent leaderboard, personal stats, and a "first correct"
  bonus that rewards speed.
- Awards Reputation points (via the built-in reputation module) for correct
  answers, capped per session so the game can't be farmed.

Install: upload this file in Bark → Settings → Modules → Plugins.
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
from datetime import datetime, timezone

import discord
import httpx
from database.engine import session_scope
from fastapi import APIRouter, Request
from modules.base import (
    BarkModule,
    CommandRegistration,
    PageRegistration,
    PermissionDefinition,
)
from services.response import api_forbidden, api_success, check_api_permission
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
    update,
)

logger = logging.getLogger("bark.plugins.trivia")

OPENTDB_URL = "https://opentdb.com/api.php"
TRIVIAAPI_URL = "https://the-trivia-api.com/v2/questions"
OPENTDB_TIMEOUT = 8.0
FETCH_RETRY_AFTER_429 = 3.0
INTERLUDE_SECONDS = 4.0

# Question sources. Order matters: sources are tried in this order when
# building a game's question pool.
SOURCE_ORDER = ("opentdb", "triviaapi", "builtin")
DEFAULT_SOURCES = {"opentdb", "triviaapi", "builtin"}
SOURCE_LABELS = {
    "opentdb": "Open Trivia DB",
    "triviaapi": "The Trivia API",
    "builtin": "Built-in bank",
}
SOURCE_DESCRIPTIONS = {
    "opentdb": "Open Trivia Database (https://opentdb.com) — free, no key, 24 categories, easy/medium/hard.",
    "triviaapi": "The Trivia API (https://the-trivia-api.com) — free, no key required, its own large question pool.",
    "builtin": "Offline-safe bank bundled with the plugin (~24 questions) — fills gaps when network sources fail or rate-limit.",
}

LETTERS = ("A", "B", "C", "D")

# Our category slug -> The Trivia API's category slug (best-effort mapping).
TRIVIAAPI_CATEGORIES: dict[str, str] = {
    "general_knowledge": "general_knowledge",
    "books": "arts_and_literature",
    "art": "arts_and_literature",
    "film": "film_and_tv",
    "television": "film_and_tv",
    "musicals_theatres": "film_and_tv",
    "comics": "film_and_tv",
    "anime_manga": "film_and_tv",
    "cartoons_animations": "film_and_tv",
    "music": "music",
    "science_nature": "science",
    "computers": "science",
    "mathematics": "science",
    "gadgets": "science",
    "animals": "science",
    "geography": "geography",
    "history": "history",
    "mythology": "history",
    "politics": "society_and_culture",
    "celebrities": "society_and_culture",
    "vehicles": "sport_and_leisure",
    "video_games": "sport_and_leisure",
    "board_games": "sport_and_leisure",
}
REVERSE_TRIVIAAPI_CATEGORIES: dict[str, str] = {}
for _our_slug, _their_slug in TRIVIAAPI_CATEGORIES.items():
    # Multiple local slugs share a The Trivia API slug; keep the FIRST local
    # mapping deterministically for display purposes.
    REVERSE_TRIVIAAPI_CATEGORIES.setdefault(_their_slug, _our_slug)

# OpenTDB results carry the category as a display NAME (e.g. "Science:
# Computers"), not an id. Map names back to our slugs for the footer.
OPENTDB_NAME_TO_SLUG: dict[str, str] = {
    "General Knowledge": "general_knowledge",
    "Entertainment: Books": "books",
    "Entertainment: Film": "film",
    "Entertainment: Music": "music",
    "Entertainment: Musicals & Theatres": "musicals_theatres",
    "Entertainment: Television": "television",
    "Entertainment: Video Games": "video_games",
    "Entertainment: Board Games": "board_games",
    "Science & Nature": "science_nature",
    "Science: Computers": "computers",
    "Science: Mathematics": "mathematics",
    "Science: Gadgets": "gadgets",
    "Mythology": "mythology",
    "Geography": "geography",
    "History": "history",
    "Politics": "politics",
    "Art": "art",
    "Celebrities": "celebrities",
    "Animals": "animals",
    "Vehicles": "vehicles",
    "Entertainment: Comics": "comics",
    "Entertainment: Japanese Anime & Manga": "anime_manga",
    "Entertainment: Cartoon & Animations": "cartoons_animations",
}

# Open Trivia Database category id -> slug used in dashboard settings.
CATEGORY_IDS: dict[str, int] = {
    "any": 0,
    "general_knowledge": 9,
    "books": 10,
    "film": 11,
    "music": 12,
    "musicals_theatres": 13,
    "television": 14,
    "video_games": 15,
    "board_games": 16,
    "science_nature": 17,
    "computers": 18,
    "mathematics": 19,
    "mythology": 20,
    "geography": 21,
    "history": 22,
    "politics": 23,
    "art": 24,
    "celebrities": 25,
    "animals": 26,
    "vehicles": 27,
    "comics": 28,
    "gadgets": 29,
    "anime_manga": 30,
    "cartoons_animations": 31,
}
ID_TO_CATEGORY = {value: key for key, value in CATEGORY_IDS.items()}

DIFFICULTIES = ("any", "easy", "medium", "hard")

# ── Persistent leaderboard ─────────────────────────────
# A single-file plugin cannot register ORM models before init_db() runs, so
# the table is created in enable() with SQLAlchemy Core.

_METADATA = MetaData()

trivia_scores = Table(
    "trivia_scores",
    _METADATA,
    Column("guild_id", String(32), primary_key=True),
    Column("user_id", String(32), primary_key=True),
    Column("display_name", String(100), nullable=False, default=""),
    Column("points", Integer, nullable=False, default=0),
    Column("correct", Integer, nullable=False, default=0),
    Column("answered", Integer, nullable=False, default=0),
    Column("games_played", Integer, nullable=False, default=0),
    Column("best_streak", Integer, nullable=False, default=0),
    Column("updated_at", String(32), nullable=False, default=""),
)

# ── Built-in fallback bank (used when OpenTDB is down / rate-limited) ──
_FALLBACK_QUESTIONS: list[dict] = [
    {"question": "What geometric shape is generally used for stop signs?", "options": ["Circle", "Octagon", "Triangle", "Hexagon"], "answer": 1, "category": "general_knowledge", "difficulty": "easy"},
    {"question": "How many continents are there on Earth?", "options": ["5", "6", "7", "8"], "answer": 2, "category": "general_knowledge", "difficulty": "easy"},
    {"question": "What is the chemical symbol for water?", "options": ["H2O", "O2", "CO2", "NaCl"], "answer": 0, "category": "science_nature", "difficulty": "easy"},
    {"question": "Which planet is known as the Red Planet?", "options": ["Venus", "Mars", "Jupiter", "Saturn"], "answer": 1, "category": "science_nature", "difficulty": "easy"},
    {"question": "What is the largest mammal in the world?", "options": ["African Elephant", "Blue Whale", "Giraffe", "Orca"], "answer": 1, "category": "animals", "difficulty": "easy"},
    {"question": "How many legs does a spider have?", "options": ["6", "8", "10", "12"], "answer": 1, "category": "animals", "difficulty": "easy"},
    {"question": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": 2, "category": "geography", "difficulty": "easy"},
    {"question": "Which country has the largest population?", "options": ["USA", "India", "China", "Indonesia"], "answer": 1, "category": "geography", "difficulty": "medium"},
    {"question": "In which year did World War II end?", "options": ["1943", "1944", "1945", "1946"], "answer": 2, "category": "history", "difficulty": "medium"},
    {"question": "Who painted the Mona Lisa?", "options": ["Michelangelo", "Leonardo da Vinci", "Raphael", "Donatello"], "answer": 1, "category": "art", "difficulty": "easy"},
    {"question": "What is the smallest prime number?", "options": ["0", "1", "2", "3"], "answer": 2, "category": "mathematics", "difficulty": "easy"},
    {"question": "What is the value of pi to two decimal places?", "options": ["3.14", "3.15", "3.13", "3.41"], "answer": 0, "category": "mathematics", "difficulty": "easy"},
    {"question": "Which company created the iPhone?", "options": ["Samsung", "Google", "Apple", "Microsoft"], "answer": 2, "category": "computers", "difficulty": "easy"},
    {"question": "What does 'HTTP' stand for?", "options": ["HyperText Transfer Protocol", "HighText Transmission Process", "Hyperlink Transfer Protocol", "HyperText Translation Program"], "answer": 0, "category": "computers", "difficulty": "medium"},
    {"question": "Which game features a plumber named Mario?", "options": ["Sonic", "Super Mario", "Zelda", "Pac-Man"], "answer": 1, "category": "video_games", "difficulty": "easy"},
    {"question": "What is the best-selling video game of all time?", "options": ["Minecraft", "Grand Theft Auto V", "Tetris", "Wii Sports"], "answer": 0, "category": "video_games", "difficulty": "medium"},
    {"question": "Who wrote 'Romeo and Juliet'?", "options": ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"], "answer": 1, "category": "books", "difficulty": "easy"},
    {"question": "What is the name of the wizard boy who lives at 4 Privet Drive?", "options": ["Harry Potter", "Ron Weasley", "Draco Malfoy", "Neville Longbottom"], "answer": 0, "category": "books", "difficulty": "easy"},
    {"question": "Which band performed 'Bohemian Rhapsody'?", "options": ["The Beatles", "Queen", "Pink Floyd", "Led Zeppelin"], "answer": 1, "category": "music", "difficulty": "easy"},
    {"question": "What is the tallest mountain on Earth?", "options": ["K2", "Kilimanjaro", "Mount Everest", "Denali"], "answer": 2, "category": "geography", "difficulty": "easy"},
    {"question": "Which country is known as the Land of the Rising Sun?", "options": ["China", "South Korea", "Japan", "Thailand"], "answer": 2, "category": "geography", "difficulty": "easy"},
    {"question": "How many hearts does an octopus have?", "options": ["1", "2", "3", "4"], "answer": 2, "category": "animals", "difficulty": "medium"},
    {"question": "What is the currency of Japan?", "options": ["Yuan", "Won", "Yen", "Ringgit"], "answer": 2, "category": "general_knowledge", "difficulty": "easy"},
    {"question": "Which element has the atomic number 1?", "options": ["Oxygen", "Helium", "Hydrogen", "Carbon"], "answer": 2, "category": "science_nature", "difficulty": "easy"},
]


# ── Interactive answer view ────────────────────────────


class _TriviaView(discord.ui.View):
    """Button row (A/B/C/D) attached to the current question embed."""

    def __init__(self, module: TriviaPlugin, question_index: int, options: list[str]):
        super().__init__(timeout=None)
        self.module = module
        self.question_index = question_index
        for index, _option in enumerate(options):
            button = discord.ui.Button(
                label=LETTERS[index],
                style=discord.ButtonStyle.primary,
                row=index // 2,
                custom_id=f"trivia_q{question_index}_{index}",
            )
            button.callback = self._make_callback(index)
            self.add_item(button)

    def _make_callback(self, option_index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self.module._on_answer(interaction, self.question_index, option_index)

        return callback


# ── Module ─────────────────────────────────────────────


class TriviaPlugin(BarkModule):
    name = "trivia"
    version = "1.1.0"
    description = "Multiplayer trivia: interactive embeds, leaderboards, and Reputation points."
    author = "Bark Plugins"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._sessions: dict[int, _TriviaSession] = {}
        self._tasks: set[asyncio.Task] = set()
        self._last_end: dict[int, dict[int, float]] = {}

    # ── Registration ───────────────────────────────────

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/trivia",
                label="Trivia",
                icon="brain",
                category="fun",
            )
        ]

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="trivia",
                description="Play multiplayer trivia! /trivia start",
            )
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="trivia.manage", label="Manage Trivia"),
            PermissionDefinition(name="trivia.view", label="View Trivia Data"),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Server defaults for trivia games. Slash-command options "
            "override these for a single game.",
            "properties": {
                "default_category": {
                    "type": "string",
                    "title": "Default Category",
                    "description": "Question category used when /trivia start is run "
                    "without a category.",
                    "enum": sorted(CATEGORY_IDS.keys()),
                    "default": "any",
                },
                "default_difficulty": {
                    "type": "string",
                    "title": "Default Difficulty",
                    "enum": list(DIFFICULTIES),
                    "default": "any",
                },
                "questions_per_session": {
                    "type": "integer",
                    "title": "Questions per Game",
                    "minimum": 5,
                    "maximum": 20,
                    "default": 10,
                },
                "time_per_question": {
                    "type": "integer",
                    "title": "Seconds per Question",
                    "minimum": 10,
                    "maximum": 60,
                    "default": 20,
                },
                "points_per_correct": {
                    "type": "integer",
                    "title": "Trivia Points per Correct Answer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                },
                "first_correct_bonus": {
                    "type": "integer",
                    "title": "First-Correct Bonus (trivia points)",
                    "description": "Extra trivia points for the first player to answer "
                    "a question correctly.",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 2,
                },
                "rep_points_per_correct": {
                    "type": "integer",
                    "title": "Reputation Points per Correct Answer",
                    "description": "How many Reputation points a correct answer earns. "
                    "0 disables reputation rewards.",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 2,
                },
                "rep_points_per_session_cap": {
                    "type": "integer",
                    "title": "Max Reputation Points per Game",
                    "description": "Per-player cap per game, so trivia can't be farmed "
                    "for reputation.",
                    "minimum": 0,
                    "maximum": 100,
                    "default": 15,
                },
                "session_cooldown_seconds": {
                    "type": "integer",
                    "title": "Cooldown Between Games (seconds)",
                    "minimum": 0,
                    "maximum": 600,
                    "default": 60,
                },
                "source_opentdb": {
                    "type": "boolean",
                    "title": "Open Trivia Database (opentdb.com)",
                    "description": SOURCE_DESCRIPTIONS["opentdb"],
                    "default": True,
                },
                "source_triviaapi": {
                    "type": "boolean",
                    "title": "The Trivia API (the-trivia-api.com)",
                    "description": SOURCE_DESCRIPTIONS["triviaapi"],
                    "default": True,
                },
                "source_builtin": {
                    "type": "boolean",
                    "title": "Built-in Question Bank",
                    "description": SOURCE_DESCRIPTIONS["builtin"],
                    "default": True,
                },
            },
        }

    def get_actions(self) -> list[dict]:
        return [
            {
                "id": "leaderboard",
                "label": "View Leaderboard",
                "description": "Show the top trivia players for this server.",
                "fields": [],
                "endpoint": "leaderboard",
            },
            {
                "id": "reset_scores",
                "label": "Reset Leaderboard",
                "description": "Wipe all trivia scores for this server. This cannot be undone.",
                "fields": [],
                "endpoint": "reset_scores",
                "destructive": True,
            },
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "How it works",
                "stories": [
                    {"prefix": "🎮", "text": "Anyone can start a game with /trivia start in a channel. Questions post as interactive embeds — click A/B/C/D to answer."},
                    {"prefix": "🏆", "text": "Correct answers earn trivia points; the first correct answer earns a speed bonus. Scores accumulate on a per-server leaderboard."},
                    {"prefix": "⭐", "text": "Correct answers also earn Reputation points (capped per game), so trivia feeds the same Reputation system as the rest of the server."},
                ],
            },
            {
                "title": "Question sources",
                "stories": [
                    {"prefix": "📚", "text": "Open Trivia Database — opentdb.com. Free API, no key required, 24 categories, easy/medium/hard difficulty."},
                    {"prefix": "🌐", "text": "The Trivia API — the-trivia-api.com. Free API, no key required, a second large question pool with its own categories."},
                    {"prefix": "📦", "text": "Built-in bank — questions bundled with the plugin (~24). Offline-safe; fills any gap when a network source is down or rate-limited."},
                    {"prefix": "🎛️", "text": "Which sources are used is a per-server setting (Configure tab). Every question shows its source in the embed footer, and the end-of-game summary shows the mix."},
                ],
            },
        ]

    def get_api_routes(self):
        router = APIRouter(tags=["module-trivia"])

        @router.post("/guilds/{guild_id}/modules/trivia/leaderboard")
        async def trivia_leaderboard(request: Request, guild_id: str):
            if not check_api_permission(request, "trivia.view", guild_id):
                return api_forbidden()
            rows = await self._top_scores(int(guild_id), 10)
            lines = ["**🏆 Top 10 — Trivia Leaderboard**", ""]
            if not rows:
                lines.append("No trivia scores yet. Start a game with `/trivia start`!")
            for rank, row in enumerate(rows, start=1):
                name = row["display_name"] or f"<user {row['user_id']}>"
                lines.append(
                    f"{rank}. **{name}** — {row['points']} pts "
                    f"({row['correct']}/{row['answered']} correct)"
                )
            return api_success({"message": "\n".join(lines)})

        @router.post("/guilds/{guild_id}/modules/trivia/reset_scores")
        async def trivia_reset_scores(request: Request, guild_id: str):
            if not check_api_permission(request, "trivia.manage", guild_id):
                return api_forbidden()
            async with session_scope() as session:
                await session.execute(
                    delete(trivia_scores).where(trivia_scores.c.guild_id == str(guild_id))
                )
                await session.commit()
            return api_success({"message": "Trivia leaderboard reset for this server."})

        return router

    # ── Lifecycle ──────────────────────────────────────

    async def enable(self) -> None:
        from database.engine import get_engine

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(_METADATA.create_all)
        self._sessions.clear()
        self._logger.info("Trivia plugin enabled (leaderboard table ready)")

    async def disable(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for session in list(self._sessions.values()):
            session.cancelled = True
            if session.view is not None:
                session.view.stop()
        self._tasks.clear()
        self._sessions.clear()

    # ── Slash command group ────────────────────────────

    def _make_trivia_command(self):
        group = discord.app_commands.Group(name="trivia", description="Play multiplayer trivia!")

        category_choices = [
            discord.app_commands.Choice(name="Any Category", value=0),
            *[
                discord.app_commands.Choice(name=slug.replace("_", " ").title(), value=cid)
                for slug, cid in sorted(CATEGORY_IDS.items(), key=lambda item: item[1])
                if cid != 0
            ],
        ]

        @group.command(name="start", description="Start a trivia game in this channel")
        @discord.app_commands.describe(
            category="Question category (defaults to the server setting)",
            difficulty="Difficulty (defaults to the server setting)",
            questions="Number of questions, 5-20 (default 10)",
        )
        @discord.app_commands.choices(
            category=category_choices,
            difficulty=[
                discord.app_commands.Choice(name="Any", value="any"),
                discord.app_commands.Choice(name="Easy", value="easy"),
                discord.app_commands.Choice(name="Medium", value="medium"),
                discord.app_commands.Choice(name="Hard", value="hard"),
            ],
        )
        async def trivia_start(
            interaction: discord.Interaction,
            category: int = 0,
            difficulty: str = "any",
            questions: int = 0,
        ):
            await self._cmd_start(interaction, category, difficulty, questions)

        @group.command(name="stop", description="Stop the current trivia game")
        async def trivia_stop(interaction: discord.Interaction):
            await self._cmd_stop(interaction)

        @group.command(name="leaderboard", description="Show the trivia leaderboard")
        @discord.app_commands.describe(top="How many entries to show (1-25, default 10)")
        async def trivia_leaderboard_cmd(interaction: discord.Interaction, top: int = 10):
            await self._cmd_leaderboard(interaction, top)

        @group.command(name="stats", description="Show trivia stats for a member")
        @discord.app_commands.describe(member="Member to look up (defaults to you)")
        async def trivia_stats(
            interaction: discord.Interaction, member: discord.Member | None = None
        ):
            await self._cmd_stats(interaction, member)

        @group.command(name="categories", description="List available trivia categories")
        async def trivia_categories(interaction: discord.Interaction):
            await self._cmd_categories(interaction)

        return group

    # ── Command handlers ───────────────────────────────

    async def _cmd_start(
        self,
        interaction: discord.Interaction,
        category: int,
        difficulty: str,
        questions: int,
    ) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or channel is None:
            await self._ephemeral(interaction, "Trivia only works in a server channel.")
            return

        config = await self.load_dashboard_config(int(guild.id))
        if category <= 0:
            category = CATEGORY_IDS.get(config.get("default_category", "any"), 0)
        if difficulty not in DIFFICULTIES:
            difficulty = config.get("default_difficulty", "any") or "any"
        if questions <= 0:
            questions = int(config.get("questions_per_session", 10) or 10)
        questions = max(5, min(questions, 20))

        if channel.id in self._sessions:
            await self._ephemeral(
                interaction,
                "A trivia game is already running in this channel! Stop it with "
                "`/trivia stop` or wait for it to finish.",
            )
            return

        cooldown = int(config.get("session_cooldown_seconds", 60) or 0)
        last_end = self._last_end.get(int(guild.id), {}).get(channel.id, 0)
        remaining = cooldown - (self._now() - last_end)
        if remaining > 0:
            await self._ephemeral(
                interaction, f"Trivia is on cooldown — try again in {int(remaining)}s."
            )
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Fetching questions… 🧠", ephemeral=True)

        parsed = await self._build_question_pool(category, difficulty, questions, config)
        if not parsed:
            await interaction.followup.send(
                "Could not load any trivia questions — no enabled source returned "
                "anything. Check which sources are enabled in Trivia settings.",
                ephemeral=True,
            )
            return

        session = _TriviaSession(
            guild_id=int(guild.id),
            channel_id=channel.id,
            questions=parsed[:questions],
            starter_id=interaction.user.id,
            time_per_question=int(config.get("time_per_question", 20) or 20),
            points_per_correct=int(config.get("points_per_correct", 5) or 5),
            first_bonus=int(config.get("first_correct_bonus", 2) or 0),
            rep_per_correct=int(config.get("rep_points_per_correct", 2) or 0),
            rep_cap=int(config.get("rep_points_per_session_cap", 15) or 0),
        )
        self._sessions[channel.id] = session
        await self._post_question(session)
        source_labels = ", ".join(
            dict.fromkeys(SOURCE_LABELS.get(q.get("source", "?"), "?") for q in session.questions)
        )
        await interaction.followup.send(
            f"🎉 Trivia started — {len(session.questions)} questions! "
            f"Sources: {source_labels}. Good luck!",
            ephemeral=True,
        )

    async def _cmd_stop(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if channel is None:
            return
        session = self._sessions.get(channel.id)
        if session is None:
            await self._ephemeral(interaction, "No trivia game is running in this channel.")
            return
        can_manage = bool(
            getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False)
        )
        if interaction.user.id != session.starter_id and not can_manage:
            await self._ephemeral(
                interaction, "Only the player who started the game (or a moderator) can stop it."
            )
            return
        session.cancelled = True
        for task in list(self._tasks):
            if task.get_name() == f"trivia_close_{channel.id}":
                task.cancel()
        await self._finish_session(session, stopped=True)
        await self._ephemeral(interaction, "Trivia stopped — scores were saved.")

    async def _cmd_leaderboard(self, interaction: discord.Interaction, top: int) -> None:
        guild = interaction.guild
        if guild is None:
            return
        top = max(1, min(top, 25))
        rows = await self._top_scores(int(guild.id), top)
        embed = discord.Embed(
            title="🏆 Trivia Leaderboard",
            color=discord.Color.gold(),
            description="Nobody has played trivia here yet. Start a game with "
            "`/trivia start`!" if not rows else None,
        )
        if rows:
            lines = []
            for rank, row in enumerate(rows, start=1):
                name = row["display_name"] or self._resolve_name(guild, row["user_id"])
                lines.append(
                    f"{rank}. **{name}** — {row['points']} pts "
                    f"({row['correct']}/{row['answered']} correct)"
                )
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"Top {len(rows)} • trivia points")
        await interaction.response.send_message(embed=embed)

    async def _cmd_stats(
        self, interaction: discord.Interaction, member: discord.Member | None
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        target = member or interaction.user
        row = await self._player_stats(int(guild.id), int(target.id))
        embed = discord.Embed(
            title=f"📊 Trivia Stats — {target.display_name}",
            color=discord.Color.blurple(),
        )
        if row is None:
            embed.description = "No trivia stats yet. Join a game with `/trivia start`!"
        else:
            accuracy = (
                f"{100 * row['correct'] // max(1, row['answered'])}%"
                if row["answered"]
                else "—"
            )
            embed.add_field(name="Points", value=str(row["points"]), inline=True)
            embed.add_field(name="Correct", value=f"{row['correct']}/{row['answered']}", inline=True)
            embed.add_field(name="Accuracy", value=accuracy, inline=True)
            embed.add_field(name="Games Played", value=str(row["games_played"]), inline=True)
            embed.add_field(name="Best Streak", value=str(row["best_streak"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _cmd_categories(self, interaction: discord.Interaction) -> None:
        names = "\n".join(
            f"• {slug.replace('_', ' ').title()}" for slug in sorted(CATEGORY_IDS) if slug != "any"
        )
        embed = discord.Embed(
            title="🎯 Trivia Categories",
            color=discord.Color.blurple(),
            description="Pick one with `/trivia start category:<name>`:\n" + names,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Game loop ──────────────────────────────────────

    async def _post_question(self, session: _TriviaSession) -> None:
        if session.cancelled or session.index >= len(session.questions):
            return
        question = session.questions[session.index]
        session.closed = False
        session.answered.clear()
        session.first_correct = None

        embed = discord.Embed(
            title=f"❓ Question {session.index + 1}/{len(session.questions)}",
            color=discord.Color.blurple(),
            description=f"**{question['question']}**",
        )
        category_label = (question.get("category") or "").replace("_", " ").title()
        difficulty = question.get("difficulty") or "any"
        source_label = SOURCE_LABELS.get(question.get("source", ""), "?")
        embed.set_footer(
            text=f"{category_label} • {difficulty.title()} • 📚 {source_label} • "
            f"⏱ {session.time_per_question}s — click a button to answer"
        )
        options = question["options"]
        embed.add_field(
            name="Answers",
            value="\n".join(
                f"{LETTERS[index]}. {option}" for index, option in enumerate(options)
            ),
            inline=False,
        )

        view = _TriviaView(self, session.index, options)
        session.view = view

        if session.message is None:
            session.message = await self._send_message(session, embed=embed, view=view)
        else:
            try:
                session.message = await session.message.edit(embed=embed, view=view)
            except discord.NotFound:
                session.message = await self._send_message(session, embed=embed, view=view)

        session.ends_at = self._now() + session.time_per_question
        task = asyncio.get_running_loop().create_task(
            self._close_question(session), name=f"trivia_close_{session.channel_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _close_question(self, session: _TriviaSession) -> None:
        try:
            await asyncio.sleep(session.time_per_question)
        except asyncio.CancelledError:
            return
        if session.cancelled or session.channel_id not in self._sessions:
            return
        session.closed = True
        question = session.questions[session.index]
        correct_text = question["options"][question["answer"]]
        leader = self._standing_snippet(session)

        embed = discord.Embed(
            title=f"❓ Question {session.index + 1}/{len(session.questions)} — closed",
            color=discord.Color.green() if session.correct_count else discord.Color.red(),
            description=f"**{question['question']}**",
        )
        embed.add_field(name="✅ Correct answer", value=f"**{correct_text}**", inline=False)
        if leader:
            embed.add_field(name="🏅 Standings", value=leader, inline=False)
        try:
            await session.message.edit(embed=embed, view=None)
        except discord.NotFound:
            pass

        session.index += 1
        if session.index >= len(session.questions):
            await self._finish_session(session)
        else:
            await asyncio.sleep(INTERLUDE_SECONDS)
            if not session.cancelled and session.channel_id in self._sessions:
                await self._post_question(session)

    async def _on_answer(
        self, interaction: discord.Interaction, question_index: int, option_index: int
    ) -> None:
        channel = interaction.channel
        if channel is None:
            return
        session = self._sessions.get(channel.id)
        if session is None:
            await self._ephemeral(
                interaction,
                "There's no trivia running in this channel right now. Start one with "
                "`/trivia start`!",
            )
            return
        if session.closed or session.index != question_index:
            await self._ephemeral(
                interaction,
                "That question is already closed — the next one is on its way! ⏱",
            )
            return
        uid = int(interaction.user.id)
        if uid in session.answered:
            await self._ephemeral(interaction, "You already answered this question! 🫢")
            return

        session.answered[uid] = option_index
        session.answered_count[uid] = session.answered_count.get(uid, 0) + 1
        session.names[uid] = interaction.user.display_name

        question = session.questions[session.index]
        correct = option_index == question["answer"]
        if correct:
            session.correct_count[uid] = session.correct_count.get(uid, 0) + 1
            session.streak[uid] = session.streak.get(uid, 0) + 1
            gained = session.points_per_correct
            if session.first_correct is None:
                session.first_correct = uid
                gained += session.first_bonus
                await self._mark_first_correct(session, interaction.user.display_name)
            session.points[uid] = session.points.get(uid, 0) + gained
            reply = f"✅ **Correct!** +{gained} trivia point{'s' if gained != 1 else ''}"
            if session.first_correct == uid:
                reply += " ⚡ (first correct — speed bonus!)"
        else:
            session.streak[uid] = 0
            answer_text = question["options"][question["answer"]]
            reply = f"❌ Not quite — the answer was **{answer_text}**."

        await self._ephemeral(interaction, reply)

    async def _mark_first_correct(self, session: _TriviaSession, name: str) -> None:
        try:
            embed = session.message.embeds[0]
            embed.set_footer(
                text=f"⚡ First correct: {name} • {embed.footer.text}"
            )
            await session.message.edit(embed=embed)
        except (discord.NotFound, IndexError, AttributeError):
            pass

    async def _finish_session(self, session: _TriviaSession, stopped: bool = False) -> None:
        self._sessions.pop(session.channel_id, None)
        self._last_end.setdefault(session.guild_id, {})[session.channel_id] = self._now()

        await self._save_scores(session)
        rep_summary = await self._award_reputation(session)

        if session.message is not None and not stopped:
            embed = discord.Embed(
                title="🎉 Trivia complete!",
                color=discord.Color.gold(),
                description=f"{len(session.questions)} questions, all done. Great playing, everyone!",
            )
            if session.points:
                embed.add_field(
                    name="🏆 Final scores",
                    value=self._standing_snippet(session, limit=5),
                    inline=False,
                )
            counts: dict[str, int] = {}
            for question in session.questions:
                source = question.get("source", "builtin")
                counts[source] = counts.get(source, 0) + 1
            if counts:
                source_line = " · ".join(
                    f"{count} {SOURCE_LABELS.get(source, source)}"
                    for source, count in counts.items()
                )
                embed.add_field(name="📚 Sources", value=source_line, inline=False)
            if rep_summary:
                embed.add_field(name="⭐ Reputation", value=rep_summary, inline=False)
            embed.set_footer(text="Check /trivia leaderboard anytime")
            try:
                await session.message.edit(embed=embed, view=None)
            except discord.NotFound:
                pass
        elif stopped and session.message is not None:
            try:
                await session.message.edit(view=None)
            except discord.NotFound:
                pass

    # ── Persistence ────────────────────────────────────

    async def _save_scores(self, session: _TriviaSession) -> None:
        if not session.points and not session.correct_count:
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with session_scope() as session_db:
            for uid, points in session.points.items():
                row = (
                    await session_db.execute(
                        select(trivia_scores).where(
                            trivia_scores.c.guild_id == str(session.guild_id),
                            trivia_scores.c.user_id == str(uid),
                        )
                    )
                ).first()
                correct = session.correct_count.get(uid, 0)
                answered = session.answered_count.get(uid, 0)
                best_streak = session.streak.get(uid, 0)
                if row is None:
                    await session_db.execute(
                        insert(trivia_scores).values(
                            guild_id=str(session.guild_id),
                            user_id=str(uid),
                            display_name=session.names.get(uid, "")[:100],
                            points=points,
                            correct=correct,
                            answered=answered,
                            games_played=1,
                            best_streak=best_streak,
                            updated_at=now,
                        )
                    )
                else:
                    row_map = row._mapping
                    await session_db.execute(
                        update(trivia_scores)
                        .where(
                            trivia_scores.c.guild_id == str(session.guild_id),
                            trivia_scores.c.user_id == str(uid),
                        )
                        .values(
                            display_name=session.names.get(uid, "")[:100],
                            points=row_map["points"] + points,
                            correct=row_map["correct"] + correct,
                            answered=row_map["answered"] + answered,
                            games_played=row_map["games_played"] + 1,
                            best_streak=max(row_map["best_streak"], best_streak),
                            updated_at=now,
                        )
                    )
            await session_db.commit()

    async def _award_reputation(self, session: _TriviaSession) -> str:
        """Award Reputation points for correct answers (capped per session)."""
        if session.rep_per_correct <= 0 or session.rep_cap <= 0 or not session.correct_count:
            return ""
        reputation = self.ctx.bot.modules.get_module("reputation")
        if reputation is None or not getattr(reputation, "enabled", False):
            return ""
        awarded = 0
        for uid, correct in session.correct_count.items():
            amount = min(correct * session.rep_per_correct, session.rep_cap)
            if amount <= 0:
                continue
            try:
                await reputation._add_points(
                    session.guild_id,
                    int(uid),
                    float(amount),
                    "trivia",
                    metadata={"source": "trivia"},
                )
                awarded += 1
            except Exception:
                self._logger.exception("Trivia reputation award failed for %s", uid)
        if awarded:
            return f"{awarded} player{'s' if awarded != 1 else ''} earned Reputation points ⭐"
        return ""

    async def _top_scores(self, guild_id: int, limit: int) -> list[dict]:
        async with session_scope() as session_db:
            result = await session_db.execute(
                select(trivia_scores)
                .where(trivia_scores.c.guild_id == str(guild_id))
                .order_by(trivia_scores.c.points.desc(), trivia_scores.c.correct.desc())
                .limit(limit)
            )
            return [dict(row) for row in result.mappings()]

    async def _player_stats(self, guild_id: int, user_id: int) -> dict | None:
        async with session_scope() as session_db:
            result = await session_db.execute(
                select(trivia_scores).where(
                    trivia_scores.c.guild_id == str(guild_id),
                    trivia_scores.c.user_id == str(user_id),
                )
            )
            row = result.first()
            return dict(row._mapping) if row is not None else None

    # ── Question source ────────────────────────────────

    async def _build_question_pool(
        self, category_id: int, difficulty: str, amount: int, config: dict
    ) -> list[dict]:
        """Gather questions from every enabled source, in order, up to `amount`.

        Each question dict carries a ``source`` key (one of SOURCE_ORDER) so
        the UI can attribute every question. A failing source is skipped; the
        next enabled source fills the gap. Returns an empty list only when no
        source yields anything.
        """
        enabled = [
            source
            for source in SOURCE_ORDER
            if bool(config.get(f"source_{source}", source in DEFAULT_SOURCES))
        ]
        if not enabled:
            return []

        pool: list[dict] = []
        for source in enabled:
            if len(pool) >= amount:
                break
            need = amount - len(pool)
            try:
                if source == "opentdb":
                    raw = await self._fetch_questions(category_id, difficulty, need)
                    pool.extend(
                        {**self._parse_opentdb(item), "source": "opentdb"}
                        for item in raw
                    )
                elif source == "triviaapi":
                    raw = await self._fetch_triviaapi(category_id, difficulty, need)
                    for item in raw:
                        parsed = self._parse_triviaapi(item)
                        if parsed is not None:
                            pool.append({**parsed, "source": "triviaapi"})
                elif source == "builtin":
                    pool.extend(
                        {**item, "source": "builtin"}
                        for item in self._fallback_questions(category_id, difficulty, need)
                    )
            except Exception:
                self._logger.exception("Trivia source '%s' failed", source)

        random.shuffle(pool)
        return pool

    async def _fetch_questions(self, category_id: int, difficulty: str, amount: int) -> list[dict]:
        """Fetch multiple-choice questions from OpenTDB. Retries once on 429."""
        params = {"amount": min(amount, 50), "type": "multiple"}
        if category_id > 0:
            params["category"] = category_id
        if difficulty != "any":
            params["difficulty"] = difficulty
        try:
            async with httpx.AsyncClient(timeout=OPENTDB_TIMEOUT) as client:
                response = await client.get(OPENTDB_URL, params=params)
            if response.status_code == 429:
                await asyncio.sleep(FETCH_RETRY_AFTER_429)
                async with httpx.AsyncClient(timeout=OPENTDB_TIMEOUT) as client:
                    response = await client.get(OPENTDB_URL, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("response_code") == 0:
                return list(data.get("results", []))
        except Exception:
            self._logger.exception("OpenTDB fetch failed")
        return []

    async def _fetch_triviaapi(self, category_id: int, difficulty: str, amount: int) -> list[dict]:
        """Fetch questions from The Trivia API (no key required)."""
        params = {"limit": min(amount, 50)}
        if difficulty != "any":
            params["difficulty"] = difficulty
        category_slug = ID_TO_CATEGORY.get(category_id)
        mapped = TRIVIAAPI_CATEGORIES.get(category_slug) if category_slug else None
        if mapped:
            params["categories"] = mapped
        try:
            async with httpx.AsyncClient(timeout=OPENTDB_TIMEOUT) as client:
                response = await client.get(TRIVIAAPI_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception:
            self._logger.exception("The Trivia API fetch failed")
        return []

    @staticmethod
    def _parse_opentdb(item: dict) -> dict:
        """Normalize one OpenTDB result into the plugin's question shape."""
        question = html.unescape(str(item.get("question", "")))
        correct = html.unescape(str(item.get("correct_answer", "")))
        incorrect = [html.unescape(str(value)) for value in item.get("incorrect_answers", [])]
        options = incorrect + [correct]
        random.shuffle(options)
        category_slug = OPENTDB_NAME_TO_SLUG.get(str(item.get("category", "")), "")
        if not category_slug:
            category_slug = ID_TO_CATEGORY.get(int(item.get("category_id") or 0), "general_knowledge")
        difficulty = str(item.get("difficulty", "any")).lower()
        return {
            "question": question,
            "options": options,
            "answer": options.index(correct),
            "category": category_slug,
            "difficulty": difficulty,
        }

    @staticmethod
    def _parse_triviaapi(item: dict) -> dict | None:
        """Normalize one The Trivia API result; None when the item is unusable."""
        question = html.unescape(str((item.get("question") or {}).get("text", "") or "").strip())
        correct = html.unescape(str(item.get("correctAnswer", "") or "").strip())
        incorrect = [
            html.unescape(str(value).strip())
            for value in item.get("incorrectAnswers", [])
            if str(value).strip()
        ]
        if not question or not correct or not incorrect:
            return None
        options = incorrect + [correct]
        random.shuffle(options)
        category_slug = REVERSE_TRIVIAAPI_CATEGORIES.get(
            str(item.get("category", "")), "general_knowledge"
        )
        return {
            "question": question,
            "options": options,
            "answer": options.index(correct),
            "category": category_slug,
            "difficulty": str(item.get("difficulty", "any")).lower(),
        }

    def _fallback_questions(self, category_id: int, difficulty: str, count: int) -> list[dict]:
        """Fill remaining slots from the built-in bank."""
        category_slug = ID_TO_CATEGORY.get(category_id, "any")
        pool = [
            dict(item)
            for item in _FALLBACK_QUESTIONS
            if (category_slug == "any" or item["category"] == category_slug)
            and (difficulty == "any" or item["difficulty"] == difficulty)
        ]
        if len(pool) < count:
            pool = [dict(item) for item in _FALLBACK_QUESTIONS if category_slug in ("any", item["category"])]
        if len(pool) < count:
            pool = [dict(item) for item in _FALLBACK_QUESTIONS]
        random.shuffle(pool)
        return pool[:count]

    # ── Helpers ────────────────────────────────────────

    @staticmethod
    def _now() -> float:
        return datetime.now(timezone.utc).timestamp()

    def _standing_snippet(self, session: _TriviaSession, limit: int = 3) -> str:
        if not session.points:
            return ""
        ranked = sorted(session.points.items(), key=lambda item: item[1], reverse=True)
        lines = []
        for uid, points in ranked[:limit]:
            name = session.names.get(uid, f"<@{uid}>")
            lines.append(f"**{name}** — {points} pts")
        return "\n".join(lines)

    def _resolve_name(self, guild, user_id: str) -> str:
        try:
            member = guild.get_member(int(user_id))
            if member is not None:
                return getattr(member, "display_name", None) or str(user_id)
        except (TypeError, ValueError):
            pass
        return user_id

    async def _send_message(self, session: _TriviaSession, *, embed, view) -> discord.Message:
        guild = self.ctx.get_guild(session.guild_id)
        if guild is None:
            raise RuntimeError("trivia guild disappeared")
        channel = guild.get_channel(session.channel_id)
        if channel is None:
            raise RuntimeError("trivia channel disappeared")
        return await channel.send(embed=embed, view=view)

    async def _ephemeral(self, interaction: discord.Interaction, content: str) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
        except discord.HTTPException:
            self._logger.exception("Trivia ephemeral reply failed")


class _TriviaSession:
    """State for one active trivia game in one channel."""

    def __init__(
        self,
        *,
        guild_id: int,
        channel_id: int,
        questions: list[dict],
        starter_id: int,
        time_per_question: int,
        points_per_correct: int,
        first_bonus: int,
        rep_per_correct: int,
        rep_cap: int,
    ) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.questions = questions
        self.starter_id = starter_id
        self.time_per_question = time_per_question
        self.points_per_correct = points_per_correct
        self.first_bonus = first_bonus
        self.rep_per_correct = rep_per_correct
        self.rep_cap = rep_cap

        self.index = 0
        self.closed = False
        self.cancelled = False
        self.message: discord.Message | None = None
        self.view: discord.ui.View | None = None
        self.ends_at = 0.0
        self.first_correct: int | None = None

        self.answered: dict[int, int] = {}
        self.answered_count: dict[int, int] = {}
        self.correct_count: dict[int, int] = {}
        self.points: dict[int, int] = {}
        self.streak: dict[int, int] = {}
        self.names: dict[int, str] = {}
