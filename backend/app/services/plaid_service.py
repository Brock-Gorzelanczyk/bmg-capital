from __future__ import annotations

"""
Plaid service wrapper.

If PLAID_CLIENT_ID is not set, all functions operate in demo/mock mode and
return realistic fixture data so the UI can be exercised without real Plaid
credentials.
"""

import random
import uuid
from typing import Optional

from fastapi import HTTPException

from app.config import settings

# ---------------------------------------------------------------------------
# Demo fixtures — three mock brokerages with pre-seeded holdings
# ---------------------------------------------------------------------------

_DEMO_BROKERAGES: dict[str, list[dict]] = {
    "Fidelity": [
        {
            "symbol": "FXAIX",
            "name": "Fidelity 500 Index Fund",
            "quantity": 100.0,
            "cost_basis": 15_800.0,
            "current_value": 17_200.0,
            "type": "mutual_fund",
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft Corporation",
            "quantity": 50.0,
            "cost_basis": 16_500.0,
            "current_value": 21_250.0,
            "type": "equity",
        },
    ],
    "Schwab": [
        {
            "symbol": "VOO",
            "name": "Vanguard S&P 500 ETF",
            "quantity": 75.0,
            "cost_basis": 22_500.0,
            "current_value": 27_300.0,
            "type": "etf",
        },
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "quantity": 30.0,
            "cost_basis": 5_100.0,
            "current_value": 6_450.0,
            "type": "equity",
        },
    ],
    "Robinhood": [
        {
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "quantity": 20.0,
            "cost_basis": 4_800.0,
            "current_value": 19_800.0,
            "type": "equity",
        },
        {
            "symbol": "TSLA",
            "name": "Tesla Inc.",
            "quantity": 15.0,
            "cost_basis": 4_200.0,
            "current_value": 3_150.0,
            "type": "equity",
        },
    ],
    # Fallback for any institution not in the list
    "_default": [
        {
            "symbol": "SPY",
            "name": "SPDR S&P 500 ETF",
            "quantity": 10.0,
            "cost_basis": 4_500.0,
            "current_value": 5_400.0,
            "type": "etf",
        },
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_configured() -> bool:
    return bool(settings.plaid_client_id)


def _require_plaid():
    if not _is_configured():
        raise HTTPException(status_code=503, detail="Plaid not configured")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_link_token(user_id: int) -> str:
    """Return a Plaid Link token (or a demo token if Plaid is not configured)."""
    if not _is_configured():
        # Return a fake token so the frontend can simulate the Link flow
        return f"link-demo-{user_id}-{uuid.uuid4().hex[:12]}"

    try:
        from plaid.api import plaid_api
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.products import Products
        from plaid.model.country_code import CountryCode
        import plaid

        configuration = plaid.Configuration(
            host=plaid.Environment.Sandbox if settings.plaid_env == "sandbox" else plaid.Environment.Production,
            api_key={
                "clientId": settings.plaid_client_id,
                "secret": settings.plaid_secret,
            },
        )
        api_client = plaid.ApiClient(configuration)
        client = plaid_api.PlaidApi(api_client)

        request = LinkTokenCreateRequest(
            products=[Products("investments")],
            client_name="BMG Capital",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
        )
        response = client.link_token_create(request)
        return response["link_token"]
    except ImportError:
        # plaid-python not installed — fall back to demo
        return f"link-demo-{user_id}-{uuid.uuid4().hex[:12]}"


def exchange_public_token(public_token: str) -> tuple[str, str, str]:
    """Exchange a public token → (access_token, item_id, institution_name)."""
    if not _is_configured() or public_token.startswith("link-demo-"):
        # Demo mode — derive institution from the fake token or return Fidelity
        institution = "Fidelity"
        for inst in _DEMO_BROKERAGES:
            if inst.lower() in public_token.lower():
                institution = inst
                break
        return (
            f"access-demo-{uuid.uuid4().hex}",
            f"item-demo-{uuid.uuid4().hex[:16]}",
            institution,
        )

    try:
        from plaid.api import plaid_api
        from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
        import plaid

        configuration = plaid.Configuration(
            host=plaid.Environment.Sandbox if settings.plaid_env == "sandbox" else plaid.Environment.Production,
            api_key={
                "clientId": settings.plaid_client_id,
                "secret": settings.plaid_secret,
            },
        )
        api_client = plaid.ApiClient(configuration)
        client = plaid_api.PlaidApi(api_client)

        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = client.item_public_token_exchange(request)

        access_token = response["access_token"]
        item_id = response["item_id"]

        # Fetch institution name
        item_response = client.item_get({"access_token": access_token})
        institution_id = item_response["item"].get("institution_id", "")
        institution_name = institution_id  # fallback; can be enriched further

        return access_token, item_id, institution_name
    except ImportError:
        return (
            f"access-demo-{uuid.uuid4().hex}",
            f"item-demo-{uuid.uuid4().hex[:16]}",
            "Unknown",
        )


def fetch_investments(access_token: str, institution_name: Optional[str] = None) -> list[dict]:
    """Fetch investment holdings for an access token.

    Returns a list of dicts: [{symbol, name, quantity, cost_basis, current_value, type}]
    """
    if not _is_configured() or access_token.startswith("access-demo-"):
        inst = institution_name or "Fidelity"
        holdings = _DEMO_BROKERAGES.get(inst, _DEMO_BROKERAGES["_default"])
        # Add a tiny random jitter so re-syncs feel alive
        return [
            {
                **h,
                "current_value": round(
                    h["current_value"] * (1 + random.uniform(-0.005, 0.005)), 2
                ),
            }
            for h in holdings
        ]

    try:
        from plaid.api import plaid_api
        from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
        import plaid

        configuration = plaid.Configuration(
            host=plaid.Environment.Sandbox if settings.plaid_env == "sandbox" else plaid.Environment.Production,
            api_key={
                "clientId": settings.plaid_client_id,
                "secret": settings.plaid_secret,
            },
        )
        api_client = plaid.ApiClient(configuration)
        client = plaid_api.PlaidApi(api_client)

        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = client.investments_holdings_get(request)

        securities_by_id = {s["security_id"]: s for s in response["securities"]}
        results = []
        for holding in response["holdings"]:
            security = securities_by_id.get(holding.get("security_id"), {})
            ticker = security.get("ticker_symbol") or security.get("name", "UNKNOWN")
            security_type = security.get("type", "equity")
            results.append(
                {
                    "symbol": ticker,
                    "name": security.get("name", ticker),
                    "quantity": float(holding.get("quantity", 0)),
                    "cost_basis": float(holding.get("cost_basis") or 0) or None,
                    "current_value": float(holding.get("institution_value", 0)) or None,
                    "type": security_type,
                }
            )
        return results
    except ImportError:
        inst = institution_name or "Fidelity"
        return _DEMO_BROKERAGES.get(inst, _DEMO_BROKERAGES["_default"])
