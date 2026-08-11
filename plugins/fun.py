"""
Fun — a single-file Bark plugin: /roll, /coinflip, /fact, and /8ball.

This module unifies the old dice_roller + fun_facts plugins (plus a new
8-ball) into one self-contained add-on. Upload this file through the Bark
dashboard (Settings → Modules → Plugins) to install it.

Everything it needs comes from Bark's framework (modules.base + discord) —
no other dependencies.
"""

from __future__ import annotations

import random
import re

import discord
from modules.base import BarkModule, CommandRegistration

_DICE_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)

# Built-in fun facts (the /fact pool when no custom facts are configured).
_FACTS = [
    "Octopuses have three hearts and blue blood.",
    "Honey never spoils — archaeologists have found 3,000-year-old honey in Egyptian tombs.",
    "A group of flamingos is called a flamboyance.",
    "The Eiffel Tower grows about 15 cm taller in summer due to thermal expansion.",
    "Bananas are berries, but strawberries are not.",
    "Wombat poop is cube-shaped.",
    "The shortest war in history lasted 38 minutes (Britain vs Zanzibar, 1896).",
    "Sharks existed before trees.",
    "A day on Venus is longer than a year on Venus.",
    "Cows have best friends and get stressed when separated from them.",
    "The first computer bug was a real moth stuck in a relay in 1947.",
    "There are more possible chess games than atoms in the observable universe.",
    "Sea otters hold hands while sleeping so they don't drift apart.",
    "Lightning strikes Earth about 8 million times per day.",
    "The human brain generates about 20 watts of power while awake.",
    "A jiffy is an actual unit of time: 1/100th of a second.",
    "The dot over the letters 'i' and 'j' is called a tittle.",
    "Butterflies taste with their feet.",
    "There are more stars in the sky than grains of sand on all of Earth's beaches.",
    "Cleopatra lived closer in time to the moon landing than to the building of the Great Pyramid.",
]

# Built-in 8-ball answers (the /8ball pool when no custom answers are set).
_EIGHT_BALL = [
    "It is certain.",
    "It is decidedly so.",
    "Without a doubt.",
    "Yes — definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful.",
]


class FunPlugin(BarkModule):
    name = "fun"
    version = "1.0.0"
    description = "Random fun: dice (/roll 2d6+1), coin flips, fun facts, and a magic 8-ball."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="roll", description="Roll dice, e.g. /roll 2d6+1"
            ),
            CommandRegistration(name="coinflip", description="Flip a coin"),
            CommandRegistration(name="fact", description="Share a random fun fact"),
            CommandRegistration(
                name="eightball", description="Ask the magic 8-ball a question"
            ),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure dice limits, coin odds, custom facts, and 8-ball answers.",
            "properties": {
                "max_dice": {
                    "type": "integer",
                    "title": "Max Dice per Roll",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100,
                },
                "max_sides": {
                    "type": "integer",
                    "title": "Max Die Sides",
                    "description": "Largest die allowed, e.g. d1000.",
                    "minimum": 2,
                    "maximum": 10000,
                    "default": 1000,
                },
                "coinflip_heads": {
                    "type": "integer",
                    "title": "Coinflip Heads Odds (%)",
                    "minimum": 1,
                    "maximum": 99,
                    "default": 50,
                },
                "custom_facts": {
                    "type": "string",
                    "title": "Custom Facts",
                    "description": "One fact per line. Added to the built-in list for /fact.",
                    "default": "",
                },
                "fact_prefix": {
                    "type": "string",
                    "title": "Fact Prefix",
                    "description": "Emoji or text shown before each fact.",
                    "default": "💡",
                },
                "custom_8ball": {
                    "type": "string",
                    "title": "Custom 8-Ball Answers",
                    "description": "One answer per line. Replaces the built-in /8ball answers.",
                    "default": "",
                },
            },
        }

    # ── /roll ─────────────────────────────────────────

    def _make_roll_command(self):
        @discord.app_commands.command(name="roll", description="Roll dice, e.g. 2d6+1")
        @discord.app_commands.describe(
            dice="Dice expression like 2d6, 1d20+3, or d100"
        )
        async def roll_cmd(interaction: discord.Interaction, dice: str = "1d6"):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            max_dice = int(config.get("max_dice", 100) or 100)
            max_sides = int(config.get("max_sides", 1000) or 1000)

            match = _DICE_RE.fullmatch(dice.strip())
            if not match:
                await interaction.response.send_message(
                    f"`{dice}` is not a valid dice expression. Try `2d6`, "
                    "`1d20+3`, or `d100`.",
                    ephemeral=True,
                )
                return
            count = int(match.group(1) or 1)
            sides = int(match.group(2))
            modifier = int(match.group(3) or 0)

            if not 1 <= count <= max_dice:
                await interaction.response.send_message(
                    f"Number of dice must be between 1 and {max_dice}.",
                    ephemeral=True,
                )
                return
            if not 2 <= sides <= max_sides:
                await interaction.response.send_message(
                    f"Sides must be between 2 and {max_sides}.", ephemeral=True
                )
                return

            rolls = [random.randint(1, sides) for _ in range(count)]
            total = sum(rolls) + modifier

            parts = [f"`{dice}` → **{total}**"]
            if count > 1:
                detail = ", ".join(str(roll) for roll in rolls)
                if modifier:
                    sign = "+" if modifier >= 0 else "-"
                    detail += f" {sign} {abs(modifier)}"
                parts.append(f"({detail})")
            await interaction.response.send_message(" ".join(parts))

        return roll_cmd

    # ── /coinflip ─────────────────────────────────────

    def _make_coinflip_command(self):
        @discord.app_commands.command(name="coinflip", description="Flip a coin")
        async def coinflip_cmd(interaction: discord.Interaction):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            heads_chance = int(config.get("coinflip_heads", 50) or 50)
            result = "Heads" if random.randint(1, 100) <= heads_chance else "Tails"
            await interaction.response.send_message(f"🪙 {result}!")

        return coinflip_cmd

    # ── /fact ─────────────────────────────────────────

    def _make_fact_command(self):
        @discord.app_commands.command(name="fact", description="Share a random fun fact")
        async def fact_cmd(interaction: discord.Interaction):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            pool = list(_FACTS)
            custom = (config.get("custom_facts") or "").strip()
            if custom:
                pool.extend(
                    line.strip() for line in custom.splitlines() if line.strip()
                )
            prefix = (config.get("fact_prefix") or "💡").strip() or "💡"
            await interaction.response.send_message(f"{prefix} {random.choice(pool)}")

        return fact_cmd

    # ── /8ball ────────────────────────────────────────

    def _make_eightball_command(self):
        @discord.app_commands.command(
            name="eightball", description="Ask the magic 8-ball a question"
        )
        @discord.app_commands.describe(question="The question to ask")
        async def eight_ball_cmd(interaction: discord.Interaction, question: str):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            custom = (config.get("custom_8ball") or "").strip()
            if custom:
                pool = [a.strip() for a in custom.splitlines() if a.strip()]
            else:
                pool = list(_EIGHT_BALL)
            if not pool:
                pool = _EIGHT_BALL
            answer = random.choice(pool)
            await interaction.response.send_message(
                f"🎱 **{interaction.user.display_name}** asks: {question}\n"
                f"→ *{answer}*"
            )

        return eight_ball_cmd

    async def enable(self) -> None:
        self._logger.info("fun plugin enabled")

    async def disable(self) -> None:
        pass
