from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class SentinelSettings(BaseSettings):
    # Core
    sentinel_enabled: bool = Field(False, alias="SENTINEL_ENABLED")
    environment: str = Field("production", alias="ENVIRONMENT")

    # DB
    database_url: str = Field("", alias="DATABASE_URL")

    # Railway
    railway_api_token: str = Field("", alias="RAILWAY_API_TOKEN")
    railway_project_id: str = Field("", alias="RAILWAY_PROJECT_ID")
    railway_service_id: str = Field("", alias="RAILWAY_SERVICE_ID")

    # GitHub
    github_token: str = Field("", alias="GITHUB_TOKEN")
    github_repo: str = Field("Brock-Gorzelanczyk/bmg-capital", alias="GITHUB_REPO")

    # Discord
    discord_bot_token: str = Field("", alias="DISCORD_BOT_TOKEN")
    discord_sentinel_channel_id: str = Field("", alias="DISCORD_CHANNEL_ID_SENTINEL_OPS")

    # Anthropic
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")

    # Limits
    daily_cost_cap_usd: float = Field(5.0, alias="SENTINEL_DAILY_COST_CAP_USD")
    max_daily_prs: int = Field(5, alias="SENTINEL_MAX_DAILY_PRS")

    # App URL to scan
    app_url: str = Field("https://bmg-capital.up.railway.app", alias="APP_URL")

    model_config = {"env_file": ".env", "extra": "ignore", "populate_by_name": True}

    def load_safe_fixes(self) -> dict:
        cfg_path = Path(__file__).parent / "config" / "safe_fixes.yaml"
        with open(cfg_path) as f:
            return yaml.safe_load(f)

    def load_signal_intervals(self) -> dict:
        cfg_path = Path(__file__).parent / "config" / "expected_signal_intervals.yaml"
        with open(cfg_path) as f:
            return yaml.safe_load(f)


settings = SentinelSettings()
