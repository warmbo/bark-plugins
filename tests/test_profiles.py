"""Profiles plugin: registration, payload builders, config helpers."""

from unittest.mock import MagicMock

import pytest

from plugins.profiles import (
    ProfilesPlugin,
    resolve_channel_names,
    roles_block,
    user_block,
)


def make_plugin() -> ProfilesPlugin:
    ctx = MagicMock()
    ctx.get_module_config = MagicMock(return_value={})
    return ProfilesPlugin(ctx)


def test_command_registration():
    plugin = make_plugin()
    names = [c.name for c in plugin.get_commands()]
    assert names == ["profile"]
    assert callable(getattr(plugin, "_make_profile_command", None))


def test_settings_schema_grouped():
    plugin = make_plugin()
    schema = plugin.get_settings_schema()
    assert "appearance" in schema["properties"]
    assert "delivery" in schema["properties"]
    assert schema["properties"]["appearance"]["properties"]["theme"]["enum"] == ["bark"]
    assert schema["properties"]["delivery"]["properties"]["cache_ttl"]["default"] == 900


def test_setting_nested_and_flat():
    from plugins.profiles import _setting

    assert _setting({"delivery": {"ephemeral": True}}, "delivery", "ephemeral", False) is True
    assert _setting({"delivery__ephemeral": True}, "delivery", "ephemeral", False) is True
    assert _setting({}, "delivery", "ephemeral", False) is False


def test_user_block_fields():
    user = MagicMock()
    user.id = 123
    user.name = "cody"
    user.display_name = "Cody"
    user.bot = False
    avatar = MagicMock()
    avatar.replace.return_value.url = "https://cdn.example/cody_512.png"
    user.display_avatar = avatar

    member = MagicMock()
    member.display_name = "Cody Warmbo"
    member.joined_at = MagicMock()
    member.joined_at.isoformat.return_value = "2024-01-05T00:00:00+00:00"
    member.status = "online"

    block = user_block(member, user)
    assert block["id"] == "123"
    assert block["username"] == "cody"
    assert block["display_name"] == "Cody Warmbo"
    assert block["avatar_url"] == "https://cdn.example/cody_512.png"
    assert block["joined_at"] == "2024-01-05T00:00:00+00:00"
    assert block["presence"] == "online"
    assert block["is_bot"] is False


def test_user_block_no_member():
    user = MagicMock()
    user.id = 1
    user.name = "ghost"
    user.display_name = None
    user.bot = False
    user.display_avatar = None

    block = user_block(None, user)
    assert block["display_name"] == "ghost"
    assert block["joined_at"] is None
    assert block["avatar_url"] is None
    assert block["presence"] == "offline"


def test_roles_block_filters_everyone():
    everyone = MagicMock()
    everyone.name = "@everyone"
    mod = MagicMock()
    mod.name = "Moderator"
    mod.color.value = 0x5865F2
    mod.hoist = True

    member = MagicMock()
    member.roles = [everyone, mod]
    assert roles_block(member) == [
        {"name": "Moderator", "color": 0x5865F2, "hoist": True},
    ]


def test_roles_block_no_member():
    assert roles_block(None) == []


def test_resolve_channel_names():
    data = {
        "favorites": [
            {"channel_id": "111", "name": None, "count": 3},
            {"channel_id": "999", "name": None, "count": 1},
        ]
    }
    ch1 = MagicMock()
    ch1.id = 111
    ch1.name = "general"
    guild = MagicMock()
    guild.channels = [ch1]

    resolve_channel_names(data, guild)
    assert data["favorites"][0]["name"] == "general"
    assert data["favorites"][1]["name"] is None  # unknown channel stays None


def test_engine_client_defaults(monkeypatch):
    """Plugin uses the shared MediaEngineClient wired to env config."""
    import os
    from services.media_engine.client import MediaEngineClient

    monkeypatch.setenv("BARK_MEDIA_ENGINE_URL", "http://127.0.0.1:8095")
    monkeypatch.setenv("BARK_MEDIA_ENGINE_TOKEN", "tok")
    client = MediaEngineClient()
    assert client.base_url == "http://127.0.0.1:8095"
    assert client.token == "tok"
    assert os.environ.get("BARK_MEDIA_ENGINE_URL")  # env plumbed through
