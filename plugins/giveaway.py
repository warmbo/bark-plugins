"""
Giveaway — a single-file Bark plugin.

Admins create a giveaway with ``/giveaway create``; the bot posts an embed
and members react to enter. After the duration the bot draws a winner (or
winners) automatically and announces it. All state lives in the plugin's own
config blob + in-memory (no dashboard form), so it can't be clobbered.

Upload this file through the Bark dashboard (Settings → Modules → Plugins).
Self-contained: uses only Bark's framework (modules.base + discord) and the
Python standard library.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
)

_ENTRY_EMOJI = "🎉"


class GiveawayPlugin(BarkModule):
    name = "giveaway"
    version = "1.0.0"
    description = "React-to-enter giveaways with automatic winner drawing."
    author = "Bark Plugins"

    show_configure_tab = False

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._tasks: set[asyncio.Task] = set()
        # message_id -> {"prize", "channel_id", "ends_at", "winners", "entrants": [uid]}
        self._active: dict[int, dict] = {}

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="giveaway", description="Run a giveaway"),
        ]

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("raw_reaction_add", handler="_on_reaction_add"),
        ]

    def _make_giveaway_command(self):
        group = app_commands.Group(name="giveaway", description="Run a giveaway")

        @group.command(name="create", description="Create a giveaway (admin)")
        @app_commands.describe(
            prize="The prize to give away",
            duration="How long it runs, in minutes (default 60)",
            winners="Number of winners (default 1)",
        )
        async def create_cmd(
            interaction: discord.Interaction,
            prize: str,
            duration: int = 60,
            winners: int = 1,
        ):
            if not self._is_admin(interaction):
                await interaction.response.send_message(
                    "Only admins can create giveaways.", ephemeral=True
                )
                return
            if not prize.strip():
                await interaction.response.send_message(
                    "Please include a prize.", ephemeral=True
                )
                return
            if duration < 1:
                await interaction.response.send_message(
                    "Duration must be at least 1 minute.", ephemeral=True
                )
                return
            if not 1 <= winners <= 10:
                await interaction.response.send_message(
                    "Winners must be between 1 and 10.", ephemeral=True
                )
                return

            ends_at = datetime.now(timezone.utc) + timedelta(minutes=duration)
            embed = self._make_embed(prize, ends_at, winners)
            await interaction.response.send_message(embed=embed)
            message = await interaction.original_response()
            try:
                await message.add_reaction(_ENTRY_EMOJI)
            except Exception:
                self._logger.exception("could not add giveaway reaction")

            guild_id = interaction.guild_id or 0
            self._active[message.id] = {
                "prize": prize.strip(),
                "channel_id": str(interaction.channel_id),
                "ends_at": ends_at.isoformat(),
                "winners": winners,
                "entrants": [],
            }
            await self._persist(guild_id)
            self._logger.info("giveaway created in guild %s: %s", guild_id, prize)

        @group.command(name="end", description="End a giveaway early and draw (admin)")
        @app_commands.describe(
            message_id="The ID of the giveaway message to end"
        )
        async def end_cmd(interaction: discord.Interaction, message_id: str):
            if not self._is_admin(interaction):
                await interaction.response.send_message(
                    "Only admins can end giveaways.", ephemeral=True
                )
                return
            try:
                mid = int(message_id)
            except ValueError:
                await interaction.response.send_message(
                    "That doesn't look like a valid message ID.", ephemeral=True
                )
                return
            if mid not in self._active:
                await interaction.response.send_message(
                    "That's not an active giveaway.", ephemeral=True
                )
                return
            await self._draw(interaction.guild_id or 0, mid)
            await interaction.response.send_message("Giveaway drawn!", ephemeral=True)

        @group.command(name="list", description="Show active giveaways")
        async def list_cmd(interaction: discord.Interaction):
            guild_id = interaction.guild_id or 0
            active = [
                (mid, g)
                for mid, g in self._active.items()
                if g.get("guild_id") == str(guild_id)
            ]
            if not active:
                await interaction.response.send_message(
                    "No active giveaways.", ephemeral=True
                )
                return
            lines = []
            for mid, g in active:
                entrants = len([u for u in g.get("entrants", []) if u != str(self.ctx.bot.user.id)])
                lines.append(f"**{g['prize']}** — {entrants} entrant(s) — ends <t:{int(datetime.fromisoformat(g['ends_at']).timestamp())}:R>")
            embed = discord.Embed(
                title="🎉 Active Giveaways", description="\n".join(lines), color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed)

        return group

    # ── Reaction entry ────────────────────────────────

    async def _on_reaction_add(self, event_type: str, **data):
        payload = data.get("payload")
        if payload is None or payload.message_id not in self._active:
            return
        if payload.emoji.name != _ENTRY_EMOJI:
            return
        if payload.user_id == self.ctx.bot.user.id:
            return
        if payload.guild_id is None:
            return
        entry = self._active[payload.message_id]
        uid = str(payload.user_id)
        if uid not in entry["entrants"]:
            entry["entrants"].append(uid)
            await self._persist(payload.guild_id)

    # ── Auto-draw loop ────────────────────────────────

    async def enable(self) -> None:
        await self._seed_from_config()
        task = asyncio.get_running_loop().create_task(self._draw_loop())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self._logger.info("giveaway enabled, draw loop started")

    async def disable(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    async def _seed_from_config(self) -> None:
        # Rebuild in-memory active giveaways from the persisted config.
        for guild in list(self.ctx.guilds):
            data = await self.load_dashboard_config(guild.id)
            active = data.get("active") or {}
            for mid, info in active.items():
                try:
                    self._active[int(mid)] = info
                    self._active[int(mid)]["guild_id"] = str(guild.id)
                except (KeyError, ValueError):
                    continue

    async def _draw_loop(self) -> None:
        await self.ctx.bot.wait_until_ready()
        while True:
            try:
                await self._check_draws()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("giveaway draw loop error")
            await asyncio.sleep(30)

    async def _check_draws(self) -> None:
        now = datetime.now(timezone.utc)
        expired = []
        for mid, info in self._active.items():
            try:
                if datetime.fromisoformat(info["ends_at"]) <= now:
                    expired.append(mid)
            except (KeyError, ValueError):
                continue
        for mid in expired:
            guild_id = int(self._active[mid].get("guild_id", "0"))
            await self._draw(guild_id, mid)

    async def _draw(self, guild_id: int, message_id: int) -> None:
        info = self._active.pop(message_id, None)
        if info is None:
            return
        guild = self.ctx.get_guild(guild_id)
        channel = guild.get_channel(int(info["channel_id"])) if guild else None
        entrants = [
            u for u in info.get("entrants", []) if u != str(self.ctx.bot.user.id)
        ]
        prize = info.get("prize", "a prize")
        winners = random.sample(
            entrants, min(info.get("winners", 1), len(entrants))
        ) if entrants else []
        await self._persist(guild_id)

        try:
            if channel is not None and winners:
                await channel.send(
                    f"🎉 **Giveaway: {prize}**\nCongratulations "
                    + ", ".join(f"<@{w}>" for w in winners)
                    + "! 🥳"
                )
            elif channel is not None:
                await channel.send(
                    f"🎉 **Giveaway: {prize}** ended with no entrants. "
                    "Better luck next time!"
                )
        except Exception:
            self._logger.exception("could not announce giveaway winner")
        self._logger.info("giveaway drawn in guild %s: %s -> %s", guild_id, prize, winners)

    # ── persistence ───────────────────────────────────

    async def _persist(self, guild_id: int) -> None:
        by_guild: dict[str, dict] = {}
        for mid, info in self._active.items():
            gid = info.get("guild_id") or str(guild_id)
            by_guild.setdefault(gid, {})[str(mid)] = info
        # Persist for the touched guild (and any guild with active giveaways).
        touched = {str(guild_id), *(info.get("guild_id") for info in self._active.values())}
        for gid in touched:
            if not gid:
                continue
            data = await self.load_dashboard_config(int(gid))
            data["active"] = by_guild.get(gid, {})
            await self.save_dashboard_config(int(gid), data)

    # ── helpers ───────────────────────────────────────

    @staticmethod
    def _make_embed(prize: str, ends_at: datetime, winners: int) -> discord.Embed:
        embed = discord.Embed(
            title="🎉 Giveaway",
            description=f"**{prize}**\n\nReact with {_ENTRY_EMOJI} to enter!",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Winner(s)", value=str(winners), inline=True)
        embed.add_field(
            name="Ends",
            value=f"<t:{int(ends_at.timestamp())}:R>",
            inline=True,
        )
        return embed

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
