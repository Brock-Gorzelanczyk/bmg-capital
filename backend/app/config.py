from __future__ import annotations
import os
import warnings
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

_ENV_FILE = Path(__file__).parent.parent / ".env"

_DEFAULT_CORS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
]


class Settings(BaseSettings):
    # ── Core ──────────────────────────────────────────────────────────────────
    environment: str = "development"   # development | staging | production
    app_url: str = "http://localhost:5173"
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Auth ──────────────────────────────────────────────────────────────────
    jwt_secret: str = "bmg-capital-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = f"sqlite:///{Path(__file__).parent.parent / 'bmg_capital.db'}"

    # ── CORS — comma-separated origins can be set via env var ─────────────────
    cors_origins: List[str] = _DEFAULT_CORS

    # ── Trading APIs ──────────────────────────────────────────────────────────
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    fmp_api_key: str = ""

    # ── AI ────────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ── Payments ──────────────────────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_plus_monthly: str = ""
    stripe_price_plus_annual: str = ""
    stripe_price_premium_monthly: str = ""
    stripe_price_premium_annual: str = ""

    # ── Observability ─────────────────────────────────────────────────────────
    sentry_dsn: str = ""
    log_level: str = "INFO"

    # ── Monitoring / Alerting ─────────────────────────────────────────────────
    alert_webhook_url: str = ""   # Slack/Discord webhook URL
    alert_email: str = ""          # email to send alerts to

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **data):
        super().__init__(**data)
        if self.jwt_secret == "bmg-capital-secret-change-in-production":
            if self.environment == "production":
                raise RuntimeError(
                    "FATAL: Using default JWT secret in production. "
                    "Set JWT_SECRET env var to a 32-byte hex string."
                )
            warnings.warn(
                "Using default JWT secret — set JWT_SECRET env var before going to production.",
                stacklevel=2,
            )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
