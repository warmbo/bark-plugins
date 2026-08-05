# Bark Plugin Format

Bark plugins are **single-file modules**. A plugin is one `.py` file that
defines exactly one `BarkModule` subclass. You upload it through the dashboard
(Settings → Modules → Plugins); Bark validates it, writes it to
`<data_dir>/plugins/<name>.py`, registers it, and enables it immediately.

## Minimum valid plugin

```python
from __future__ import annotations

import discord

from modules.base import BarkModule, CommandRegistration


class MyPlugin(BarkModule):
    name = "my_plugin"          # lowercase snake_case, matches the filename
    version = "1.0.0"
    description = "What my plugin does"
    author = "You"

    def get_commands(self):
        return [CommandRegistration(name="hello", description="Say hello")]

    def _make_hello_command(self):
        @discord.app_commands.command(name="hello", description="Say hello")
        async def hello_cmd(interaction: discord.Interaction):
            await interaction.response.send_message(f"Hi {interaction.user.display_name}!")

        return hello_cmd

    async def enable(self):
        pass

    async def disable(self):
        pass
```

## Validation rules (enforced on upload)

| Rule | Why |
|---|---|
| File must end in `.py` | Only Python single-file modules are supported |
| Max 512 KB | Upload limit |
| Exactly **one** `BarkModule` subclass | Ambiguity is rejected |
| `name` must match `^[a-z][a-z0-9_]{1,31}$` | Safe Python identifier |
| `name` must not collide with built-in modules (`reputation`, `logging`, …) | Built-ins can't be shadowed or removed |
| Must import cleanly and implement `enable()`/`disable()` | The manager calls them |

The file is validated against a **staging copy** first; if anything fails,
nothing is written and the dashboard shows the error.

## What a plugin can register

| Capability | Method | Notes |
|---|---|---|
| Slash commands | `get_commands()` + `_make_<name>_command()` | Factory returns a `discord.app_commands.Command` |
| Event handlers | `get_events()` + `async def _on_<event>(self, event_type, **data)` | Subscribed to Bark's EventBus |
| Settings | `get_settings_schema()` | Rendered in the dashboard Configure tab |
| Actions | `get_actions()` | Rendered in the Operate tab |
| API routes | `get_api_routes()` | Returns a FastAPI `APIRouter` mounted at `/api/v1` |
| Permissions | `get_permissions()` | Granular `PermissionDefinition`s |
| About text | `get_about()` | Dashboard About tab |
| Dashboard pages | `get_dashboard_pages()` | Extra nav entries |

**Not supported in v1:** custom extra-tab templates (a plugin can't ship
Jinja templates in one file — declare a tab whose template doesn't exist and
the dashboard silently drops it).

## Events

The most useful EventBus events for plugins:

| Event | Data |
|---|---|
| `discord_message` | `message` |
| `discord_message_edit` | `before`, `after` |
| `discord_message_delete` | `message` |
| `discord_member_join` / `discord_member_remove` | `member` |
| `discord_voice_state` | `member`, `before`, `after`, `before_channel`, `after_channel` |
| `raw_reaction_add` / `raw_reaction_remove` | `payload` |

Handler signature: `async def _on_message(self, event_type: str, **data)` —
read values with `data.get(...)`.

## Config & settings

```python
def get_settings_schema(self):
    return {
        "type": "object",
        "properties": {
            "auto_reply": {
                "type": "boolean",
                "title": "Reply to 'bark'",
                "description": "Off by default.",
                "default": False,
            },
            "reply_chance": {
                "type": "integer",
                "title": "Reply chance (%)",
                "default": 100,
                "minimum": 1,
                "maximum": 100,
            },
        },
    }
```

Read the current per-guild config with:

```python
config = await self.load_dashboard_config(guild_id)   # dict
config.get("auto_reply", False)
```

**Default-off for anything that posts to a channel.** Discord messages are
visible to every member of the server. A plugin that sends messages or
reactions should gate on a per-guild setting the admin explicitly enables
(see `plugins/bark_reply.py`).

## API routes

```python
from fastapi import APIRouter  # import at MODULE level — see pitfall below

def get_api_routes(self):
    router = APIRouter(tags=["plugin-my_plugin"])

    @router.get("/guilds/{guild_id}/modules/my_plugin/hello")
    async def hello(request: Request, guild_id: str):
        return {"success": True, "data": {"hello": "world"}}

    return router
```

Routes are mounted under `/api/v1` and, for plugins, wrapped in an
availability guard: once the plugin is removed, its routes answer `404`.

### Pitfall: `Request` must be imported at module level

Bark modules begin with `from __future__ import annotations`, which turns
annotations into strings. FastAPI resolves `request: Request` against the
module's top-level namespace — if `Request` is imported inside
`get_api_routes()`, FastAPI treats `request` as a query parameter and every
call returns `422 {"loc": ["query", "request"]}`. Import it at the top of the
file:

```python
from fastapi import APIRouter, Request  # top of file, not inside get_api_routes()
```

## Keep-alive etiquette

- **No unbounded in-memory state.** If your plugin tracks per-user or
  per-message state, prune it (TTL/cleanup loop). Long-running bots otherwise
  accumulate keys forever.
- **Wrap Discord sends in try/except.** Channels get deleted, permissions
  change, rate limits happen — a failed `send()` should log, not crash the
  event handler.
- **Never post without permission.** A plugin that posts to channels should
  default to OFF and require an admin to enable it per server.

## Reinstalling / updating

Uploading a new version of the same plugin (same `name`) replaces the old one:
the previous instance is unloaded, the new file is written, and the new code
is enabled. Your per-guild settings are kept (they live in the database keyed
by module name).

## Removing a plugin

**Settings → Modules → Plugins → Remove.** Bark disables the module
(unsubscribes events, removes slash commands), deregisters it everywhere,
deletes its database rows and its file, and its API routes answer 404. The
change is immediate — no restart required — and survives restarts (the file is
gone).
