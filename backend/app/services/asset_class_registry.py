"""Canonical bot_id → asset_class registry. Single source of truth.

No env override, no DB lookup at runtime. If a bot is missing here, the
module raises at import time so the app refuses to boot.

Keys MUST match bot_profiles.name (the DB-canonical names used by
m027_force_clean_slate.ALLOCATIONS_CENTS). Brock's spec slugs
(stock_long_term, crypto_lt_dca, quant_mean_rev, quant_scalper) are
ALIASED so a typo raises a recognisable error rather than silently
returning None.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# DB-canonical bot_id → enforcement record
ASSET_CLASS_REGISTRY: dict[str, dict] = {
    "stock_swing":                  {"asset_class": "equity", "ticker_allowlist": None},
    "stock_lt":                     {"asset_class": "equity", "ticker_allowlist": None},
    "stock_day":                    {"asset_class": "equity", "ticker_allowlist": None},
    "crypto_day":                   {"asset_class": "crypto", "ticker_allowlist": None},
    "crypto_swing":                 {"asset_class": "crypto", "ticker_allowlist": None},
    "crypto_lt":                    {"asset_class": "crypto", "ticker_allowlist": None},
    "crypto_onchain":               {"asset_class": "crypto", "ticker_allowlist": None},
    "options_income":               {"asset_class": "option", "ticker_allowlist": None},
    "options_directional":          {"asset_class": "option", "ticker_allowlist": None},
    "crypto_quant_aggressive":      {"asset_class": "crypto", "ticker_allowlist": None},
    "crypto_quant_mean_reversion":  {"asset_class": "crypto", "ticker_allowlist": None},
    "crypto_quant_scalper":         {"asset_class": "crypto", "ticker_allowlist": None},
    "cash_floor":                   {"asset_class": "equity", "ticker_allowlist": ["SPY", "QQQ"]},
}

# Brock-spec-slug → DB-canonical name. Used only inside get_required_asset_class
# so callers that accidentally pass the spec slug get a hard error mentioning
# the correct name (rather than silently routing to a None-bot path).
_SPEC_SLUG_ALIASES: dict[str, str] = {
    "stock_long_term": "stock_lt",
    "crypto_lt_dca":   "crypto_lt",
    "quant_mean_rev":  "crypto_quant_mean_reversion",
    "quant_scalper":   "crypto_quant_scalper",
}

# Import-time invariant: every bot in m027's SPEC must be in the registry.
# Done inline (not via try/except) so the app refuses to boot if drifted.
from app.db.migrations.m027_force_clean_slate import ALLOCATIONS_CENTS as _M027_SPEC
_missing_in_registry = [b for b in _M027_SPEC.keys() if b not in ASSET_CLASS_REGISTRY]
if _missing_in_registry:
    raise RuntimeError(
        f"[asset_class_registry] bots in m027 SPEC missing from registry: "
        f"{_missing_in_registry} — refusing to boot"
    )
_missing_in_m027 = [b for b in ASSET_CLASS_REGISTRY.keys() if b not in _M027_SPEC]
if _missing_in_m027:
    raise RuntimeError(
        f"[asset_class_registry] bots in registry not in m027 SPEC: "
        f"{_missing_in_m027} — refusing to boot"
    )

# OCC option symbol regex (same one used in admin.py:2528). Examples:
#   SPY250816P00400000 (21 chars: 3-letter root + 6 YYMMDD + C/P + 8 strike)
#   AAPL250620C00150000 (root may be 1-6 chars)
_OCC_RE = re.compile(r"^[A-Z]+\d{6}[CP]\d{8}$")
# Crypto pair markers — Alpaca uses "BTC/USD", Kraken uses "BTCUSD" or
# "XBT/USD". Recognise any of these as crypto.
_CRYPTO_RE = re.compile(r"^[A-Z]{2,6}[/-]?(USD|USDT|USDC|EUR|BTC|ETH)$")


def get_required_asset_class(bot_id: str) -> str:
    """Return the canonical asset_class for a bot. Raises RuntimeError on
    unknown bot. Spec-slug aliases produce a helpful error pointing at the
    canonical name."""
    if bot_id in _SPEC_SLUG_ALIASES:
        canonical = _SPEC_SLUG_ALIASES[bot_id]
        raise RuntimeError(
            f"[asset_class_registry] bot_id={bot_id!r} is the spec slug; "
            f"use DB-canonical name {canonical!r} instead"
        )
    rec = ASSET_CLASS_REGISTRY.get(bot_id)
    if rec is None:
        raise RuntimeError(f"[asset_class_registry] unknown bot_id={bot_id!r}")
    return rec["asset_class"]


def get_ticker_allowlist(bot_id: str) -> Optional[list[str]]:
    """Return the allowlist (e.g., ["SPY","QQQ"] for cash_floor) or None
    if no allowlist applies. Unknown bot raises (same as required_asset_class)."""
    if bot_id in _SPEC_SLUG_ALIASES:
        raise RuntimeError(
            f"[asset_class_registry] bot_id={bot_id!r} is the spec slug; "
            f"use DB-canonical name {_SPEC_SLUG_ALIASES[bot_id]!r} instead"
        )
    rec = ASSET_CLASS_REGISTRY.get(bot_id)
    if rec is None:
        raise RuntimeError(f"[asset_class_registry] unknown bot_id={bot_id!r}")
    return rec["ticker_allowlist"]


def classify_instrument(symbol: str) -> str:
    """Return "equity" | "crypto" | "option" by inspecting the symbol string.
    Raises RuntimeError when the symbol cannot be confidently classified
    (better to refuse the order than misclassify it)."""
    if not isinstance(symbol, str) or not symbol:
        raise RuntimeError(f"[asset_class_registry] cannot classify empty symbol={symbol!r}")
    s = symbol.strip().upper()
    # OCC option format wins first — its regex is the most specific.
    if _OCC_RE.match(s):
        return "option"
    # Crypto pair markers
    if "/" in s or "-" in s:
        if _CRYPTO_RE.match(s):
            return "crypto"
        raise RuntimeError(f"[asset_class_registry] unclassifiable symbol={symbol!r}")
    # Plain ticker — 1-5 letters with optional .B/.A class share suffix
    # (covers AAPL, GOOG, BRK.B, etc). Reject anything that doesn't look
    # like a US equity ticker.
    if re.match(r"^[A-Z]{1,5}(\.[A-Z])?$", s):
        return "equity"
    raise RuntimeError(f"[asset_class_registry] unclassifiable symbol={symbol!r}")


# ── Discord ops-alert rate limit ────────────────────────────────────────
# Per (bot_id, symbol, UTC-day) at-most-once. In-memory dict is fine here:
# violations fire at most a few times/day per worker, and a restart resetting
# the cache is acceptable (each restart would re-fire once max, not spam).
# Across multiple uvicorn workers, each worker may send once per day —
# acceptable bound (<=N_workers alerts per bot/symbol/day, typically 1-2).
_OPS_ALERT_CACHE: dict[str, float] = {}
_OPS_ALERT_TTL_SECS = 24 * 3600


def _ops_alert_already_sent(bot_id: str, symbol: str) -> bool:
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{bot_id}|{symbol}|{day}"
    now = time.time()
    # Sweep stale entries opportunistically
    stale = [k for k, ts in _OPS_ALERT_CACHE.items() if now - ts > _OPS_ALERT_TTL_SECS]
    for k in stale:
        _OPS_ALERT_CACHE.pop(k, None)
    if key in _OPS_ALERT_CACHE:
        return True
    _OPS_ALERT_CACHE[key] = now
    return False


def validate_order(bot_id: str, symbol: str) -> None:
    """HARD gate. Raises RuntimeError if (bot_id, symbol) violates the
    registry. On violation: structured log + at-most-once-per-bot/symbol/day
    Discord ops alert (fire-and-forget). Returns None on pass.

    Call BEFORE any broker submit and BEFORE any BotTrade INSERT.
    """
    required = get_required_asset_class(bot_id)
    detected = classify_instrument(symbol)
    allowlist = get_ticker_allowlist(bot_id)

    violation_reason: Optional[str] = None
    if detected != required:
        violation_reason = f"asset_class_mismatch required={required} detected={detected}"
    elif allowlist is not None and symbol.strip().upper() not in [t.upper() for t in allowlist]:
        violation_reason = (
            f"ticker_not_in_allowlist allowlist={allowlist} symbol={symbol!r}"
        )

    if violation_reason is None:
        return  # pass

    logger.error(
        "[asset_class_violation] bot_id=%s symbol=%s required=%s detected=%s reason=%s",
        bot_id, symbol, required, detected, violation_reason,
    )

    # Fire-and-forget ops alert — rate limited.
    if not _ops_alert_already_sent(bot_id, symbol):
        try:
            from app.services.discord import send_ops_alert
            send_ops_alert(
                title="[asset_class_violation] order refused",
                message=(
                    f"bot_id={bot_id} symbol={symbol} required={required} "
                    f"detected={detected} — {violation_reason}"
                ),
                severity="critical",
                source="asset_class_registry.validate_order",
                fields=[
                    {"name": "Bot",      "value": bot_id, "inline": True},
                    {"name": "Symbol",   "value": symbol, "inline": True},
                    {"name": "Required", "value": required, "inline": True},
                    {"name": "Detected", "value": detected, "inline": True},
                ],
            )
        except Exception as _disc_exc:
            logger.warning("[asset_class_violation] ops_alert send failed: %s", _disc_exc)

    raise RuntimeError(
        f"[asset_class_violation] bot_id={bot_id} symbol={symbol} {violation_reason}"
    )
