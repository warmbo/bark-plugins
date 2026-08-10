"""
Bark Profiles — rendered profile cards via bark's media engine.

`/bark profile [user]` renders a 1024×1792 profile card (Bark dashboard
aesthetic: sharp glass panels, black/white/blue, JetBrains Mono) with the
user's live Discord facts (name, avatar, roles, joined date, presence)
merged with bark-DB data the media engine collects (reputation, tier
progress, activity bars, badges, top channels).

Pipeline: defer → engine data blocks (/v1/payload) via the shared
MediaEngineClient → merge live member facts + channel names → submit render
job → read the cached file (same host) → followup with the image. If the
engine is down or the render fails, falls back to a small embed — the
command never hard-fails.

The media engine lives in bark core (services/media_engine) and is shared
by any module; config via bark .env:
  BARK_MEDIA_ENGINE_URL    default http://127.0.0.1:8094 (dev instance: 8095)
  BARK_MEDIA_ENGINE_TOKEN  required (matches the engine's)
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from modules.base import BarkModule, CommandRegistration
from services.media_engine.client import MediaEngineClient

logger = logging.getLogger("bark.modules.profiles")


# ── config helpers ────────────────────────────────────────────────────────

def _setting(config: dict, section: str, key: str, default):
    """Grouped config (nested dict) with flat ``section__key`` fallback."""
    section_data = config.get(section)
    if isinstance(section_data, dict) and key in section_data:
        return section_data[key]
    return config.get(f"{section}__{key}", default)


# ── payload builders (pure, testable) ─────────────────────────────────────

def user_block(member, user: discord.User) -> dict:
    """Live Discord facts about the user (everything the DB cannot tell us)."""
    avatar_url = None
    display_avatar = getattr(user, "display_avatar", None)
    if display_avatar is not None:
        try:
            avatar_url = display_avatar.replace(size=512).url
        except Exception:
            avatar_url = getattr(display_avatar, "url", None)

    accent = None
    accent_color = getattr(user, "accent_color", None)
    if accent_color is not None:
        accent = int(accent_color.value) if hasattr(accent_color, "value") else int(accent_color)

    joined_at = None
    if member is not None and getattr(member, "joined_at", None) is not None:
        joined_at = member.joined_at.isoformat()

    presence = "offline"
    if member is not None:
        status = getattr(member, "status", None)
        if status is not None:
            presence = str(status)

    return {
        "id": str(user.id),
        "display_name": getattr(member, "display_name", None) or user.display_name or user.name,
        "username": user.name,
        "avatar_url": avatar_url,
        "accent_color": accent,
        "is_bot": bool(getattr(user, "bot", False)),
        "joined_at": joined_at,
        "presence": presence,
    }


def roles_block(member) -> list[dict]:
    """Hoisted/colored roles (top 5) — real Discord member roles."""
    if member is None:
        return []
    out = []
    for role in getattr(member, "roles", []) or []:
        name = getattr(role, "name", None)
        if not name or name == "@everyone":
            continue
        color = getattr(getattr(role, "color", None), "value", 0x99AAB5)
        out.append({
            "name": name,
            "color": int(color) if color is not None else 0x99AAB5,
            "hoist": bool(getattr(role, "hoist", False)),
        })
        if len(out) >= 5:
            break
    return out


def resolve_channel_names(data: dict, guild) -> None:
    """Map engine channel_ids → live channel names (mutates favorites)."""
    if guild is None:
        return
    by_id = {}
    for channel in getattr(guild, "channels", []) or []:
        try:
            by_id[str(channel.id)] = channel.name
        except Exception:
            continue
    for fav in data.get("favorites", []) or []:
        fav["name"] = by_id.get(str(fav.get("channel_id"))) or fav.get("name")


class ProfilesPlugin(BarkModule):
    name = "profiles"
    version = "2.0.0"
    description = ("Renders a graphical profile card (reputation, activity, "
                   "badges, top channels) via bark's media engine.")
    author = "Bark Plugins"

    # ── registration ─────────────────────────────────────────────────────

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="profile", description="Render a profile card"),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Appearance and delivery for /bark profile cards.",
            "properties": {
                "appearance": {
                    "type": "object",
                    "title": "Appearance",
                    "properties": {
                        "theme": {
                            "type": "string",
                            "title": "Theme",
                            "description": "Card theme (engine theme pack).",
                            "enum": ["bark"],
                            "default": "bark",
                        },
                    },
                },
                "delivery": {
                    "type": "object",
                    "title": "Delivery",
                    "properties": {
                        "ephemeral": {
                            "type": "boolean",
                            "title": "Only visible to you",
                            "description": "Hide the card from everyone else.",
                            "default": False,
                        },
                        "cache_ttl": {
                            "type": "integer",
                            "title": "Cache TTL (seconds)",
                            "description": "Reuse identical renders for this long.",
                            "default": 900,
                            "minimum": 60,
                            "maximum": 86400,
                        },
                    },
                },
            },
        }

    # ── command ──────────────────────────────────────────────────────────

    def _make_profile_command(self):
        @discord.app_commands.command(
            name="profile", description="Render a graphical profile card"
        )
        async def profile_cmd(interaction: discord.Interaction,
                              user: Optional[discord.User] = None):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message(
                    "This command only works in a server.", ephemeral=True
                )
                return

            config = await self.load_dashboard_config(interaction.guild_id or 0)
            ephemeral = bool(_setting(config, "delivery", "ephemeral", False))
            await interaction.response.defer(ephemeral=ephemeral)

            target = user or interaction.user
            member = guild.get_member(target.id)
            if member is None:
                try:
                    member = await guild.fetch_member(target.id)
                except Exception:
                    member = None

            client = MediaEngineClient()
            try:
                data = await client.collect_payload("profile", guild.id, target.id)
                data["user"] = user_block(member, target)
                data["roles"] = roles_block(member)
                resolve_channel_names(data, guild)
                theme = str(_setting(config, "appearance", "theme", "bark") or "bark")
                ttl = int(_setting(config, "delivery", "cache_ttl", 900) or 900)
                path = await client.render(
                    "profile", guild.id, target.id, payload=data,
                    theme=theme, cache_ttl=ttl,
                )
                await interaction.followup.send(
                    file=discord.File(path, filename="profile.png")
                )
            except Exception as exc:
                logger.warning("profile render failed for %s in %s: %s",
                               target.id, guild.id, exc)
                embed = discord.Embed(
                    title="Profile card unavailable",
                    description=(
                        "The media engine could not render this profile right now. "
                        "Try again in a moment."
                    ),
                    color=discord.Color.blurple(),
                )
                await interaction.followup.send(embed=embed)

        return profile_cmd

    # ── lifecycle ────────────────────────────────────────────────────────

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
