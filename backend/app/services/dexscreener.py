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
# Helpers
# ---------------------------------------------------------------------------

_BASE = "https://api.dexscreener.com"
_TIMEOUT = 15.0
_CACHE_TTL = 300  # 5 minutes


def _parse_pair(pair: dict) -> dict:
    """Normalise a raw Dexscreener pair object into the canonical shape."""
    created_at_ms: int | None = pair.get("pairCreatedAt")
    age_hours: float = 0.0
    if created_at_ms:
        age_hours = (time.time() * 1000 - created_at_ms) / 3_600_000

    price_change = pair.get("priceChange") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}
    base_token = pair.get("baseToken") or {}

    return {
        "address": base_token.get("address", ""),
        "name": base_token.get("name", ""),
        "symbol": base_token.get("symbol", ""),
        "chain": pair.get("chainId", ""),
        "dex": pair.get("dexId", ""),
        "price_usd": float(pair.get("priceUsd") or 0),
        "price_change_24h": float(price_change.get("h24") or 0),
        "volume_24h": float(volume.get("h24") or 0),
        "liquidity_usd": float(liquidity.get("usd") or 0),
        "pair_address": pair.get("pairAddress", ""),
        "age_hours": round(age_hours, 2),
        "url": pair.get("url", ""),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_new_launches(
    chains: list[str] | None = None,
    min_liquidity_usd: float = 25_000,
    limit: int = 50,
) -> list[dict]:
    """
    New token pairs created in last 24 h on Dexscreener.

    Hits the token-profiles/latest endpoint first, then enriches with pair
    search results.  Filters out pairs older than 48 h and those whose
    liquidity falls below *min_liquidity_usd*.  Returns up to *limit* rows
    sorted by volume_24h descending.  Results are cached for 5 minutes.
    """
    if chains is None:
        chains = ["ethereum", "bsc", "solana"]

    cache_key = f"new_launches:{'|'.join(sorted(chains))}:{min_liquidity_usd}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results: list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # --- 1. token-profiles/latest ----------------------------------------
        try:
            resp = await client.get(f"{_BASE}/token-profiles/latest/v1")
            resp.raise_for_status()
            profiles_data = resp.json()
            profile_addresses: list[str] = []
            for profile in profiles_data if isinstance(profiles_data, list) else []:
                chain_id = profile.get("chainId", "")
                if chain_id in chains:
                    addr = profile.get("tokenAddress", "")
                    if addr:
                        profile_addresses.append(addr)
        except Exception:
            profile_addresses = []

        # --- 2. Search pairs for each chain ----------------------------------
        pairs_seen: set[str] = set()

        async def _fetch_chain_pairs(chain: str) -> list[dict]:
            try:
                r = await client.get(
                    f"{_BASE}/latest/dex/search",
                    params={"q": chain},
                )
                r.raise_for_status()
                return r.json().get("pairs") or []
            except Exception:
                return []

        for chain in chains:
            raw_pairs = await _fetch_chain_pairs(chain)
            for pair in raw_pairs:
                parsed = _parse_pair(pair)
                key = parsed["pair_address"] or parsed["address"]
                if key and key not in pairs_seen:
                    pairs_seen.add(key)
                    results.append(parsed)

        # --- 3. Also fetch pairs for addresses gathered from profiles ---------
        if profile_addresses:
            addr_chunk = ",".join(profile_addresses[:30])
            try:
                r = await client.get(
                    f"{_BASE}/latest/dex/tokens/{addr_chunk}",
                )
                r.raise_for_status()
                extra_pairs = r.json().get("pairs") or []
                for pair in extra_pairs:
                    parsed = _parse_pair(pair)
                    key = parsed["pair_address"] or parsed["address"]
                    if key and key not in pairs_seen:
                        pairs_seen.add(key)
                        results.append(parsed)
            except Exception:
                pass

    # --- 4. Filter & sort ------------------------------------------------
    results = [
        p
        for p in results
        if p["age_hours"] <= 48 and p["liquidity_usd"] >= min_liquidity_usd
    ]
    results.sort(key=lambda p: p["volume_24h"], reverse=True)
    results = results[:limit]

    _set_cached(cache_key, results, _CACHE_TTL)
    return results


async def get_trending_pairs(chain: str = "ethereum", limit: int = 20) -> list[dict]:
    """
    Trending pairs boosted / searched most on Dexscreener for *chain*.

    Endpoint: GET https://api.dexscreener.com/latest/dex/search?q={chain}
    Returns the same shape as *get_new_launches*.  Cached 5 minutes.
    """
    cache_key = f"trending:{chain}:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BASE}/latest/dex/search",
                params={"q": chain},
            )
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            results = [_parse_pair(p) for p in pairs]
    except Exception:
        pass

    results = results[:limit]
    _set_cached(cache_key, results, _CACHE_TTL)
    return results


async def get_memecoin_candidates(limit: int = 30) -> list[dict]:
    """
    Tokens matching a memecoin profile: < 48 h old, high volume/liquidity
    ratio, rapid holder growth.

    Uses the token-profiles/latest endpoint to seed candidates then enriches
    with pair data.  Returns up to *limit* rows, each including a *risk_score*
    field (1–10, higher = riskier).  Cached 5 minutes.

    Risk scoring:
      age < 6 h        → +3
      liquidity < 50 k → +2
      vol/liq > 10     → +2
    """
    cache_key = f"memecoins:{limit}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results: list[dict] = []
    pairs_seen: set[str] = set()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # Gather token addresses from latest profiles
        profile_addresses: list[tuple[str, str]] = []  # (chain, address)
        try:
            resp = await client.get(f"{_BASE}/token-profiles/latest/v1")
            resp.raise_for_status()
            data = resp.json()
            profiles = data if isinstance(data, list) else []
            for profile in profiles:
                chain_id = profile.get("chainId", "")
                addr = profile.get("tokenAddress", "")
                if chain_id and addr:
                    profile_addresses.append((chain_id, addr))
        except Exception:
            pass

        # Fetch pair details
        if profile_addresses:
            addr_list = [a for _, a in profile_addresses[:50]]
            chunk = ",".join(addr_list)
            try:
                r = await client.get(f"{_BASE}/latest/dex/tokens/{chunk}")
                r.raise_for_status()
                pairs = r.json().get("pairs") or []
                for pair in pairs:
                    parsed = _parse_pair(pair)
                    key = parsed["pair_address"] or parsed["address"]
                    if key and key not in pairs_seen:
                        pairs_seen.add(key)
                        results.append(parsed)
            except Exception:
                pass

        # Also search generic memecoin terms
        for query in ["meme", "pepe", "dog", "cat", "shib"]:
            try:
                r = await client.get(
                    f"{_BASE}/latest/dex/search",
                    params={"q": query},
                )
                r.raise_for_status()
                for pair in r.json().get("pairs") or []:
                    parsed = _parse_pair(pair)
                    key = parsed["pair_address"] or parsed["address"]
                    if key and key not in pairs_seen:
                        pairs_seen.add(key)
                        results.append(parsed)
            except Exception:
                continue

    # Filter to < 48 h old
    results = [p for p in results if p["age_hours"] <= 48]

    # Compute risk score
    for p in results:
        score = 1
        if p["age_hours"] < 6:
            score += 3
        if p["liquidity_usd"] < 50_000:
            score += 2
        if p["liquidity_usd"] > 0 and p["volume_24h"] / p["liquidity_usd"] > 10:
            score += 2
        p["risk_score"] = min(score, 10)

    results.sort(key=lambda p: p["volume_24h"], reverse=True)
    results = results[:limit]

    _set_cached(cache_key, results, _CACHE_TTL)
    return results
