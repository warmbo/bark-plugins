"""Schema + behavior tests for the add-on plugin configs and the Meow easter egg."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


def _load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGINS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ctx():
    from services.bark_context import BarkContext
    from services.event_bus import EventBus

    bot = SimpleNamespace()
    bot._event_bus = EventBus()
    return BarkContext(bot, bot._event_bus)


@pytest.fixture
def plugin():
    return _load_plugin("bark_reply").BarkReplyPlugin(_ctx())


# ── Settings schemas ───────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("bark_reply", {"auto_reply", "reply_chance", "meow_chance"}),
        ("dice_roller", {"max_dice", "max_sides", "coinflip_heads"}),
        ("fun_facts", {"custom_facts", "fact_prefix"}),
        ("poll", {"max_options", "show_author"}),
        ("server_info", {"show_channels", "show_roles", "show_boosts", "show_owner", "show_created"}),
    ],
)
def test_plugin_exposes_settings_schema(name, expected):
    module = _load_plugin(name)
    cls = next(
        v for v in vars(module).values() if getattr(v, "__bases__", None) and "BarkModule" in str(v.__bases__)
    )
    schema = cls(_ctx()).get_settings_schema()
    assert schema["type"] == "object"
    assert expected <= set(schema["properties"].keys())
    for prop in schema["properties"].values():
        assert "default" in prop, f"{name} property missing default: {prop}"


# ── bark_reply Meow easter egg ─────────────────────────


@pytest.mark.asyncio
async def test_bark_reply_meows_when_meow_chance_hits(plugin, monkeypatch):
    sent = []

    class FakeChannel:
        async def send(self, text):
            sent.append(text)

    class FakeMessage:
        bot = False
        author = SimpleNamespace(bot=False)
        content = "bark bark"
        channel = FakeChannel()
        guild = SimpleNamespace(id=1)

    async def fake_config(guild_id):
        return {"auto_reply": True, "reply_chance": 100, "meow_chance": 100}

    monkeypatch.setattr(plugin, "load_dashboard_config", fake_config)
    import random

    monkeypatch.setattr(random, "randint", lambda a, b: 1)  # always roll low → meow

    await plugin._on_message("discord_message", message=FakeMessage())
    assert sent and sent[0].startswith("Meow")


@pytest.mark.asyncio
async def test_bark_reply_woofs_when_meow_chance_zero(plugin, monkeypatch):
    sent = []

    class FakeChannel:
        async def send(self, text):
            sent.append(text)

    class FakeMessage:
        bot = False
        author = SimpleNamespace(bot=False)
        content = "bark bark"
        channel = FakeChannel()
        guild = SimpleNamespace(id=1)

    async def fake_config(guild_id):
        return {"auto_reply": True, "reply_chance": 100, "meow_chance": 0}

    monkeypatch.setattr(plugin, "load_dashboard_config", fake_config)
    import random

    monkeypatch.setattr(random, "randint", lambda a, b: 1)  # meow roll low, but chance is 0

    await plugin._on_message("discord_message", message=FakeMessage())
    assert sent and "Meow" not in sent[0]  # chance is 0 → never a meow


# ── Config-aware commands ──────────────────────────────


@pytest.mark.asyncio
async def test_dice_roller_respects_max_dice_and_max_sides(monkeypatch):
    module = _load_plugin("dice_roller")
    plugin = module.DiceRollerPlugin(_ctx())
    roll_cmd = plugin._make_roll_command()

    sent = []

    class FakeResponse:
        async def send_message(self, content, ephemeral=False):
            sent.append(content)

    class FakeInteraction:
        guild_id = 1
        response = FakeResponse()

    async def fake_config(guild_id):
        return {"max_dice": 2, "max_sides": 20, "coinflip_heads": 50}

    monkeypatch.setattr(plugin, "load_dashboard_config", fake_config)
    roll_cb = roll_cmd.callback  # @app_commands.command returns a Command wrapper

    await roll_cb(FakeInteraction(), dice="5d6")
    assert "between 1 and 2" in sent[-1]

    await roll_cb(FakeInteraction(), dice="d100")
    assert "between 2 and 20" in sent[-1]


@pytest.mark.asyncio
async def test_fun_facts_uses_custom_facts_and_prefix(monkeypatch):
    module = _load_plugin("fun_facts")
    plugin = module.FunFactsPlugin(_ctx())
    fact_cmd = plugin._make_fact_command()

    sent = []

    class FakeResponse:
        async def send_message(self, content, ephemeral=False):
            sent.append(content)

    class FakeInteraction:
        guild_id = 1
        response = FakeResponse()

    async def fake_config(guild_id):
        return {"custom_facts": "Bark is a dog.\nRuff.", "fact_prefix": "🐶"}

    monkeypatch.setattr(plugin, "load_dashboard_config", fake_config)
    fact_cb = fact_cmd.callback

    import random

    monkeypatch.setattr(random, "choice", lambda pool: "Bark is a dog.")  # from custom facts

    await fact_cb(FakeInteraction())
    assert sent
    assert sent[0] == "🐶 Bark is a dog."


@pytest.mark.asyncio
async def test_server_info_hides_disabled_sections(monkeypatch):
    module = _load_plugin("server_info")
    plugin = module.ServerInfoPlugin(_ctx())
    cmd = plugin._make_serverinfo_command()

    embed_holder = {}

    class FakeEmbed:
        def __init__(self, title=None, color=None):
            self.fields = []
            self.icon = None

        def set_thumbnail(self, url=None):
            pass

        def add_field(self, name="", value="", inline=False):
            self.fields.append((name, value))

        def set_footer(self, text=""):
            self.footer = text

    class FakeGuild:
        name = "Test"
        icon = None
        member_count = 5
        channels = (1, 2)
        roles = (1,)
        premium_subscription_count = 0
        owner = "Owner"
        created_at = None

    class FakeResponse:
        async def send_message(self, embed=None, ephemeral=False):
            embed_holder["embed"] = embed

    class FakeInteraction:
        guild_id = 1
        guild = FakeGuild()
        response = FakeResponse()

    async def fake_config(guild_id):
        return {"show_channels": False, "show_roles": True, "show_owner": False}

    monkeypatch.setattr(plugin, "load_dashboard_config", fake_config)
    monkeypatch.setattr(
        module,
        "discord",
        SimpleNamespace(
            Embed=FakeEmbed,
            Color=SimpleNamespace(blurple=lambda: None),
        ),
    )

    await cmd.callback(FakeInteraction())
    names = [f[0] for f in embed_holder["embed"].fields]
    assert "📁 Channels" not in names
    assert "👑 Owner" not in names
    assert "🎭 Roles" in names
