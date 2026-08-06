"""
Poll — a single-file Bark plugin adding a /poll command.

Creates a Discord embed poll with reaction options. Upload this file through
the Bark dashboard (Settings → Modules → Plugins) to install it.
"""

from __future__ import annotations

import discord
from modules.base import BarkModule, CommandRegistration

_NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class PollPlugin(BarkModule):
    name = "poll"
    version = "1.1.0"
    description = "Creates a quick reaction poll with /poll."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="poll", description="Create a reaction poll")
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Poll limits and display options.",
            "properties": {
                "max_options": {
                    "type": "integer",
                    "title": "Max Options",
                    "description": "Maximum number of poll options (2-10).",
                    "minimum": 2,
                    "maximum": 10,
                    "default": 4,
                },
                "show_author": {
                    "type": "boolean",
                    "title": "Show Author on Polls",
                    "description": "Footer shows who created the poll.",
                    "default": True,
                },
            },
        }

    def _make_poll_command(self):
        @discord.app_commands.command(name="poll", description="Create a reaction poll")
        @discord.app_commands.describe(
            question="The poll question",
            option1="First option",
            option2="Second option",
            option3="Third option (optional)",
            option4="Fourth option (optional)",
        )
        async def poll_cmd(
            interaction: discord.Interaction,
            question: str,
            option1: str,
            option2: str,
            option3: str | None = None,
            option4: str | None = None,
        ):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message(
                    "This command only works in a server.", ephemeral=True
                )
                return

            config = await self.load_dashboard_config(interaction.guild_id or 0)
            max_options = int(config.get("max_options", 4) or 4)
            show_author = bool(config.get("show_author", True))

            options = [option1, option2]
            for extra in (option3, option4):
                if extra:
                    options.append(extra)
            options = options[: min(max_options, len(_NUMBER_EMOJIS))]
            if len(options) < 2:
                await interaction.response.send_message(
                    "A poll needs at least two options.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"📊 {question[:256]}",
                color=discord.Color.blurple(),
                description="\n".join(
                    f"{_NUMBER_EMOJIS[index]} {option}"
                    for index, option in enumerate(options)
                ),
            )
            if show_author:
                embed.set_footer(
                    text=f"Poll by {interaction.user.display_name} — react to vote"
                )
            else:
                embed.set_footer(text="React to vote")
            await interaction.response.send_message(embed=embed)
            message = await interaction.original_response()
            for index in range(len(options)):
                await message.add_reaction(_NUMBER_EMOJIS[index])

        return poll_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
