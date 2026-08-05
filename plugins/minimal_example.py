"""
Minimal Example — the smallest valid single-file Bark plugin.

This file is the canonical starting point for writing your own plugins.
Copy it, rename the class and ``name``, and add your features.

Rules for a valid plugin:
- One file, exactly ONE ``BarkModule`` subclass.
- ``name`` is a lowercase snake_case identifier matching the filename.
- The subclass must implement ``enable()`` and ``disable()``.
- Anything the module needs comes from ``self.ctx`` (BarkContext) — modules
  never touch the bot directly.
"""

from __future__ import annotations

import discord
from modules.base import BarkModule, CommandRegistration


class MinimalExamplePlugin(BarkModule):
    # Must match the filename (minimal_example.py) and be lowercase snake_case.
    name = "minimal_example"
    version = "1.0.0"
    description = "Minimal example plugin: says hello."
    author = "Bark Plugins"

    # Slash commands the bot will register when this module is enabled.
    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="hello", description="Say hello"),
        ]

    # The module manager looks for a factory named _make_<command>_command.
    def _make_hello_command(self):
        @discord.app_commands.command(name="hello", description="Say hello")
        async def hello_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(
                f"Hello, {interaction.user.display_name}! 🐺"
            )

        return hello_cmd

    # Called when the module is enabled (at startup or on first use).
    async def enable(self) -> None:
        self._logger.info("minimal_example enabled")

    # Called when the module is disabled or the bot shuts down.
    async def disable(self) -> None:
        pass
