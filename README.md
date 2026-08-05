# Bark Plugins

Extra, non-default plugins for the [Bark Discord bot](https://bark.warx.org).
Each plugin is a **single `.py` file** you upload through the Bark dashboard —
no restart, no editing the bot's code.

## Install a plugin (2 minutes)

1. Open your Bark dashboard → **Settings** → **Modules**.
2. In the **Plugins** box, click **Choose .py file**, pick one of the files in
   [`plugins/`](plugins/), then click **Install**.
3. The plugin appears in your Modules grid with a `plugin` badge. Enable it
   and configure it like any other module.

Removing a plugin is equally simple: **Settings → Modules → Plugins → Remove**.
It is disabled, deregistered, and its file deleted immediately.

## Available plugins

| Plugin | File | What it adds |
|---|---|---|
| Server Info | [`plugins/server_info.py`](plugins/server_info.py) | `/serverinfo` — server stats embed |
| Dice Roller | [`plugins/dice_roller.py`](plugins/dice_roller.py) | `/roll 2d6+1`, `/coinflip` |
| Fun Facts | [`plugins/fun_facts.py`](plugins/fun_facts.py) | `/fact` — random fun fact |
| Poll | [`plugins/poll.py`](plugins/poll.py) | `/poll` — reaction poll embed |
| Bark Reply | [`plugins/bark_reply.py`](plugins/bark_reply.py) | Woofs at "bark" messages — opt-in per server (event + settings demo) |
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

## Validate locally

```bash
python3 scripts/validate.py            # AST-level checks (no Bark needed)
BARK_ROOT=/path/to/bark python3 scripts/validate.py   # full import check
```

## License

MIT — see [LICENSE](LICENSE).
