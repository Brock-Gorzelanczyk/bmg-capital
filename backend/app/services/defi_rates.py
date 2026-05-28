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

_LLAMA_POOLS_URL = "https://yields.llama.fi/pools"
_TIMEOUT = 20.0

_PROTOCOL_NAMES: dict[str, str] = {
    "lido": "Lido",
    "rocket-pool": "Rocket Pool",
    "marinade-finance": "Marinade",
    "jito": "Jito",
    "aave-v3": "Aave V3",
    "compound-v3": "Compound V3",
    "morpho-aave-v3": "Morpho",
    "spark": "Spark",
    "binance-staked-eth": "Binance Staked ETH",
    "frax-ether": "Frax",
}

_STAKING_PROJECTS = frozenset([
    "lido",
    "rocket-pool",
    "marinade-finance",
    "jito",
    "binance-staked-eth",
    "frax-ether",
])

_STAKING_SYMBOLS = frozenset(["ETH", "WETH", "SOL", "stETH", "rETH", "mSOL", "jitoSOL"])

_LENDING_PROJECTS = frozenset(["aave-v3", "compound-v3", "morpho-aave-v3", "spark"])

_LENDING_CHAINS = frozenset(["Ethereum", "Arbitrum", "Optimism", "Base", "Polygon"])

_YIELD_CHAINS = frozenset([
    "Ethereum", "Arbitrum", "Optimism", "Base", "Polygon", "Solana",
])

# Rough logo URLs via DeFi Llama CDN (best-effort)
_PROTOCOL_LOGOS: dict[str, str] = {
    "lido": "https://icons.llama.fi/lido.png",
    "rocket-pool": "https://icons.llama.fi/rocket-pool.png",
    "marinade-finance": "https://icons.llama.fi/marinade-finance.png",
    "jito": "https://icons.llama.fi/jito.png",
    "binance-staked-eth": "https://icons.llama.fi/binance-staked-eth.png",
    "frax-ether": "https://icons.llama.fi/frax-ether.png",
}

_PROTOCOL_URLS: dict[str, str] = {
    "lido": "https://lido.fi",
    "rocket-pool": "https://rocketpool.net",
    "marinade-finance": "https://marinade.finance",
    "jito": "https://jito.network",
    "binance-staked-eth": "https://www.binance.com/en/eth2",
    "frax-ether": "https://frax.finance",
    "aave-v3": "https://app.aave.com",
    "compound-v3": "https://app.compound.finance",
    "morpho-aave-v3": "https://app.morpho.org",
    "spark": "https://spark.fi",
}


def _display_name(project_key: str) -> str:
    return _PROTOCOL_NAMES.get(project_key, project_key.replace("-", " ").title())


def _primary_asset(symbol: str) -> str:
    """Return the canonical asset name from a pool symbol like 'USDC-WETH'."""
    first = symbol.split("-")[0].split("/")[0].upper()
    # Normalise wrapped tokens
    return first.lstrip("W") if first in ("WETH", "WBTC", "WBNB") else first


def _category_for_project(project: str, symbol: str) -> str:
    if project in _STAKING_PROJECTS:
        return "Staking"
    if project in _LENDING_PROJECTS:
        return "Lending"
    if any(kw in project for kw in ("lp", "amm", "swap", "curve", "uniswap", "sushiswap")):
        return "DEX LP"
    if any(kw in project for kw in ("yearn", "beefy", "convex", "harvest")):
        return "Yield Aggregator"
    if "-" in symbol or "/" in symbol:
        return "DEX LP"
    return "Lending"


def _il_risk(project: str, symbol: str) -> str:
    if project in _STAKING_PROJECTS:
        return "None"
    if "-" in symbol or "/" in symbol:
        tokens = [t.strip() for t in symbol.replace("/", "-").split("-")]
        stable_keywords = {"USDC", "USDT", "DAI", "FRAX", "LUSD", "BUSD", "MIM", "USDD"}
        if all(t in stable_keywords for t in tokens):
            return "Low"
        return "High"
    return "None"


# ---------------------------------------------------------------------------
# Shared pool fetch
# ---------------------------------------------------------------------------

async def _fetch_all_pools() -> list[dict]:
    """Fetch all pools from DeFi Llama (cached 30 min under a shared key)."""
    cache_key = "llama:all_pools"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_LLAMA_POOLS_URL)
            resp.raise_for_status()
            pools: list[dict] = resp.json().get("data") or []
        _set_cached(cache_key, pools, 1800)  # 30 minutes
        return pools
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_staking_rates() -> list[dict]:
    """
    Fetch ETH and SOL staking yields from DeFi Llama yields API.

    Filters for known staking protocols (Lido, Rocket Pool, Marinade, Jito,
    Binance Staked ETH, Frax Ether) and canonical staking symbols.
    Returns a list sorted by APY descending.  Cached 30 minutes.
    """
    cache_key = "staking_rates"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    pools = await _fetch_all_pools()
    results: list[dict] = []

    for pool in pools:
        project = pool.get("project", "")
        symbol = pool.get("symbol", "")
        if project not in _STAKING_PROJECTS:
            continue
        if symbol not in _STAKING_SYMBOLS:
            continue

        asset = "SOL" if symbol in ("mSOL", "jitoSOL") else "ETH"
        results.append(
            {
                "protocol": _display_name(project),
                "asset": asset,
                "apy": round(float(pool.get("apy") or 0), 4),
                "apy_base": round(float(pool.get("apyBase") or 0), 4),
                "tvl_usd": float(pool.get("tvlUsd") or 0),
                "chain": pool.get("chain", ""),
                "staked_token": symbol,
                "url": _PROTOCOL_URLS.get(project, ""),
                "logo": _PROTOCOL_LOGOS.get(project, ""),
            }
        )

    results.sort(key=lambda r: r["apy"], reverse=True)
    _set_cached(cache_key, results, 1800)
    return results


async def get_lending_rates(
    assets: list[str] | None = None,
) -> list[dict]:
    """
    Fetch lending supply rates from DeFi Llama for major lending protocols.

    Filters for Aave V3, Compound V3, Morpho, and Spark on Ethereum,
    Arbitrum, Optimism, Base, and Polygon.  *assets* is a list of symbols to
    include (case-insensitive).  Returns rows sorted by asset then by
    apy_supply descending.  Cached 30 minutes.
    """
    if assets is None:
        assets = ["USDC", "USDT", "ETH", "WBTC", "DAI"]

    cache_key = f"lending_rates:{'|'.join(sorted(a.upper() for a in assets))}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    assets_upper = {a.upper() for a in assets}
    pools = await _fetch_all_pools()
    results: list[dict] = []

    for pool in pools:
        project = pool.get("project", "")
        symbol = (pool.get("symbol") or "").upper()
        chain = pool.get("chain", "")

        if project not in _LENDING_PROJECTS:
            continue
        if chain not in _LENDING_CHAINS:
            continue
        # Check if any requested asset appears in the symbol
        if not any(a in symbol for a in assets_upper):
            continue

        # Derive canonical asset name
        matched_asset = next((a for a in assets_upper if a in symbol), symbol)

        results.append(
            {
                "protocol": _display_name(project),
                "asset": matched_asset,
                "apy_supply": round(float(pool.get("apyBase") or pool.get("apy") or 0), 4),
                "apy_borrow": round(float(pool.get("apyBaseBorrow") or 0), 4),
                "tvl_usd": float(pool.get("tvlUsd") or 0),
                "chain": chain,
                "pool_id": pool.get("pool", ""),
            }
        )

    results.sort(key=lambda r: (r["asset"], -r["apy_supply"]))
    _set_cached(cache_key, results, 1800)
    return results


async def get_top_yield_opportunities(
    min_tvl_usd: float = 1_000_000,
    limit: int = 20,
) -> list[dict]:
    """
    Top yield opportunities across all DeFi protocols.

    Filters by TVL > *min_tvl_usd*, APY in (0, 200), and supported chains.
    Returns up to *limit* rows sorted by APY descending.  Cached 30 minutes.
    """
    cache_key = f"top_yields:{min_tvl_usd}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    pools = await _fetch_all_pools()
    results: list[dict] = []

    for pool in pools:
        chain = pool.get("chain", "")
        if chain not in _YIELD_CHAINS:
            continue
        tvl = float(pool.get("tvlUsd") or 0)
        if tvl < min_tvl_usd:
            continue
        apy = float(pool.get("apy") or 0)
        if apy <= 0 or apy >= 200:
            continue

        project = pool.get("project", "")
        symbol = pool.get("symbol", "")
        exposure_raw = pool.get("exposure") or []
        exposure: list[str] = (
            exposure_raw if isinstance(exposure_raw, list) else [exposure_raw]
        )

        results.append(
            {
                "protocol": _display_name(project),
                "pool_name": symbol,
                "apy": round(apy, 4),
                "apy_base": round(float(pool.get("apyBase") or 0), 4),
                "apy_reward": round(float(pool.get("apyReward") or 0), 4),
                "tvl_usd": tvl,
                "chain": chain,
                "category": _category_for_project(project, symbol),
                "exposure": exposure,
                "il_risk": pool.get("ilRisk") or _il_risk(project, symbol),
            }
        )

    results.sort(key=lambda r: r["apy"], reverse=True)
    results = results[:limit]
    _set_cached(cache_key, results, 1800)
    return results
