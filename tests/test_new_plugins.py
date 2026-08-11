"""
Smoke tests for the new add-on modules: fun, info, birthdays, giveaway.

Verifies each plugin loads, instantiates with a fake context, declares
commands/events/settings that are structurally valid, and that every
``_make_<command>_command`` factory builds a real discord app command/group
without raising. Run with a Bark checkout on the path:
    BARK_ROOT=/path/to/bark /path/to/bark/.venv/bin/pytest tests/
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import discord
import pytest
from modules.base import BarkModule

from conftest import PLUGINS_DIR

NEW_PLUGINS = ["fun", "info", "birthdays", "giveaway"]


def load_plugin(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"_test_{name}", PLUGINS_DIR / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeModules:
    def is_enabled_for_guild(self, guild_id, name):
        return True


class _FakeBot:
    user = SimpleNamespace(id=1)

    def __init__(self):
        self.modules = _FakeModules()
        self.latency = 0.05

    async def wait_until_ready(self):
        return None


class _FakeCtx:
    def __init__(self):
        self.bot = _FakeBot()
        self._config: dict[tuple, dict] = {}

    @property
    def guilds(self):
        return []

    def get_guild(self, guild_id):
        return None

    def get_member(self, guild_id, user_id):
        return None

    async def get_module_config(self, module_name, guild_id):
        return copy.deepcopy(self._config.get((module_name, guild_id), {}))

    async def save_module_config(self, module_name, guild_id, config):
        self._config[(module_name, guild_id)] = copy.deepcopy(config)
        return True


@pytest.mark.parametrize("name", NEW_PLUGINS)
def test_plugin_imports_and_declares(name):
    module = load_plugin(name)
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule]
    assert len(cls) == 1, f"{name} must define exactly one BarkModule subclass"
    plugin = cls[0](_FakeCtx())

    assert plugin.name == name
    assert plugin.version
    assert plugin.description

    # Every declared slash command must have a matching factory.
    for cmd in plugin.get_commands():
        assert cmd.name, "command name is required"
        factory = getattr(plugin, f"_make_{cmd.name}_command", None)
        assert factory is not None, (
            f"{name}: no _make_{cmd.name}_command factory"
        )
        built = factory()
        assert built is not None
        assert built.name == cmd.name

    # Every declared event must have a matching handler method.
    for evt in plugin.get_events():
        assert getattr(plugin, evt.handler, None) is not None, (
            f"{name}: no handler {evt.handler}"
        )

    # Settings schema, if any, must be an object with declared properties.
    schema = plugin.get_settings_schema()
    assert isinstance(schema, dict)
    if schema:
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties"), dict)


def test_fun_commands():
    module = load_plugin("fun")
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule][0]
    plugin = cls(_FakeCtx())
    names = {c.name for c in plugin.get_commands()}
    assert {"roll", "coinflip", "fact", "eightball"} <= names


def test_info_commands():
    module = load_plugin("info")
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule][0]
    plugin = cls(_FakeCtx())
    names = {c.name for c in plugin.get_commands()}
    assert {"serverinfo", "userinfo", "roleinfo", "channelinfo", "ping"} <= names


def test_birthdays_group_builds():
    module = load_plugin("birthdays")
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule][0]
    plugin = cls(_FakeCtx())
    group = plugin._make_birthday_command()
    assert isinstance(group, discord.app_commands.Group)
    assert group.name == "birthday"
    subnames = {c.name for c in group.commands}
    assert {"set", "remove", "list", "channel"} <= subnames


def test_giveaway_group_builds():
    module = load_plugin("giveaway")
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule][0]
    plugin = cls(_FakeCtx())
    group = plugin._make_giveaway_command()
    assert isinstance(group, discord.app_commands.Group)
    assert group.name == "giveaway"
    subnames = {c.name for c in group.commands}
    assert {"create", "end", "list"} <= subnames


@pytest.mark.asyncio
async def test_birthday_enable_disable_roundtrip():
    module = load_plugin("birthdays")
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule][0]
    plugin = cls(_FakeCtx())
    await plugin.enable()
    assert plugin._loop_task is not None
    await plugin.disable()
    assert plugin._loop_task is None


@pytest.mark.asyncio
async def test_giveaway_enable_disable_roundtrip():
    module = load_plugin("giveaway")
    cls = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BarkModule) and v is not BarkModule][0]
    plugin = cls(_FakeCtx())
    await plugin.enable()
    assert plugin._tasks
    await plugin.disable()
    assert not plugin._tasks
