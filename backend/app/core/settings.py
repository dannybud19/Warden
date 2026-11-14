"""Settings read from the environment and `.env`."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # NOTE: extra="allow" (plan says "ignore") so that `AGENT_MODE_<NAME>=real` written in `.env`
    # reaches `agent_mode()`. pydantic-settings does not export .env values to os.environ.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="allow")

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    linkup_api_key: str = ""
    companies_house_api_key: str = ""
    storage: Literal["memory", "mongo"] = "memory"
    mongodb_uri: str = ""
    mongodb_db: str = "rss"
    cors_origins: str = "http://localhost:3000"
    default_agent_mode: Literal["stub", "real"] = "stub"
    fixtures_dir: Path = Path(__file__).resolve().parents[3] / "fixtures"

    def agent_mode(self, agent_name: str) -> Literal["stub", "real"]:
        """`stub` or `real` for one agent: process env first, then `.env`, then the default."""
        key = f"AGENT_MODE_{agent_name.upper()}"
        extra = self.model_extra or {}
        value = os.environ.get(key) or extra.get(key.lower()) or self.default_agent_mode
        return "real" if value == "real" else "stub"


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, built once."""
    return Settings()
