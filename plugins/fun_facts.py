"""
Fun Facts — a single-file Bark plugin adding a /fact command.

Upload this file through the Bark dashboard (Settings → Modules → Plugins)
to install it.
"""

from __future__ import annotations

import random

import discord
from modules.base import BarkModule, CommandRegistration

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
]


class FunFactsPlugin(BarkModule):
    name = "fun_facts"
    version = "1.1.0"
    description = "Adds a /fact command that shares a random fun fact."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="fact", description="Share a random fun fact")
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Extra facts and presentation for the /fact command.",
            "properties": {
                "custom_facts": {
                    "type": "string",
                    "title": "Custom Facts",
                    "description": "One fact per line. These are added to the "
                    "built-in list when /fact is used.",
                    "default": "",
                },
                "fact_prefix": {
                    "type": "string",
                    "title": "Fact Prefix",
                    "description": "Emoji or text shown before each fact.",
                    "default": "💡",
                },
            },
        }

    def _make_fact_command(self):
        @discord.app_commands.command(name="fact", description="Share a random fun fact")
        async def fact_cmd(interaction: discord.Interaction):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            pool = list(_FACTS)
            custom = (config.get("custom_facts") or "").strip()
            if custom:
                pool.extend(line.strip() for line in custom.splitlines() if line.strip())
            prefix = (config.get("fact_prefix") or "💡").strip() or "💡"
            await interaction.response.send_message(f"{prefix} {random.choice(pool)}")

        return fact_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
