"""SHIP 6 hard 24h per-(bot,symbol) cooldown clamp.

Sits ON TOP of YAML cooldown_minutes. The YAML setting still applies
(via scan_and_execute._can_fire_signal), but this clamp is the
non-negotiable floor: once a bot enters a symbol, no other entry on
that (bot,symbol) for 24h regardless of any profile knob.

Standing decision (vault context/06-decision-history.md): cooldown
clamped at 24h max — SHIP 6 makes it both max AND mandatory minimum
for any entry-creating path.

Multi-user scoping: cooldown is per-(bot_id, symbol), NOT per user.
This is intentional — bot_id is fleet-wide (user 1 vs user 3 share
crypto_quant_scalper), and the goal is to stop the strategy from
firing on a symbol regardless of who owns the allocation. This matches
the asset_class_registry pattern which also operates on bot_id without
user_id scoping.

Symbol case: stored verbatim (no .upper() normalization) to match the
rest of the codebase. 'BTC/USD' and 'btc/usd' are treated as separate
keys. Callers are expected to normalize before calling.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

COOLDOWN_HOURS: int = 24

# In-process Discord rate-limit cache (mirrors asset_class_registry):
# key = (bot_id, symbol, utc_date_iso) -> True if alerted today.
_violation_alert_seen: dict[tuple[str, str, str], bool] = {}


def check_cooldown(
    db,
    bot_id: str,
    symbol: str,
) -> tuple[bool, Optional[datetime]]:
    """Return (allowed, blocked_until).

    allowed=True if no row in bot_symbol_cooldown for (bot_id, symbol) OR
    if the existing row's cooldown_until <= now UTC.

    allowed=False if cooldown_until > now UTC. In that case blocked_until
    is the row's cooldown_until (timezone-aware UTC).

    On DB error: returns (True, None) — fail open so a transient DB hiccup
    doesn't halt the fleet. Mirrors the try/except pattern in
    scan_and_execute._can_fire_signal.

    Note: does NOT validate bot_id against ASSET_CLASS_REGISTRY.
    Unknown bot_ids simply return (True, None) if no row exists.
    """
    try:
        now = datetime.now(timezone.utc)
        row = db.execute(
            text(
                "SELECT cooldown_until FROM bot_symbol_cooldown "
                "WHERE bot_id = :bot_id AND symbol = :symbol"
            ),
            {"bot_id": bot_id, "symbol": symbol},
        ).fetchone()
        if row is None:
            return (True, None)

        raw_cd = row[0]
        # SQLite stores timestamps as ISO TEXT without tz. Parse and attach UTC.
        if isinstance(raw_cd, str):
            raw_cd = raw_cd.replace("Z", "+00:00")
            try:
                cooldown_until = datetime.fromisoformat(raw_cd)
            except ValueError:
                # Fallback: try without tz suffix
                cooldown_until = datetime.fromisoformat(raw_cd.split("+")[0])
                cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
        elif isinstance(raw_cd, datetime):
            cooldown_until = raw_cd
        else:
            logger.warning(
                "[cooldown_clamp] unexpected cooldown_until type %s for bot=%s symbol=%s",
                type(raw_cd), bot_id, symbol,
            )
            return (True, None)

        # Ensure tz-aware for comparison
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)

        # <= semantics: expiry == now means allowed
        if cooldown_until <= now:
            return (True, None)

        return (False, cooldown_until)

    except Exception as exc:
        logger.warning(
            "[cooldown_clamp] check_cooldown DB error for bot=%s symbol=%s: %s — failing open",
            bot_id, symbol, exc,
        )
        return (True, None)


def record_entry(
    db,
    bot_id: str,
    symbol: str,
) -> datetime:
    """UPSERT cooldown_until = now + 24h, last_entry_at = now.

    Returns the new cooldown_until (UTC, timezone-aware).
    Idempotent: callers should call this AFTER successful position
    insert. Safe to call multiple times for the same trade — UPSERT
    will overwrite with a fresher cooldown.
    """
    now = datetime.now(timezone.utc)
    cooldown_until = now + timedelta(hours=COOLDOWN_HOURS)
    now_iso = now.isoformat()
    cd_iso = cooldown_until.isoformat()

    db.execute(
        text("""
            INSERT INTO bot_symbol_cooldown
                (bot_id, symbol, cooldown_until, last_entry_at, created_at, updated_at)
            VALUES
                (:bot_id, :symbol, :cooldown_until, :last_entry_at, :created_at, :updated_at)
            ON CONFLICT(bot_id, symbol) DO UPDATE SET
                cooldown_until = excluded.cooldown_until,
                last_entry_at  = excluded.last_entry_at,
                updated_at     = excluded.updated_at
        """),
        {
            "bot_id": bot_id,
            "symbol": symbol,
            "cooldown_until": cd_iso,
            "last_entry_at": now_iso,
            "created_at": now_iso,
            "updated_at": now_iso,
        },
    )
    return cooldown_until


def _maybe_send_violation_alert(
    bot_id: str,
    symbol: str,
    blocked_until: Optional[datetime],
    user_id: Optional[int],
) -> None:
    """Post one ops alert per (bot_id, symbol) per UTC day. Rate-limited
    in-process. Mirrors asset_class_registry._maybe_send_violation_alert."""
    utc_date = datetime.now(timezone.utc).date().isoformat()
    key = (bot_id, symbol, utc_date)
    if _violation_alert_seen.get(key):
        return
    _violation_alert_seen[key] = True
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[WARN] cooldown_clamp_violation",
            message=(
                f"bot={bot_id} symbol={symbol} "
                f"blocked_until={blocked_until.isoformat() if blocked_until else '?'} "
                f"user_id={user_id}"
            ),
            severity="warn",
            source="cooldown_clamp",
        )
    except Exception as exc:
        logger.warning("[cooldown_clamp] ops alert failed: %s", exc)
