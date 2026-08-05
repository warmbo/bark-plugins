"""Validate every plugin in this repository.

Runs the same structural checks Bark enforces on upload:
- the file parses,
- it defines exactly one BarkModule subclass (AST-level when Bark isn't
  available, full import when BARK_ROOT points at a bark checkout),
- the module name is a safe snake_case identifier and matches the filename.

Usage:
    python3 scripts/validate.py                      # AST-level checks
    BARK_ROOT=/path/to/bark python3 scripts/validate.py  # full import checks
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

CORE_MODULES = {
    "announcements",
    "auto_voice",
    "logging",
    "moderation",
    "reputation",
    "role_manager",
    "welcome",
}


def ast_validate(path: Path) -> list[str]:
    """Structural checks without importing Bark."""
    errors: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]

    subclasses = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(base, ast.Name) and base.id == "BarkModule"
            for base in node.bases
        )
    ]
    if not subclasses:
        errors.append("no BarkModule subclass found")
    elif len(subclasses) > 1:
        errors.append(
            f"multiple BarkModule subclasses: {', '.join(c.name for c in subclasses)}"
        )

    if path.stem == "minimal_example":
        return errors  # the example is intentionally minimal

    name_attr = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            # Local variables named `name` inside functions must not override
            # the module's class attribute; only consider constant-string
            # assignments and keep the FIRST one.
            if (
                isinstance(target, ast.Name)
                and target.id == "name"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and name_attr is None
            ):
                name_attr = node.value.value
    if not isinstance(name_attr, str) or not NAME_RE.fullmatch(name_attr):
        errors.append(f"module name {name_attr!r} is not a valid snake_case identifier")
    elif name_attr != path.stem:
        errors.append(f"module name {name_attr!r} does not match filename {path.stem}.py")
    if name_attr in CORE_MODULES:
        errors.append(f"module name {name_attr!r} collides with a built-in Bark module")
    return errors


def main() -> int:
    bark_root = os.environ.get("BARK_ROOT")
    if bark_root:
        sys.path.insert(0, str(Path(bark_root).resolve()))
        try:
            from services.plugin_manager import (
                PluginValidationError,
                load_plugin_class,
                validate_plugin_name,
            )
        except ImportError as exc:
            print(f"! BARK_ROOT set but Bark could not be imported: {exc}", file=sys.stderr)
            bark_root = None

    failed = False
    for path in sorted(PLUGINS_DIR.glob("*.py")):
        errors = ast_validate(path)
        if not errors and bark_root:
            try:
                cls = load_plugin_class(path)
                validate_plugin_name(cls.name)
            except PluginValidationError as exc:
                errors.append(str(exc))
        status = "OK " if not errors else "BAD"
        print(f"[{status}] {path.name}")
        for error in errors:
            failed = True
            print(f"       - {error}")

    if failed:
        print("\nValidation FAILED")
        return 1
    print(f"\nAll {len(list(PLUGINS_DIR.glob('*.py')))} plugins valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
