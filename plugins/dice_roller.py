"""
Dice Roller — a single-file Bark plugin adding /roll and /coinflip commands.

Upload this file through the Bark dashboard (Settings → Modules → Plugins)
to install it.
"""

from __future__ import annotations

import random
import re

import discord
from modules.base import BarkModule, CommandRegistration

_DICE_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)
_MAX_DICE = 100
_MAX_SIDES = 1000


class DiceRollerPlugin(BarkModule):
    name = "dice_roller"
    version = "1.1.0"
    description = "Rolls dice (/roll 2d6+1) and coins (/coinflip)."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="roll", description="Roll dice, e.g. /roll 2d6+1"
            ),
            CommandRegistration(name="coinflip", description="Flip a coin"),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Limits for dice rolls and coin flip odds.",
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
                    "description": "Chance of Heads when someone flips a coin.",
                    "minimum": 1,
                    "maximum": 99,
                    "default": 50,
                },
            },
        }

    def _make_roll_command(self):
        @discord.app_commands.command(name="roll", description="Roll dice, e.g. 2d6+1")
        @discord.app_commands.describe(
            dice="Dice expression like 2d6, 1d20+3, or d100"
        )
        async def roll_cmd(interaction: discord.Interaction, dice: str = "1d6"):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            max_dice = int(config.get("max_dice", _MAX_DICE) or _MAX_DICE)
            max_sides = int(config.get("max_sides", _MAX_SIDES) or _MAX_SIDES)

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

    def _make_coinflip_command(self):
        @discord.app_commands.command(name="coinflip", description="Flip a coin")
        async def coinflip_cmd(interaction: discord.Interaction):
            config = await self.load_dashboard_config(interaction.guild_id or 0)
            heads_chance = int(config.get("coinflip_heads", 50) or 50)
            result = "Heads" if random.randint(1, 100) <= heads_chance else "Tails"
            await interaction.response.send_message(f"🪙 {result}!")

        return coinflip_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
