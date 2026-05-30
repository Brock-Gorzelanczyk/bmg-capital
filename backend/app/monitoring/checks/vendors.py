"""External vendor health checks (Category K)."""
from __future__ import annotations
import time
import logging
import httpx

logger = logging.getLogger(__name__)
TIMEOUT = 8.0  # seconds


async def _ping(url: str, headers: dict | None = None) -> dict:
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=headers or {})
        latency_ms = int((time.monotonic() - t0) * 1000)
        passed = resp.status_code < 500
        return {
            "passed": passed,
            "detail": f"HTTP {resp.status_code} in {latency_ms}ms" if passed
                      else f"HTTP {resp.status_code} — vendor may be down",
        }
    except Exception as exc:
        return {"passed": False, "detail": f"Request failed: {exc}"}


async def check_alpaca_up() -> dict:
    from app.config import settings
    if not settings.alpaca_api_key:
        return {"passed": True, "detail": "Alpaca key not configured — skipping"}
    return await _ping(
        "https://api.alpaca.markets/v2/clock",
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        },
    )


async def check_fmp_up() -> dict:
    from app.config import settings
    if not settings.fmp_api_key:
        return {"passed": True, "detail": "FMP key not configured — skipping"}
    return await _ping(
        f"https://financialmodelingprep.com/api/v3/is-the-market-open?apikey={settings.fmp_api_key}"
    )


async def check_anthropic_up() -> dict:
    from app.config import settings
    if not settings.anthropic_api_key:
        return {"passed": True, "detail": "Anthropic key not configured — skipping"}
    return await _ping(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        },
    )


async def check_stripe_up() -> dict:
    from app.config import settings
    if not settings.stripe_secret_key:
        return {"passed": True, "detail": "Stripe key not configured — skipping"}
    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        # Minimal call — just get balance (fast, always available)
        import asyncio
        balance = await asyncio.get_event_loop().run_in_executor(
            None, stripe.Balance.retrieve
        )
        return {"passed": True, "detail": "Stripe API OK"}
    except Exception as exc:
        return {"passed": False, "detail": f"Stripe error: {exc}"}
