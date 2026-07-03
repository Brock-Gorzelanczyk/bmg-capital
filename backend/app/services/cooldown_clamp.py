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

# 2026-07-02 Brock directive: replace blanket 24h clamp with per-strategy tuning.
# The 24h clamp was killing 100% of intraday fills. Aggressive paper-trading
# doctrine: cooldown should match the strategy's actual signal half-life, not
# a blanket floor. Values below are the ceiling; profile YAML's cooldown_minutes
# still applies at the _can_fire_signal layer and can be TIGHTER but not looser.
_STRATEGY_COOLDOWN_MIN: dict[str, int] = {
    # Scalpers: 5-min cooldown. Signals decay fast on 1m/5m bars.
    "scalp":  5,
    # Day traders: 30-min cooldown. Ample re-entry room within a session.
    "day":    30,
    # Swing: 4h cooldown. Half a session between adds.
    "swing":  4 * 60,
    # Long-term / DCA: 24h cooldown. Preserve original floor for slow strats.
    "lt":     24 * 60,
    # Fleet default when strategy family isn't obvious from bot_id.
    "default": 15,
}

# Legacy — held for callers that read this constant. Old default was 24h; the
# effective cooldown is now bot-family driven via _cooldown_minutes_for_bot().
COOLDOWN_HOURS: int = 24

# In-process Discord rate-limit cache (mirrors asset_class_registry):
# key = (bot_id, symbol, utc_date_iso) -> True if alerted today.
_violation_alert_seen: dict[tuple[str, str, str], bool] = {}


def _cooldown_minutes_for_bot(bot_id: str) -> int:
    """Return the effective clamp cooldown minutes for a bot family.

    Heuristic on bot_id substrings so we don't need a config table:
    - anything with "scalp" or ends in "_1m"     → scalp (5 min)
    - anything with "day", "orb", "gap", "10m"    → day (30 min)
    - "swing", "momentum", "onchain", "quant_15m" → swing (4h)
    - "lt", "dca", "pead"                          → lt (24h)
    - else                                         → default (15 min)
    """
    b = bot_id.lower()
    if "scalp" in b or b.endswith("_1m"):
        return _STRATEGY_COOLDOWN_MIN["scalp"]
    if "day" in b or "orb" in b or "gap" in b or b.endswith("_10m"):
        return _STRATEGY_COOLDOWN_MIN["day"]
    if "swing" in b or "momentum" in b or "onchain" in b or b.endswith("_15m") or "meme" in b or "defi" in b or "universe" in b or "aggressive" in b or "alt_focus" in b or "meanrev" in b or "mean_rev" in b:
        return _STRATEGY_COOLDOWN_MIN["swing"]
    if "_lt" in b or b.endswith("lt") or "dca" in b or "pead" in b:
        return _STRATEGY_COOLDOWN_MIN["lt"]
    return _STRATEGY_COOLDOWN_MIN["default"]


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
                "SELECT cooldown_until, last_entry_at FROM bot_symbol_cooldown "
                "WHERE bot_id = :bot_id AND symbol = :symbol"
            ),
            {"bot_id": bot_id, "symbol": symbol},
        ).fetchone()
        if row is None:
            return (True, None)

        raw_cd = row[0]
        raw_last = row[1] if len(row) > 1 else None
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

        # 2026-07-02: rows written under the OLD 24h clamp regime carry
        # cooldown_until = last_entry_at + 24h. That would keep blocking
        # scalpers for the next ~20h despite the new per-strategy tuning.
        # Cap the effective cooldown at last_entry_at + new-family minutes.
        last_entry: Optional[datetime] = None
        if raw_last is not None:
            _rl = raw_last
            if isinstance(_rl, str):
                _rl = _rl.replace("Z", "+00:00")
                try:
                    last_entry = datetime.fromisoformat(_rl)
                except ValueError:
                    try:
                        last_entry = datetime.fromisoformat(_rl.split("+")[0]).replace(tzinfo=timezone.utc)
                    except ValueError:
                        last_entry = None
            elif isinstance(_rl, datetime):
                last_entry = _rl
            if last_entry and last_entry.tzinfo is None:
                last_entry = last_entry.replace(tzinfo=timezone.utc)

        if last_entry is not None:
            effective_minutes = _cooldown_minutes_for_bot(bot_id)
            effective_until = last_entry + timedelta(minutes=effective_minutes)
            if effective_until < cooldown_until:
                cooldown_until = effective_until

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
    """UPSERT cooldown_until = now + per-strategy minutes, last_entry_at = now.

    2026-07-02 Brock directive: cooldown is bot-family driven, not a blanket
    24h floor. See _cooldown_minutes_for_bot for the family → minutes map.

    Returns the new cooldown_until (UTC, timezone-aware).
    Idempotent: callers should call this AFTER successful position
    insert. Safe to call multiple times for the same trade — UPSERT
    will overwrite with a fresher cooldown.
    """
    now = datetime.now(timezone.utc)
    minutes = _cooldown_minutes_for_bot(bot_id)
    cooldown_until = now + timedelta(minutes=minutes)
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
