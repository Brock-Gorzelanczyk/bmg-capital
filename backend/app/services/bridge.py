from __future__ import annotations

import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        del _cache[key]
        return None
    return value


def _set_cached(key: str, value: Any, ttl_seconds: float) -> None:
    _cache[key] = (time.monotonic() + ttl_seconds, value)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LIFI_BASE = "https://li.quest/v1"
_TIMEOUT = 20.0

CHAIN_IDS: dict[str, int] = {
    "ethereum": 1,
    "arbitrum": 42161,
    "optimism": 10,
    "base": 8453,
    "polygon": 137,
    "bsc": 56,
    "avalanche": 43114,
}

# Common token addresses by chain ID
TOKEN_ADDRESSES: dict[int, dict[str, str]] = {
    1: {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "ETH":  "0x0000000000000000000000000000000000000000",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    42161: {
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "ETH":  "0x0000000000000000000000000000000000000000",
    },
    10: {
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
        "ETH":  "0x0000000000000000000000000000000000000000",
    },
    8453: {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "ETH":  "0x0000000000000000000000000000000000000000",
    },
    137: {
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "ETH":  "0x0000000000000000000000000000000000000000",
    },
    56: {
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
        "ETH":  "0x0000000000000000000000000000000000000000",
    },
    43114: {
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
        "ETH":  "0x0000000000000000000000000000000000000000",
    },
}

# Token decimals
_TOKEN_DECIMALS: dict[str, int] = {
    "USDC": 6,
    "USDT": 6,
    "ETH":  18,
    "WBTC": 8,
    "DAI":  18,
    "WETH": 18,
}

# Fallback decimals for unknown tokens
_DEFAULT_DECIMALS = 18


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_chain_id(chain: str) -> int | None:
    """Return numeric chain ID for a chain name or numeric string."""
    chain_lower = chain.lower().strip()
    if chain_lower in CHAIN_IDS:
        return CHAIN_IDS[chain_lower]
    try:
        return int(chain)
    except (ValueError, TypeError):
        return None


def _resolve_token_address(chain_id: int, token_symbol: str) -> str | None:
    """Return the token contract address for *token_symbol* on *chain_id*."""
    symbol_upper = token_symbol.upper()
    chain_tokens = TOKEN_ADDRESSES.get(chain_id, {})
    return chain_tokens.get(symbol_upper)


def _token_from_amount(token_symbol: str, amount_usd: float) -> int:
    """Convert a USD amount to token base units (best-effort)."""
    symbol_upper = token_symbol.upper()
    decimals = _TOKEN_DECIMALS.get(symbol_upper, _DEFAULT_DECIMALS)
    # For stablecoins 1 USD ≈ 1 token; for ETH we use 1 ETH as the unit
    if symbol_upper in ("USDC", "USDT", "DAI", "FRAX", "BUSD"):
        return int(amount_usd * (10 ** decimals))
    if symbol_upper in ("ETH", "WETH"):
        # Use 1 ETH = 1e18 wei (amount_usd is effectively ignored for ETH)
        return 10 ** 18
    # Generic: assume 1:1 USD for unknown tokens
    return int(amount_usd * (10 ** decimals))


def _parse_route(route: dict) -> dict:
    """Normalise a LiFi route object into the canonical shape."""
    estimate: dict = route.get("estimate") or {}

    # Gas cost: sum of all gas cost entries
    gas_costs: list[dict] = estimate.get("gasCosts") or []
    gas_cost_usd = sum(float(g.get("amountUSD") or 0) for g in gas_costs)

    # Fee cost: sum of all fee cost entries
    fee_costs: list[dict] = estimate.get("feeCosts") or []
    fee_usd = sum(float(f.get("amountUSD") or 0) for f in fee_costs)

    # Output amount
    output_amount_usd = float(estimate.get("toAmountUSD") or route.get("toAmountUSD") or 0)

    total_cost_usd = round(gas_cost_usd + fee_usd, 4)

    # Execution duration in seconds → minutes
    duration_sec = float(estimate.get("executionDuration") or 0)
    estimated_time_min = max(1, round(duration_sec / 60))

    # Steps: derive bridge/protocol names from each step tool
    steps: list[dict] = route.get("steps") or []
    step_names: list[str] = []
    bridge_name = ""
    for step in steps:
        tool = step.get("toolDetails") or step.get("tool") or {}
        name = (tool.get("name") if isinstance(tool, dict) else tool) or ""
        if name and name not in step_names:
            step_names.append(name)
        if not bridge_name and name:
            bridge_name = name

    tags: list[str] = route.get("tags") or []

    return {
        "bridge": bridge_name or "Unknown",
        "estimated_time_min": estimated_time_min,
        "output_amount_usd": round(output_amount_usd, 4),
        "fee_usd": round(fee_usd, 4),
        "gas_cost_usd": round(gas_cost_usd, 4),
        "total_cost_usd": total_cost_usd,
        "steps": step_names,
        "score": float(route.get("score") or 0),
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_bridge_quote(
    from_chain: str,
    to_chain: str,
    token: str = "USDC",
    amount_usd: float = 1000.0,
    from_address: str = "0x0000000000000000000000000000000000000000",
) -> dict:
    """
    Get bridge routes from LiFi for transferring *token* from *from_chain*
    to *to_chain*.

    Uses the LiFi ``/v1/routes`` endpoint so that multiple bridge options are
    returned for comparison.  Not cached (user-specific amounts).

    Returns a dict with ``routes`` list, ``ok``, and ``error``.
    """
    error_result: dict = {
        "from_chain": from_chain,
        "to_chain": to_chain,
        "token": token,
        "amount_usd": amount_usd,
        "routes": [],
        "ok": False,
        "error": None,
    }

    from_chain_id = _resolve_chain_id(from_chain)
    to_chain_id = _resolve_chain_id(to_chain)

    if from_chain_id is None:
        return {**error_result, "error": f"Unknown from_chain: {from_chain}"}
    if to_chain_id is None:
        return {**error_result, "error": f"Unknown to_chain: {to_chain}"}

    from_token_addr = _resolve_token_address(from_chain_id, token)
    to_token_addr = _resolve_token_address(to_chain_id, token)

    if from_token_addr is None:
        return {
            **error_result,
            "error": f"Token {token} not found on chain {from_chain}",
        }
    if to_token_addr is None:
        # Fall back to same address on target chain (may not exist)
        to_token_addr = from_token_addr

    from_amount = _token_from_amount(token, amount_usd)

    params: dict[str, Any] = {
        "fromChainId": from_chain_id,
        "toChainId": to_chain_id,
        "fromTokenAddress": from_token_addr,
        "toTokenAddress": to_token_addr,
        "fromAmount": str(from_amount),
        "fromAddress": from_address,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_LIFI_BASE}/routes", params=params)
            resp.raise_for_status()
            data = resp.json()

        raw_routes: list[dict] = data.get("routes") or []
        parsed_routes = [_parse_route(r) for r in raw_routes]

        return {
            "from_chain": from_chain,
            "to_chain": to_chain,
            "token": token,
            "amount_usd": amount_usd,
            "routes": parsed_routes,
            "ok": True,
            "error": None,
        }

    except httpx.HTTPStatusError as exc:
        return {
            **error_result,
            "error": f"LiFi HTTP {exc.response.status_code}: {exc.response.text[:200]}",
        }
    except Exception as exc:
        return {**error_result, "error": str(exc)}


async def get_supported_chains() -> list[dict]:
    """
    Fetch supported chains from LiFi.

    Endpoint: GET https://li.quest/v1/chains
    Returns a list of chain objects.  Cached 1 hour.
    """
    cache_key = "lifi:chains"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_LIFI_BASE}/chains")
            resp.raise_for_status()
            data = resp.json()

        chains: list[dict] = data.get("chains") or (
            data if isinstance(data, list) else []
        )
        _set_cached(cache_key, chains, 3600)
        return chains

    except Exception:
        return []


async def get_supported_tokens(chain_id: int) -> list[dict]:
    """
    Fetch supported tokens for a specific chain from LiFi.

    Endpoint: GET https://li.quest/v1/tokens?chains={chain_id}
    Returns a list of token objects.  Cached 1 hour.
    """
    cache_key = f"lifi:tokens:{chain_id}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_LIFI_BASE}/tokens",
                params={"chains": chain_id},
            )
            resp.raise_for_status()
            data = resp.json()

        # LiFi returns {"tokens": {"1": [...], ...}} keyed by chain ID
        tokens_map: dict = data.get("tokens") or {}
        tokens: list[dict] = tokens_map.get(str(chain_id)) or []

        _set_cached(cache_key, tokens, 3600)
        return tokens

    except Exception:
        return []
