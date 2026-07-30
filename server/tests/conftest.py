from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("MOCK_DATA_SEED", "42")
os.environ.setdefault("LOCAL_TIMEZONE", "America/New_York")

from app.config.loader import get_config, load_config, reset_config_cache  # noqa: E402
from app.config.settings import REPO_ROOT, get_settings, reset_settings_cache  # noqa: E402
from app.storage.repository import Repository  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_caches():
    reset_settings_cache()
    reset_config_cache()
    yield
    reset_settings_cache()
    reset_config_cache()


@pytest.fixture
def example_config():
    return load_config(REPO_ROOT / "config.example.yaml")


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    database = tmp_path / "test.sqlite3"
    return Repository(f"sqlite:///{database.as_posix()}", database)


@pytest.fixture
def sync_service(repository, example_config, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_SEED", "42")
    monkeypatch.setenv("LOCAL_TIMEZONE", "America/New_York")
    reset_settings_cache()
    from app.services.sync import SyncService

    return SyncService(repository, get_settings(), example_config)


@pytest.fixture
def new_york() -> ZoneInfo:
    return ZoneInfo("America/New_York")


@pytest.fixture
def fixed_now(new_york) -> datetime:
    """A reference "now" so tests always reconstruct 2025-06-10."""
    return datetime(2025, 6, 11, 9, 30, tzinfo=new_york)


@pytest.fixture
def config_fixture():
    return get_config
