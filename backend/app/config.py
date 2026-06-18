from __future__ import annotations
import os
import warnings
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

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
    # FRONTEND_URL is an alias for app_url — either env var works
    frontend_url: Optional[str] = None
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

    @model_validator(mode="after")
    def add_app_url_to_cors(self) -> "Settings":
        # FRONTEND_URL env var is an alias for app_url
        effective_url = self.frontend_url or self.app_url
        if self.frontend_url:
            self.app_url = self.frontend_url
        origins = list(self.cors_origins)
        if effective_url and effective_url not in origins:
            origins.append(effective_url)
        self.cors_origins = origins
        return self

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

    # ── Plaid ─────────────────────────────────────────────────────────────────
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"

    # ── Observability ─────────────────────────────────────────────────────────
    sentry_dsn: str = ""
    log_level: str = "INFO"

    # ── Monitoring / Alerting ─────────────────────────────────────────────────
    alert_webhook_url: str = ""           # Slack/Discord webhook URL (system alerts)
    discord_signal_webhook_url: str = "" # Discord webhook for bot trade signals
    alert_email: str = ""                # email to send alerts to

    # ── Notifications ─────────────────────────────────────────────────────────
    telegram_bot_token: str = ""         # @BMGCapitalBot token from @BotFather
    resend_api_key: str = ""             # Resend for email notifications

    # ── Public Discord Bot (signal feed server) ────────────────────────────────
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    # Channel IDs — accepts both DISCORD_CH_* and legacy DISCORD_CHANNEL_* names.
    discord_ch_all_signals: str = ""
    discord_ch_stocks_signals: str = ""
    discord_ch_crypto_signals: str = ""
    discord_ch_options_signals: str = ""
    discord_ch_quant_signals: str = ""   # BMG_QUANT_SIGNALS_CHANNEL_ID
    discord_ch_daily_digest: str = ""
    discord_ch_weekly_leaderboard: str = ""
    discord_ch_monthly_recap: str = ""
    discord_ch_announcements: str = ""
    discord_ch_dev_log: str = ""
    discord_ch_price_alerts: str = ""
    discord_ch_macro_view: str = ""
    # Webhook for the #fund-updates paste-ready requests channel
    discord_wh_fund_updates: str = ""
    # Legacy aliases (kept for backward compat — prefer DISCORD_CH_* above).
    discord_channel_all_signals: str = ""
    discord_channel_stocks: str = ""
    discord_channel_crypto: str = ""
    discord_channel_options: str = ""
    discord_channel_daily_digest: str = ""
    discord_channel_weekly_leaderboard: str = ""
    discord_channel_monthly_recap: str = ""

    # ── On-Chain Data ─────────────────────────────────────────────────────────
    glassnode_api_key: str = ""
    coinglass_api_key: str = ""
    lunarcrush_api_key: str = ""

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
