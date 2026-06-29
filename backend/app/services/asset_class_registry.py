"""Canonical bot-to-asset-class registry and per-order gate.

Every order-placement path MUST call validate_order(bot_id, symbol) before
writing a BotTrade row or submitting to any broker. Raising is intentional —
soft modes let the options-equity bug live for weeks (known-issues.md #2).

See SHIP 2 spec (.pipeline/01-spec.md) for the 12 paths gated and the
standing decisions that prohibit silent fallbacks.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ASSET_CLASS_REGISTRY: dict[str, dict] = {
    # bot_id (DB-canonical name) -> {asset_class, ticker_allowlist}
    "stock_swing":                  {"asset_class": "equity",  "ticker_allowlist": None},
    "stock_lt":                     {"asset_class": "equity",  "ticker_allowlist": None},
    "stock_day":                    {"asset_class": "equity",  "ticker_allowlist": None},
    "crypto_day":                   {"asset_class": "crypto",  "ticker_allowlist": None},
    "crypto_swing":                 {"asset_class": "crypto",  "ticker_allowlist": None},
    "crypto_lt":                    {"asset_class": "crypto",  "ticker_allowlist": None},
    "crypto_onchain":               {"asset_class": "crypto",  "ticker_allowlist": None},
    "options_income":               {"asset_class": "option",  "ticker_allowlist": None},
    "options_directional":          {"asset_class": "option",  "ticker_allowlist": None},
    "crypto_quant_aggressive":      {"asset_class": "crypto",  "ticker_allowlist": None},
    "crypto_quant_mean_reversion":  {"asset_class": "crypto",  "ticker_allowlist": None},
    "crypto_quant_scalper":         {"asset_class": "crypto",  "ticker_allowlist": None},
    "cash_floor":                   {"asset_class": "equity",  "ticker_allowlist": ["SPY", "QQQ"]},
}

# Spec-slug aliases — DO NOT silently resolve. Raise with the canonical name
# so callers fix the call site.
_SPEC_SLUG_ALIASES: dict[str, str] = {
    "stock_long_term":  "stock_lt",
    "crypto_lt_dca":    "crypto_lt",
    "quant_mean_rev":   "crypto_quant_mean_reversion",
    "quant_scalper":    "crypto_quant_scalper",
}

# Module-level invariant: every key in m027 ALLOCATIONS_CENTS must be a key
# in ASSET_CLASS_REGISTRY, else RuntimeError at import.
_M027_BOT_NAMES = {
    "stock_swing", "stock_lt", "stock_day",
    "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
    "options_income", "options_directional",
    "crypto_quant_aggressive", "crypto_quant_mean_reversion", "crypto_quant_scalper",
    "cash_floor",
}
_missing = _M027_BOT_NAMES - set(ASSET_CLASS_REGISTRY)
if _missing:
    raise RuntimeError(
        f"[asset_class_registry] m027 bot(s) missing from registry: {_missing}"
    )

# ---------------------------------------------------------------------------
# Discord rate-limit (in-process; resets on process restart — acceptable per spec)
# ---------------------------------------------------------------------------

# Key: (bot_id, symbol, utc_date_iso) -> True if already alerted today
_violation_alert_seen: dict[tuple[str, str, str], bool] = {}


def _maybe_send_violation_alert(
    bot_id: str,
    symbol: str,
    required: str,
    detected: str,
    user_id: int | None,
) -> None:
    """Post one ops alert per (bot_id, symbol) per UTC day. Rate-limited in-process."""
    utc_date = datetime.now(timezone.utc).date().isoformat()
    key = (bot_id, symbol, utc_date)
    if _violation_alert_seen.get(key):
        return
    _violation_alert_seen[key] = True
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[WARN] asset_class_violation",
            message=(
                f"bot={bot_id} symbol={symbol} "
                f"required={required} detected={detected} "
                f"user_id={user_id}"
            ),
            severity="warn",
            source="asset_class_registry",
        )
    except Exception as exc:
        logger.warning("[asset_class_registry] ops alert failed: %s", exc)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_required_asset_class(bot_id: str) -> str:
    """Return 'equity' | 'crypto' | 'option'.

    Raises RuntimeError for unknown bot_id OR if bot_id is a spec-slug alias
    (message includes the canonical name to use).
    """
    if bot_id in _SPEC_SLUG_ALIASES:
        canonical = _SPEC_SLUG_ALIASES[bot_id]
        raise RuntimeError(
            f"alias '{bot_id}' not allowed; use canonical '{canonical}'"
        )
    entry = ASSET_CLASS_REGISTRY.get(bot_id)
    if entry is None:
        raise RuntimeError(f"unknown bot_id: '{bot_id}'")
    return entry["asset_class"]


def get_ticker_allowlist(bot_id: str) -> list[str] | None:
    """Return the allowlist for cash_floor (['SPY','QQQ']), None for all others.

    Raises RuntimeError for unknown / alias bot_ids.
    """
    if bot_id in _SPEC_SLUG_ALIASES:
        canonical = _SPEC_SLUG_ALIASES[bot_id]
        raise RuntimeError(
            f"alias '{bot_id}' not allowed; use canonical '{canonical}'"
        )
    entry = ASSET_CLASS_REGISTRY.get(bot_id)
    if entry is None:
        raise RuntimeError(f"unknown bot_id: '{bot_id}'")
    return entry["ticker_allowlist"]


# OCC option symbol: e.g. "SPY  250816P00400000" (Alpaca padded, double-space)
# Up to 6 alpha, optional whitespace, 6-digit date, C or P, 8-digit strike
_OCC_RE = re.compile(r"^[A-Z]{1,6}\s*\d{6}[CP]\d{8}$")

# Crypto pair: ALPHA/USD | ALPHA/USDT | ALPHA/USDC
_CRYPTO_RE = re.compile(r"^[A-Z]{2,10}/(USD|USDT|USDC)$")

# Plain equity ticker: 1-5 alpha chars, or alpha.alpha (BRK.B)
_EQUITY_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,3})?$")


def classify_instrument(symbol: str) -> str:
    """Return 'equity' | 'crypto' | 'option'.

    Detection order:
      1. OCC option symbol (padded or tight) -> 'option'
      2. CRYPTO/QUOTE pair -> 'crypto'
      3. Plain ticker (1-5 alpha or BRK.B style) -> 'equity'
      4. Else: RuntimeError("unclassifiable symbol: {symbol}")
    """
    if not symbol or not symbol.strip():
        raise RuntimeError(f"unclassifiable symbol: {symbol!r}")

    s = symbol.strip()

    if _OCC_RE.match(s):
        return "option"

    if _CRYPTO_RE.match(s):
        return "crypto"

    if _EQUITY_RE.match(s):
        return "equity"

    raise RuntimeError(f"unclassifiable symbol: {symbol!r}")


def validate_order(bot_id: str, symbol: str) -> None:
    """Gate the order: raise RuntimeError on any asset-class mismatch.

    Logs the violation in EXACT format required by spec and sends a
    rate-limited Discord ops alert.

    Raises RuntimeError for:
      - unknown / alias bot_id
      - asset-class mismatch
      - cash_floor with non-allowlist ticker
    """
    validate_order_with_user(bot_id=bot_id, symbol=symbol, user_id=None)


def validate_order_with_user(
    bot_id: str,
    symbol: str,
    user_id: int | None = None,
) -> None:
    """Same as validate_order but logs user_id when provided."""
    required = get_required_asset_class(bot_id)  # raises for unknown/alias
    detected = classify_instrument(symbol)        # raises for unclassifiable

    # Cash-floor allowlist check (allowlist takes precedence over class match)
    allowlist = get_ticker_allowlist(bot_id)
    if allowlist is not None and symbol not in allowlist:
        msg = (
            f"ticker_not_allowlisted bot={bot_id} symbol={symbol} "
            f"allowlist={allowlist}"
        )
        logger.warning(
            "[asset_class_violation] bot_id=%s user_id=%s symbol=%s "
            "required=%s detected=%s",
            bot_id, user_id, symbol, required, detected,
        )
        _maybe_send_violation_alert(bot_id, symbol, required, detected, user_id)
        raise RuntimeError(msg)

    if required != detected:
        logger.warning(
            "[asset_class_violation] bot_id=%s user_id=%s symbol=%s "
            "required=%s detected=%s",
            bot_id, user_id, symbol, required, detected,
        )
        _maybe_send_violation_alert(bot_id, symbol, required, detected, user_id)
        raise RuntimeError(
            f"asset_class_violation bot={bot_id} symbol={symbol} "
            f"required={required} detected={detected}"
        )


def validate_order_with_cooldown_and_user(
    db,
    bot_id: str,
    symbol: str,
    user_id: int | None = None,
) -> None:
    """SHIP 6: asset_class check + 24h cooldown check, in that order.

    Raises RuntimeError with one of:
      - asset_class_violation ...   (from validate_order_with_user)
      - cooldown_clamp_violation bot=X symbol=Y blocked_until=Z

    Cooldown is enforced AFTER asset-class so a mis-configured bot still
    surfaces as the right error type.
    """
    validate_order_with_user(bot_id=bot_id, symbol=symbol, user_id=user_id)
    from app.services.cooldown_clamp import check_cooldown, _maybe_send_violation_alert as _cd_alert
    allowed, blocked_until = check_cooldown(db, bot_id, symbol)
    if not allowed:
        logger.warning(
            "[cooldown_clamp_violation] bot=%s symbol=%s blocked_until=%s",
            bot_id, symbol, blocked_until.isoformat() if blocked_until else "?",
        )
        _cd_alert(bot_id, symbol, blocked_until, user_id)
        raise RuntimeError(
            f"cooldown_clamp_violation bot={bot_id} symbol={symbol} "
            f"blocked_until={blocked_until.isoformat() if blocked_until else '?'}"
        )
