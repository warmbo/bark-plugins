"""
Birthdays — a single-file Bark plugin.

Members store their birthday with ``/birthday set``; the bot announces
birthdays in a configured channel each day. Everything is managed through
slash commands (no dashboard form), so all stored data lives in the plugin's
own config blob and can't be clobbered by the settings UI.

Upload this file through the Bark dashboard (Settings → Modules → Plugins).
Self-contained: uses only Bark's framework (modules.base + discord) and the
Python standard library.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time as dtime, timedelta

import discord
from discord import app_commands
from modules.base import BarkModule, CommandRegistration

# Default announcement hour (24h, host-local time).
_DEFAULT_HOUR = 9
_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class BirthdaysPlugin(BarkModule):
    name = "birthdays"
    version = "1.0.0"
    description = "Store birthdays and get them announced in a channel on the day."
    author = "Bark Plugins"

    # All config is managed via /birthday commands; hide the generic form so
    # the stored birthdays/channel are never overwritten by the settings UI.
    show_configure_tab = False

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._loop_task: asyncio.Task | None = None

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="birthday", description="Manage birthdays"),
        ]

    def _make_birthday_command(self):
        group = app_commands.Group(name="birthday", description="Manage birthdays")

        @group.command(name="set", description="Set your birthday")
        @app_commands.describe(
            day="Day of the month (1-31)", month="Month (1-12)"
        )
        async def set_cmd(
            interaction: discord.Interaction, day: int, month: int
        ):
            if not 1 <= month <= 12:
                await interaction.response.send_message(
                    "Month must be between 1 and 12.", ephemeral=True
                )
                return
            if not 1 <= day <= 31:
                await interaction.response.send_message(
                    "Day must be between 1 and 31.", ephemeral=True
                )
                return

            guild_id = interaction.guild_id or 0
            data = await self.load_dashboard_config(guild_id)
            birthdays = data.setdefault("birthdays", {})
            birthdays[str(interaction.user.id)] = {
                "month": month,
                "day": day,
                "name": interaction.user.display_name,
            }
            await self.save_dashboard_config(guild_id, data)

            await interaction.response.send_message(
                f"🎂 Got it! Your birthday ({_MONTHS[month - 1]} {day}) is set. "
                "I'll announce it when the day comes.",
                ephemeral=True,
            )

        @group.command(name="remove", description="Remove your birthday")
        async def remove_cmd(interaction: discord.Interaction):
            guild_id = interaction.guild_id or 0
            data = await self.load_dashboard_config(guild_id)
            birthdays = data.get("birthdays", {})
            if str(interaction.user.id) not in birthdays:
                await interaction.response.send_message(
                    "You haven't set a birthday yet.", ephemeral=True
                )
                return
            del birthdays[str(interaction.user.id)]
            await self.save_dashboard_config(guild_id, data)
            await interaction.response.send_message(
                "🗑️ Your birthday has been removed.", ephemeral=True
            )

        @group.command(name="list", description="List birthdays in this server")
        async def list_cmd(interaction: discord.Interaction):
            guild_id = interaction.guild_id or 0
            data = await self.load_dashboard_config(guild_id)
            birthdays = data.get("birthdays", {})
            if not birthdays:
                await interaction.response.send_message(
                    "No birthdays are stored yet. Set yours with `/birthday set`!",
                    ephemeral=True,
                )
                return

            lines = []
            for uid, info in sorted(
                birthdays.items(),
                key=lambda kv: (kv[1]["month"], kv[1]["day"]),
            ):
                name = info.get("name") or f"<@{uid}>"
                lines.append(
                    f"**{_MONTHS[info['month'] - 1]} {info['day']}** — {name}"
                )
            embed = discord.Embed(
                title="🎂 Birthdays",
                description="\n".join(lines),
                color=discord.Color.magenta(),
            )
            embed.set_footer(text=f"{len(lines)} birthday(s) stored")
            await interaction.response.send_message(embed=embed)

        @group.command(
            name="channel",
            description="Set the channel where birthdays are announced (admin)",
        )
        @app_commands.describe(
            channel="Text channel for announcements, or leave blank to clear"
        )
        async def channel_cmd(
            interaction: discord.Interaction, channel: discord.TextChannel | None = None
        ):
            if not self._is_admin(interaction):
                await interaction.response.send_message(
                    "Only admins can set the announcement channel.", ephemeral=True
                )
                return
            guild_id = interaction.guild_id or 0
            data = await self.load_dashboard_config(guild_id)
            if channel is None:
                data.pop("announce_channel", None)
                msg = "Birthday announcements are now off."
            else:
                data["announce_channel"] = str(channel.id)
                msg = f"Birthday announcements will go to {channel.mention}."
            await self.save_dashboard_config(guild_id, data)
            await interaction.response.send_message(msg, ephemeral=True)

        return group

    # ── Daily announce loop ───────────────────────────

    async def enable(self) -> None:
        self._loop_task = asyncio.get_running_loop().create_task(
            self._announce_loop()
        )
        self._logger.info("birthdays enabled, announce loop started")

    async def disable(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            self._loop_task = None

    async def _announce_loop(self) -> None:
        await self.ctx.bot.wait_until_ready()
        while True:
            try:
                await self._announce_today()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("birthday announce loop error")
            # Sleep until the next announce hour (host-local).
            now = datetime.now()
            target = datetime.combine(now.date(), dtime(self._hour(), 0))
            if target <= now:
                target += timedelta(days=1)
            await asyncio.sleep(max(1.0, (target - now).total_seconds()))

    def _hour(self) -> int:
        # host-local default; per-guild override is read in _announce_today.
        return _DEFAULT_HOUR

    async def _announce_today(self) -> None:
        today = date.today()
        for guild in list(self.ctx.guilds):
            if not self.ctx.bot.modules.is_enabled_for_guild(guild.id, self.name):
                continue
            data = await self.load_dashboard_config(guild.id)
            channel_id = data.get("announce_channel")
            if not channel_id:
                continue
            birthdays = data.get("birthdays", {})
            todays = [
                (uid, info)
                for uid, info in birthdays.items()
                if info.get("month") == today.month and info.get("day") == today.day
            ]
            if not todays:
                continue
            channel = self.ctx.get_guild(guild.id).get_channel(int(channel_id))
            if channel is None:
                continue
            names = []
            for uid, info in todays:
                names.append(
                    info.get("name") or f"<@{uid}>"
                )
            try:
                await channel.send(
                    "🎂 **Happy birthday** to "
                    + ", ".join(f"**{n}**" for n in names)
                    + "! 🎉🥳"
                )
                self._logger.info(
                    "Announced birthdays in guild %s: %s", guild.id, names
                )
            except Exception:
                self._logger.exception(
                    "Could not announce birthdays in guild %s", guild.id
                )

    # ── helpers ───────────────────────────────────────

    @staticmethod
    def _is_admin(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        if interaction.guild.owner_id and interaction.user.id == interaction.guild.owner_id:
            return True
        return bool(
            getattr(interaction.user, "guild_permissions", None)
            and interaction.user.guild_permissions.administrator
        )
