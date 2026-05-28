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

_GOPLUS_BASE = "https://api.gopluslabs.io/api/v1"
_TIMEOUT = 15.0
_TOKEN_CACHE_TTL = 600   # 10 minutes
_WALLET_CACHE_TTL = 300  # 5 minutes

# Chain IDs that use the EVM token_security endpoint
_EVM_CHAIN_IDS = frozenset(["1", "56", "137", "42161", "8453", "10", "43114", "250"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag(value: Any) -> bool:
    """Convert GoPlus "1"/"0" or 1/0 to bool."""
    return str(value) == "1"


def _float_field(raw: dict, key: str, default: float = 0.0) -> float:
    v = raw.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _int_field(raw: dict, key: str, default: int = 0) -> int:
    v = raw.get(key)
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _compute_top_holder_concentration(holders: list[dict]) -> float:
    """Sum of percent fields for top 10 holders (0–100 scale)."""
    total = 0.0
    for h in holders[:10]:
        pct = _float_field(h, "percent")
        # DeFi API returns fractions (0.05 = 5%) or percentages (5.0) — normalise
        if pct > 1:
            total += pct
        else:
            total += pct * 100
    return round(min(total, 100.0), 2)


def _compute_lp_lock(lp_holders: list[dict]) -> tuple[bool, float]:
    """Return (any_locked, locked_pct)."""
    locked_pct = 0.0
    any_locked = False
    for lph in lp_holders:
        if _flag(lph.get("is_locked")):
            any_locked = True
            pct = _float_field(lph, "percent")
            locked_pct += pct * 100 if pct <= 1 else pct
    return any_locked, round(min(locked_pct, 100.0), 2)


def _compute_creator_pct(raw: dict) -> float:
    """Creator balance as % of total supply."""
    creator_bal_str = raw.get("creator_balance", "0") or "0"
    total_supply_str = raw.get("total_supply", "0") or "0"
    try:
        creator_bal = float(creator_bal_str)
        total_supply = float(total_supply_str)
        if total_supply == 0:
            return 0.0
        return round((creator_bal / total_supply) * 100, 2)
    except (ValueError, TypeError):
        return 0.0


def _build_risk_score_and_flags(
    is_honeypot: bool,
    sell_tax: float,
    is_open_source: bool,
    is_mintable: bool,
    top_holder_concentration: float,
    creator_balance_pct: float,
    lp_locked: bool,
) -> tuple[int, list[str]]:
    score = 0
    flags: list[str] = []

    if is_honeypot:
        score += 50
        flags.append("Honeypot detected")
    if sell_tax > 0.1:
        score += 20
        flags.append(f"Very high sell tax ({sell_tax * 100:.1f}%)")
    elif sell_tax > 0.05:
        score += 10
        flags.append(f"High sell tax ({sell_tax * 100:.1f}%)")
    if not is_open_source:
        score += 15
        flags.append("Contract not open-source")
    if is_mintable:
        score += 10
        flags.append("Token is mintable")
    if top_holder_concentration > 50:
        score += 15
        flags.append(f"Top holders own {top_holder_concentration:.1f}% of supply")
    elif top_holder_concentration > 30:
        score += 8
        flags.append(f"Top holders own {top_holder_concentration:.1f}% of supply")
    if creator_balance_pct > 20:
        score += 10
        flags.append(f"Creator holds {creator_balance_pct:.1f}% of supply")
    if not lp_locked:
        score += 5
        flags.append("LP not locked")

    return min(score, 100), flags


def _parse_token_result(
    address: str,
    raw: dict,
    chain_id: str,
) -> dict:
    """Transform a single GoPlus token result into the canonical shape."""
    is_honeypot = _flag(raw.get("is_honeypot"))
    sell_tax = _float_field(raw, "sell_tax")
    buy_tax = _float_field(raw, "buy_tax")
    is_open_source = _flag(raw.get("is_open_source"))
    is_mintable = _flag(raw.get("is_mintable"))
    is_proxy = _flag(raw.get("is_proxy"))
    is_blacklisted = _flag(raw.get("is_blacklisted"))
    is_whitelisted = _flag(raw.get("is_whitelisted"))
    holder_count = _int_field(raw, "holder_count")

    holders: list[dict] = raw.get("holders") or []
    lp_holders: list[dict] = raw.get("lp_holders") or []

    top_holder_concentration = _compute_top_holder_concentration(holders)
    lp_locked, lp_lock_pct = _compute_lp_lock(lp_holders)
    creator_balance_pct = _compute_creator_pct(raw)

    risk_score, risk_flags = _build_risk_score_and_flags(
        is_honeypot=is_honeypot,
        sell_tax=sell_tax,
        is_open_source=is_open_source,
        is_mintable=is_mintable,
        top_holder_concentration=top_holder_concentration,
        creator_balance_pct=creator_balance_pct,
        lp_locked=lp_locked,
    )

    return {
        "address": address,
        "name": raw.get("token_name", ""),
        "symbol": raw.get("token_symbol", ""),
        "is_open_source": is_open_source,
        "is_proxy": is_proxy,
        "is_mintable": is_mintable,
        "is_honeypot": is_honeypot,
        "buy_tax": buy_tax,
        "sell_tax": sell_tax,
        "is_blacklisted": is_blacklisted,
        "is_whitelisted": is_whitelisted,
        "holder_count": holder_count,
        "top_holder_concentration": top_holder_concentration,
        "lp_locked": lp_locked,
        "lp_lock_pct": lp_lock_pct,
        "creator_balance_pct": creator_balance_pct,
        "risk_score": risk_score,
        "risk_flags": risk_flags,
        "chain_id": chain_id,
        "ok": True,
        "error": None,
    }


def _error_result(address: str, chain_id: str, error: str) -> dict:
    return {
        "address": address,
        "name": "",
        "symbol": "",
        "is_open_source": False,
        "is_proxy": False,
        "is_mintable": False,
        "is_honeypot": False,
        "buy_tax": 0.0,
        "sell_tax": 0.0,
        "is_blacklisted": False,
        "is_whitelisted": False,
        "holder_count": 0,
        "top_holder_concentration": 0.0,
        "lp_locked": False,
        "lp_lock_pct": 0.0,
        "creator_balance_pct": 0.0,
        "risk_score": 0,
        "risk_flags": [],
        "chain_id": chain_id,
        "ok": False,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_token(
    contract_address: str,
    chain_id: str = "1",
) -> dict:
    """
    Check token security via GoPlus API.

    Supports EVM chains (chain_id as numeric string) and Solana ("solana").
    Results are cached for 10 minutes per (address, chain_id).
    On any error, returns a safe fallback dict with ok=False.
    """
    address = contract_address.lower().strip()
    cache_key = f"token_security:{chain_id}:{address}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if chain_id.lower() == "solana":
                url = f"{_GOPLUS_BASE}/solana/token_security"
            else:
                url = f"{_GOPLUS_BASE}/token_security/{chain_id}"

            resp = await client.get(url, params={"contract_addresses": address})
            resp.raise_for_status()
            data = resp.json()

        result_map: dict = data.get("result") or {}
        # GoPlus keys the result by the queried address (may differ in case)
        raw = result_map.get(address) or result_map.get(
            contract_address
        ) or next(iter(result_map.values()), None)

        if raw is None:
            result = _error_result(address, chain_id, "No data returned by GoPlus")
        else:
            result = _parse_token_result(address, raw, chain_id)

    except httpx.HTTPStatusError as exc:
        result = _error_result(address, chain_id, f"HTTP {exc.response.status_code}")
    except Exception as exc:
        result = _error_result(address, chain_id, str(exc))

    _set_cached(cache_key, result, _TOKEN_CACHE_TTL)
    return result


async def check_wallet_approvals(
    wallet_address: str,
    chain_id: str = "1",
) -> dict:
    """
    Check what token approvals a wallet has granted via GoPlus.

    Endpoint: GET /api/v1/approval_security/{chain_id}?contract_addresses={wallet}
    Results are cached for 5 minutes per wallet.
    """
    wallet = wallet_address.lower().strip()
    cache_key = f"approvals:{chain_id}:{wallet}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    empty_result: dict = {
        "wallet": wallet,
        "chain_id": chain_id,
        "approvals": [],
        "total": 0,
        "high_risk_count": 0,
        "ok": False,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url = f"{_GOPLUS_BASE}/approval_security/{chain_id}"
            resp = await client.get(url, params={"contract_addresses": wallet})
            resp.raise_for_status()
            data = resp.json()

        result_map: dict = data.get("result") or {}
        raw = result_map.get(wallet) or result_map.get(wallet_address) or next(
            iter(result_map.values()), {}
        )

        # GoPlus returns a list under the wallet key (ERC20 approvals)
        approval_list: list[dict] = raw if isinstance(raw, list) else (
            raw.get("approved_list") or raw.get("token_approvals") or []
        )

        approvals: list[dict] = []
        high_risk = 0

        for item in approval_list:
            spender = item.get("spender_address", "")
            approved_amount = item.get("approved_amount", "0")
            # Detect unlimited approvals
            try:
                if int(approved_amount) >= 2**200:
                    approved_amount = "Unlimited"
            except (ValueError, TypeError):
                pass

            # Derive risk level from open-source status and known flags
            is_os = _flag(item.get("is_open_source"))
            is_malicious = _flag(item.get("is_malicious"))
            if is_malicious:
                risk_level = "danger"
                high_risk += 1
            elif not is_os:
                risk_level = "warning"
            else:
                risk_level = "safe"

            approvals.append(
                {
                    "token_address": item.get("token_address", ""),
                    "token_name": item.get("token_name", ""),
                    "token_symbol": item.get("token_symbol", ""),
                    "spender_address": spender,
                    "spender_name": item.get("spender_name") or item.get("tag", ""),
                    "approved_amount": approved_amount,
                    "risk_level": risk_level,
                    "is_open_source": is_os,
                    "last_used": item.get("last_used") or None,
                }
            )

        result = {
            "wallet": wallet,
            "chain_id": chain_id,
            "approvals": approvals,
            "total": len(approvals),
            "high_risk_count": high_risk,
            "ok": True,
        }

    except httpx.HTTPStatusError as exc:
        result = {**empty_result, "ok": False}
        result["error"] = f"HTTP {exc.response.status_code}"
    except Exception as exc:
        result = {**empty_result, "ok": False}
        result["error"] = str(exc)

    _set_cached(cache_key, result, _WALLET_CACHE_TTL)
    return result


async def batch_check_tokens(
    addresses_by_chain: dict[str, list[str]],
) -> dict[str, dict]:
    """
    Check multiple tokens at once.

    Accepts ``{chain_id: [addr1, addr2, ...]}`` and returns
    ``{addr: security_result}``.  Uses GoPlus's comma-separated batch
    endpoint per chain.  Individual results are cached.
    """
    output: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for chain_id, addresses in addresses_by_chain.items():
            if not addresses:
                continue

            # Check cache first; collect uncached addresses
            uncached: list[str] = []
            for addr in addresses:
                key = f"token_security:{chain_id}:{addr.lower()}"
                hit = _get_cached(key)
                if hit is not None:
                    output[addr.lower()] = hit
                else:
                    uncached.append(addr)

            if not uncached:
                continue

            # Batch request: GoPlus accepts up to 50 comma-separated addresses
            batch_size = 50
            for i in range(0, len(uncached), batch_size):
                chunk = uncached[i : i + batch_size]
                combined = ",".join(a.lower() for a in chunk)

                try:
                    if chain_id.lower() == "solana":
                        url = f"{_GOPLUS_BASE}/solana/token_security"
                    else:
                        url = f"{_GOPLUS_BASE}/token_security/{chain_id}"

                    resp = await client.get(
                        url, params={"contract_addresses": combined}
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    result_map: dict = data.get("result") or {}

                    for addr in chunk:
                        addr_lower = addr.lower()
                        raw = result_map.get(addr_lower) or result_map.get(addr)
                        if raw:
                            parsed = _parse_token_result(addr_lower, raw, chain_id)
                        else:
                            parsed = _error_result(
                                addr_lower, chain_id, "Not found in batch response"
                            )
                        _set_cached(
                            f"token_security:{chain_id}:{addr_lower}",
                            parsed,
                            _TOKEN_CACHE_TTL,
                        )
                        output[addr_lower] = parsed

                except Exception as exc:
                    for addr in chunk:
                        addr_lower = addr.lower()
                        err = _error_result(addr_lower, chain_id, str(exc))
                        output[addr_lower] = err

    return output
