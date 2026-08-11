"""
Info & Tools — a single-file Bark plugin: /serverinfo, /userinfo, /roleinfo,
/channelinfo, and /ping.

Unifies and expands the old server_info plugin into one self-contained add-on.
Upload this file through the Bark dashboard (Settings → Modules → Plugins).

Everything it needs comes from Bark's framework (modules.base + discord) —
no other dependencies.
"""

from __future__ import annotations

import time

import discord
from discord.utils import format_dt
from modules.base import BarkModule, CommandRegistration


class InfoPlugin(BarkModule):
    name = "info"
    version = "1.0.0"
    description = "Server intel: /serverinfo, /userinfo, /roleinfo, /channelinfo, and /ping."
    author = "Bark Plugins"

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="serverinfo", description="Show server information"),
            CommandRegistration(name="userinfo", description="Show info about a member"),
            CommandRegistration(name="roleinfo", description="Show info about a role"),
            CommandRegistration(name="channelinfo", description="Show info about a channel"),
            CommandRegistration(name="ping", description="Show the bot's latency"),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Which sections appear in the /serverinfo embed.",
            "properties": {
                "show_channels": {
                    "type": "boolean",
                    "title": "Show Channel Count",
                    "default": True,
                },
                "show_roles": {
                    "type": "boolean",
                    "title": "Show Role Count",
                    "default": True,
                },
                "show_boosts": {
                    "type": "boolean",
                    "title": "Show Boost Count",
                    "default": True,
                },
                "show_owner": {
                    "type": "boolean",
                    "title": "Show Owner",
                    "default": True,
                },
                "show_created": {
                    "type": "boolean",
                    "title": "Show Creation Date",
                    "default": True,
                },
            },
        }

    # ── /serverinfo ───────────────────────────────────

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

            config = await self.load_dashboard_config(interaction.guild_id or 0)

            def show(key: str) -> bool:
                return bool(config.get(key, True))

            embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.add_field(name="👥 Members", value=str(guild.member_count), inline=True)
            if show("show_channels"):
                embed.add_field(
                    name="📁 Channels", value=str(len(guild.channels)), inline=True
                )
            if show("show_roles"):
                embed.add_field(
                    name="🎭 Roles", value=str(len(guild.roles)), inline=True
                )
            if show("show_boosts") and getattr(guild, "premium_subscription_count", 0):
                embed.add_field(
                    name="🚀 Boosts",
                    value=str(guild.premium_subscription_count),
                    inline=True,
                )
            if show("show_owner"):
                embed.add_field(
                    name="👑 Owner", value=str(guild.owner or "Unknown"), inline=True
                )
            if show("show_created") and guild.created_at:
                embed.set_footer(text=f"Server created {format_dt(guild.created_at, style='D')}")
            await interaction.response.send_message(embed=embed)

        return serverinfo_cmd

    # ── /userinfo ─────────────────────────────────────

    def _make_userinfo_command(self):
        @discord.app_commands.command(
            name="userinfo", description="Show info about a member"
        )
        @discord.app_commands.describe(member="Member to inspect (defaults to you)")
        async def userinfo_cmd(
            interaction: discord.Interaction, member: discord.Member | None = None
        ):
            target = member or interaction.user
            if interaction.guild is not None:
                target = interaction.guild.get_member(target.id) or target

            embed = discord.Embed(
                title=target.display_name,
                color=getattr(target, "color", None) or discord.Color.blurple(),
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="🆔 ID", value=str(target.id), inline=True)
            created = format_dt(target.created_at, style="R")
            embed.add_field(name="🐣 Account", value=created, inline=True)
            joined = format_dt(target.joined_at, style="R") if target.joined_at else "Unknown"
            embed.add_field(name="📅 Joined", value=joined, inline=True)

            if isinstance(target, discord.Member) and target.roles:
                top_roles = [r.mention for r in reversed(target.roles[1:])][:10]
                if top_roles:
                    embed.add_field(
                        name="🎭 Roles",
                        value=" ".join(top_roles) or "None",
                        inline=False,
                    )
            await interaction.response.send_message(embed=embed)

        return userinfo_cmd

    # ── /roleinfo ─────────────────────────────────────

    def _make_roleinfo_command(self):
        @discord.app_commands.command(
            name="roleinfo", description="Show info about a role"
        )
        @discord.app_commands.describe(role="Role to inspect")
        async def roleinfo_cmd(interaction: discord.Interaction, role: discord.Role):
            embed = discord.Embed(title=role.name, color=role.color)
            embed.add_field(name="🆔 ID", value=str(role.id), inline=True)
            embed.add_field(
                name="📅 Created", value=format_dt(role.created_at, style="R"), inline=True
            )
            embed.add_field(name="👥 Members", value=str(len(role.members)), inline=True)
            embed.add_field(name="🔖 Hoisted", value="Yes" if role.hoist else "No", inline=True)
            embed.add_field(
                name="🤖 Managed", value="Yes" if role.managed else "No", inline=True
            )
            embed.add_field(
                name="📌 Mentionable",
                value="Yes" if role.mentionable else "No",
                inline=True,
            )
            embed.add_field(name="🎨 Color", value=str(role.color), inline=True)
            key_perms = [
                perm.replace("_", " ").title()
                for perm, value in role.permissions
                if value
            ][:8]
            if key_perms:
                embed.add_field(
                    name="⚡ Key Permissions",
                    value=", ".join(key_perms),
                    inline=False,
                )
            await interaction.response.send_message(embed=embed)

        return roleinfo_cmd

    # ── /channelinfo ──────────────────────────────────

    def _make_channelinfo_command(self):
        @discord.app_commands.command(
            name="channelinfo", description="Show info about a channel"
        )
        @discord.app_commands.describe(
            channel="Channel to inspect (defaults to the current one)"
        )
        async def channelinfo_cmd(
            interaction: discord.Interaction,
            channel: discord.abc.GuildChannel | None = None,
        ):
            target = channel or interaction.channel
            embed = discord.Embed(
                title=f"#{target.name}", color=discord.Color.blurple()
            )
            embed.add_field(name="🆔 ID", value=str(target.id), inline=True)
            embed.add_field(name="📁 Type", value=str(target.type).title(), inline=True)
            embed.add_field(
                name="📅 Created",
                value=format_dt(target.created_at, style="R"),
                inline=True,
            )
            if getattr(target, "category", None):
                embed.add_field(
                    name="🗂 Category", value=target.category.name, inline=True
                )
            topic = getattr(target, "topic", None)
            if topic:
                embed.add_field(name="📝 Topic", value=topic[:1024], inline=False)
            if getattr(target, "slowmode_delay", 0):
                embed.add_field(
                    name="🐢 Slowmode", value=f"{target.slowmode_delay}s", inline=True
                )
            if getattr(target, "nsfw", False):
                embed.add_field(name="🔞 NSFW", value="Yes", inline=True)
            if getattr(target, "user_limit", 0):
                embed.add_field(
                    name="👤 User Limit", value=str(target.user_limit), inline=True
                )
            await interaction.response.send_message(embed=embed)

        return channelinfo_cmd

    # ── /ping ─────────────────────────────────────────

    def _make_ping_command(self):
        @discord.app_commands.command(name="ping", description="Show the bot's latency")
        async def ping_cmd(interaction: discord.Interaction):
            before = time.perf_counter()
            await interaction.response.defer()
            after = time.perf_counter()
            ws = round(float(getattr(self.ctx.bot, "latency", 0.0)) * 1000, 1)
            roundtrip = round((after - before) * 1000, 1)
            await interaction.followup.send(
                f"🏓 Pong! WebSocket: **{ws}ms** · Round-trip: **{roundtrip}ms**"
            )

        return ping_cmd

    async def enable(self) -> None:
        self._logger.info("info plugin enabled")

    async def disable(self) -> None:
        pass
