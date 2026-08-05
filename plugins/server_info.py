"""
Server Info — a single-file Bark plugin that adds a /serverinfo command.

Shows basic Discord server statistics in an embed. Upload this file through
the Bark dashboard (Settings → Modules → Plugins) to install it.
"""

from __future__ import annotations

import discord

from modules.base import BarkModule, CommandRegistration


class ServerInfoPlugin(BarkModule):
    name = "server_info"
    version = "1.0.0"
    description = "Adds a /serverinfo command that summarizes the server."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(
                name="serverinfo", description="Show server information"
            )
        ]

    def _make_serverinfo_command(self):
        @discord.app_commands.command(
            name="serverinfo", description="Show server information"
        )
        async def serverinfo_cmd(interaction: discord.Interaction):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message(
                    "This command only works in a server.", ephemeral=True
                )
                return

            embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.add_field(name="👥 Members", value=str(guild.member_count), inline=True)
            embed.add_field(name="📁 Channels", value=str(len(guild.channels)), inline=True)
            embed.add_field(name="🎭 Roles", value=str(len(guild.roles)), inline=True)
            if getattr(guild, "premium_subscription_count", 0):
                embed.add_field(
                    name="🚀 Boosts",
                    value=str(guild.premium_subscription_count),
                    inline=True,
                )
            embed.add_field(name="👑 Owner", value=str(guild.owner or "Unknown"), inline=True)
            if guild.created_at:
                embed.set_footer(text=f"Server created {guild.created_at:%Y-%m-%d}")

            await interaction.response.send_message(embed=embed)

        return serverinfo_cmd

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
