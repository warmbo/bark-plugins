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
    version = "1.0.0"
    description = "Rolls dice (/roll 2d6+1) and coins (/coinflip)."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="roll", description="Roll dice, e.g. /roll 2d6+1"
            ),
            CommandRegistration(name="coinflip", description="Flip a coin"),
        ]

    def _make_roll_command(self):
        @discord.app_commands.command(name="roll", description="Roll dice, e.g. 2d6+1")
        @discord.app_commands.describe(
            dice="Dice expression like 2d6, 1d20+3, or d100"
        )
        async def roll_cmd(interaction: discord.Interaction, dice: str = "1d6"):
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

            if not 1 <= count <= _MAX_DICE:
                await interaction.response.send_message(
                    f"Number of dice must be between 1 and {_MAX_DICE}.",
                    ephemeral=True,
                )
                return
            if not 2 <= sides <= _MAX_SIDES:
                await interaction.response.send_message(
                    f"Sides must be between 2 and {_MAX_SIDES}.", ephemeral=True
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
            result = "Heads" if random.random() < 0.5 else "Tails"
            await interaction.response.send_message(f"🪙 {result}!")

        return coinflip_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
