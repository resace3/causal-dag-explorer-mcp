"""Environment-driven runtime settings.

Secrets (Home Assistant token) are read from the environment only and are never
written to the SQLite cache, the API responses, or the logs.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(REPO_ROOT / ".env", override=False)


class Settings(BaseSettings):
    """Runtime configuration read from environment variables / `.env`."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # --- Home Assistant -------------------------------------------------
    home_assistant_url: str | None = Field(default=None, alias="HOME_ASSISTANT_URL")
    home_assistant_token: str | None = Field(default=None, alias="HOME_ASSISTANT_TOKEN")
    home_assistant_timeout_seconds: float = Field(
        default=15.0, alias="HOME_ASSISTANT_TIMEOUT_SECONDS"
    )
    home_assistant_verify_ssl: bool = Field(default=True, alias="HOME_ASSISTANT_VERIFY_SSL")

    # --- ActivityWatch --------------------------------------------------
    # No credential exists: the server listens on loopback only and is not
    # authenticated, which is also why it is never addressed off-machine.
    activitywatch_url: str = Field(default="http://localhost:5600", alias="ACTIVITYWATCH_URL")
    activitywatch_timeout_seconds: float = Field(
        default=20.0, alias="ACTIVITYWATCH_TIMEOUT_SECONDS"
    )

    # --- Phone usage add-on ---------------------------------------------
    # The add-on serves its query API on two ports. 8099 takes a bearer token
    # and is what this uses; 8098 goes through Home Assistant Ingress, which
    # authenticates with a session cookie minted from an admin credential — a
    # long-lived token cannot mint one, Supervisor endpoints refuse it.
    phone_usage_url: str | None = Field(default=None, alias="PHONE_USAGE_URL")
    phone_usage_token: str | None = Field(default=None, alias="PHONE_USAGE_TOKEN")
    phone_usage_timeout_seconds: float = Field(
        default=20.0, alias="PHONE_USAGE_TIMEOUT_SECONDS"
    )

    # --- Locale ---------------------------------------------------------
    local_timezone: str = Field(default="America/New_York", alias="LOCAL_TIMEZONE")

    # --- Data mode ------------------------------------------------------
    use_mock_data: bool = Field(default=True, alias="USE_MOCK_DATA")
    mock_data_seed: int = Field(default=42, alias="MOCK_DATA_SEED")
    wearable_provider: str | None = Field(default=None, alias="WEARABLE_PROVIDER")

    # --- Local servers --------------------------------------------------
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    frontend_port: int = Field(default=3000, alias="FRONTEND_PORT")

    # --- Storage --------------------------------------------------------
    data_dir: Path = Field(default=REPO_ROOT / "data", alias="DATA_DIR")
    config_path: Path | None = Field(default=None, alias="CONFIG_PATH")

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand_data_dir(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(os.path.expandvars(value)).expanduser()
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "yesterday.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def api_base_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"

    @property
    def frontend_dev_url(self) -> str:
        return f"http://{self.api_host}:{self.frontend_port}"

    @property
    def allowed_origins(self) -> list[str]:
        """CORS allow-list: only the local frontend dev server."""
        hosts = {self.api_host, "127.0.0.1", "localhost"}
        return [f"http://{host}:{self.frontend_port}" for host in sorted(hosts)]

    def resolved_config_path(self) -> Path:
        """`config.yaml` when the user created one, otherwise the shipped example."""
        if self.config_path is not None:
            return Path(self.config_path)
        candidate = REPO_ROOT / "config.yaml"
        if candidate.exists():
            return candidate
        return REPO_ROOT / "config.example.yaml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that patch the environment."""
    get_settings.cache_clear()
