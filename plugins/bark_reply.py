"""
Bark Reply — a single-file Bark plugin demonstrating events + settings.

Listens for messages containing the word "bark" and replies with a woof —
but ONLY in guilds where an admin has enabled the ``auto_reply`` setting in
the dashboard (Configure tab). The default is OFF, so installing this plugin
changes nothing until you turn it on per server.
"""

from __future__ import annotations

from modules.base import BarkModule, EventRegistration

_TRIGGER_WORDS = ("bark", "woof", "🐺")
_REPLIES = ("Woof! 🐺", "Woof woof! 🐾", "Bark! 🐺")
_MEOWS = ("Meow! 🐱", "Meow? 🐱", "Meow meow! 🐾")


class BarkReplyPlugin(BarkModule):
    name = "bark_reply"
    version = "1.1.0"
    description = "Replies with a woof when someone says 'bark' (opt-in per server)."
    author = "Bark Plugins"

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("discord_message", handler="_on_message"),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Controls whether the bot replies to 'bark' messages.",
            "properties": {
                "auto_reply": {
                    "type": "boolean",
                    "title": "Reply to 'bark'",
                    "description": "When enabled, the bot replies with a woof to "
                    "messages containing 'bark'. Off by default.",
                    "default": False,
                },
                "reply_chance": {
                    "type": "integer",
                    "title": "Reply chance (%)",
                    "description": "How often a matching message gets a reply (1-100).",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 100,
                },
                "meow_chance": {
                    "type": "integer",
                    "title": "Meow chance (%)",
                    "description": "The rare chance the reply is a 'Meow!' instead "
                    "of a woof (0-100).",
                    "default": 3,
                    "minimum": 0,
                    "maximum": 100,
                },
            },
        }

    async def _on_message(self, event_type: str, **data):
        message = data.get("message")
        if message is None or message.author.bot:
            return
        guild = getattr(message, "guild", None)
        if guild is None:
            return

        content = (getattr(message, "content", "") or "").lower()
        if not any(word in content for word in _TRIGGER_WORDS):
            return

        config = await self.load_dashboard_config(int(guild.id))
        if not config.get("auto_reply", False):
            return
        chance = int(config.get("reply_chance", 100) or 100)
        meow_chance = int(config.get("meow_chance", 3) or 0)
        import random

        if random.randint(1, 100) > chance:
            return

        if random.randint(1, 100) <= meow_chance:
            reply = random.choice(_MEOWS)
        else:
            reply = random.choice(_REPLIES)

        try:
            await message.channel.send(reply)
        except Exception:
            self._logger.exception("bark_reply could not send a reply")

    async def enable(self) -> None:
        pass

    async def disable(self) -> None:
        pass
