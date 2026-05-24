from __future__ import annotations
import warnings
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    database_url: str = f"sqlite:///{Path(__file__).parent.parent / 'bmg_capital.db'}"
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176"]
    fmp_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    jwt_secret: str = "bmg-capital-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_plus_monthly: str = ""
    stripe_price_plus_annual: str = ""
    stripe_price_premium_monthly: str = ""
    stripe_price_premium_annual: str = ""
    app_url: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **data):
        super().__init__(**data)
        if self.jwt_secret == "bmg-capital-secret-change-in-production":
            warnings.warn(
                "WARNING: Using default JWT secret. Set JWT_SECRET env var in production!",
                stacklevel=2,
            )


settings = Settings()
