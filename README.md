# Bark Plugins

Extra, non-default plugins for the [Bark Discord bot](https://bark.warx.org).
Each plugin is a **single `.py` file** you upload through the Bark dashboard —
no restart, no editing the bot's code.

Related repositories: the [bark](https://github.com/warmbo/bark) bot (its
`dev` branch is the dev instance) and the [bark-site](https://github.com/warmbo/bark-site)
landing page, which lists the core modules and points to this plugin set.

## Install a plugin (2 minutes)

1. Open your Bark dashboard and pick a server (**Modules** page — or browse
   the plugin catalog at `/guild/<id>/plugins`).
2. In the **Plugins** box, click **Choose .py file**, pick one of the files in
   [`plugins/`](plugins/), then click **Install**.
3. The plugin appears in the server's Modules grid with a `plugin` badge.
   Enable it and configure it like any other module.

Installing/removing plugins is **owner-only** (instance owner when OAuth is
enabled). Removing a plugin is equally simple: **Modules → Plugins → Remove**.
It is disabled, deregistered, and its file deleted immediately.

> The catalog page (`/guild/<id>/plugins`) shows the plugins from this repo as
> installable suggestions with one-click file downloads.

## Available plugins

| Plugin | File | What it adds |
|---|---|---|
| Trivia | [`plugins/trivia.py`](plugins/trivia.py) | Multiplayer trivia: interactive A/B/C/D button embeds, categories + difficulty, per-server leaderboard, Reputation points |
| Server Info | [`plugins/server_info.py`](plugins/server_info.py) | `/serverinfo` — server stats embed |
| Dice Roller | [`plugins/dice_roller.py`](plugins/dice_roller.py) | `/roll 2d6+1`, `/coinflip` |
| Fun Facts | [`plugins/fun_facts.py`](plugins/fun_facts.py) | `/fact` — random fun fact |
| Poll | [`plugins/poll.py`](plugins/poll.py) | `/poll` — reaction poll embed |
| Bark Reply | [`plugins/bark_reply.py`](plugins/bark_reply.py) | Woofs at "bark" messages — opt-in per server (event + settings demo) |
| Profiles | [`plugins/profiles.py`](plugins/profiles.py) | `/bark profile [user]` — rendered 1024×1792 profile card (reputation, tier progress, activity, badges, top channels) via bark's media engine (`services/media_engine`) |
| Minimal Example | [`plugins/minimal_example.py`](plugins/minimal_example.py) | `/hello` — smallest valid plugin, the starting point for your own |

## Writing your own plugins

See [`docs/plugin-format.md`](docs/plugin-format.md) for the full format:
what a plugin can register (commands, events, settings, actions, API routes,
permissions), the validation rules, and the pitfalls to avoid.

Quick checklist for a valid plugin:

- Single `.py` file with **exactly one** `BarkModule` subclass.
- `name` is lowercase `snake_case` and matches the filename.
- Implements `enable()` and `disable()`.
- Slash commands are factories named `_make_<command>_command`.
- Uses `self.ctx` (BarkContext) for everything — never the bot directly.

## Plugin ideas (not yet built)

Small, fun, single-file plugin ideas — pick one and build it! Zero-dependency
ideas work offline; anything marked **network** fetches from a public API
(with a fallback list so it still works if the API is down).

| Idea | File (planned) | What it would add | Deps |
|---|---|---|---|
| Magic 8-Ball | `plugins/eight_ball.py` | `/8ball <question>` — classic fortune answer | none |
| Ship Meter | `plugins/ship.py` | `/ship @a @b` — compatibility % + emoji meter, seeded by user IDs so the score is stable | none |
| Would You Rather | `plugins/wyr.py` | `/wyr` — bundled question deck, daily rotation | none |
| Roast & Compliment | `plugins/roast.py` | `/roast @user` and `/compliment @user` — curated word lists | none |
| Reaction Roleplay | `plugins/rp.py` | `/hug`, `/pat`, `/slap`, `/bonk` — emoji/GIF reactions between users | none |
| Mock Text | `plugins/mock.py` | `/mock <text>` — SpongeBob mock-casing | none |
| UwU-ify | `plugins/uwu.py` | `/uwu <text>` — uwu-speak translator | none |
| Emoji Translate | `plugins/emojify.py` | `/emojify <text>` — words → emoji | none |
| Slots | `plugins/slots.py` | `/slots` — emoji slot machine with rarity table | none |
| Rock Paper Scissors | `plugins/rps.py` | `/rps` — button-based game vs the bot | none |
| Hangman | `plugins/hangman.py` | `/hangman` — multiplayer hangman via buttons | none |
| Wordle | `plugins/wordle.py` | `/wordle` — one daily word per server, reaction guesses | none |
| Dad Jokes | `plugins/dadjoke.py` | `/dadjoke` — bundled joke list (or icanhazdadjoke) | none / network |
| Meme | `plugins/meme.py` | `/meme` — random meme from Reddit JSON feeds | network |
| Horoscope | `plugins/horoscope.py` | `/horoscope <sign>` — daily reading (bundled + API) | network |
| Quote Machine | `plugins/quote.py` | `/quote` — fake inspirational quote generator | none |

Guidelines for any new plugin: default **off** if it posts to a channel,
prune any tracked state, and pass `scripts/validate.py` before submitting.

## Validate locally

```bash
python3 scripts/validate.py            # AST-level checks (no Bark needed)
BARK_ROOT=/path/to/bark python3 scripts/validate.py   # full import check

# Trivia plugin has its own unit tests (need a bark checkout + venv):
BARK_ROOT=/path/to/bark /path/to/bark/.venv/bin/pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
