"""
Shared test environment for bark-plugins tests.

Mirrors the bark-avc conftest: points BARK_* env at a temp database, resets
the engine singleton, and initializes tables. Requires a bark checkout for
imports — set BARK_ROOT (or run with the bark venv python):
    BARK_ROOT=/path/to/bark /path/to/bark/.venv/bin/pytest tests/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

BARK_ROOT = Path(os.environ.get("BARK_ROOT", "/home/cody/Projects/bark")).resolve()
if BARK_ROOT not in sys.path:
    sys.path.insert(0, str(BARK_ROOT))

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch, tmp_path):
    """Point the config singleton at a temp database and reset singletons."""
    db_path = tmp_path / "test_bark.db"
    monkeypatch.setenv("BARK_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("BARK_BOT_TOKEN", "test_token_12345")
    monkeypatch.setenv("BARK_SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("BARK_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))

    import config as cfg

    cfg.config.database.url = f"sqlite+aiosqlite:///{db_path}"
    cfg.config.data_dir = tmp_path
    cfg.config.bot.token = "test_token_12345"
    cfg.config.dashboard.secret_key = "test_secret_key"
    cfg.config.logging.level = "ERROR"

    import database.engine

    database.engine._engine = None
    database.engine._session_factory = None

    from services.response import reset_permission_state

    reset_permission_state()
    yield
    reset_permission_state()


@pytest_asyncio.fixture
async def db():
    """Initialize the database engine and all core + plugin tables."""
    from database.engine import close_db, init_db

    await init_db()
    yield
    await close_db()


def load_plugin_module():
    """Import plugins/trivia.py the same way the Bark plugin loader does."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_test_trivia", PLUGINS_DIR / "trivia.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
