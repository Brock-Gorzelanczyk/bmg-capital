"""
Halt on abnormal market conditions:
- Flash crash: price drops >3% in <5 bars
- Vol spike: bar range > 5x ATR
- Exchange halt: 0 volume bars
- Circuit breaker: any symbol down >20% in session

On detection: pause bot (set enabled=False, paused_reason='anomaly'),
log AnomalyEvent, return halt=True.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_FLASH_CRASH_PCT = 3.0    # % drop
_FLASH_CRASH_BARS = 5     # within N bars
_VOL_SPIKE_MULTIPLIER = 5.0
_CIRCUIT_BREAKER_PCT = 20.0
_ATR_PERIOD = 14


def _atr(bars: list[dict], period: int = _ATR_PERIOD) -> float | None:
    """Compute ATR."""
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(bars)):
        h = float(bars[i].get("h") or bars[i].get("high") or 0)
        l = float(bars[i].get("l") or bars[i].get("low") or 0)
        pc = float(bars[i - 1].get("c") or bars[i - 1].get("close") or 0)
        if h == 0 and l == 0 and pc == 0:
            continue
        tr = max(h - l, abs(h - pc), abs(l - pc))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    return sum(true_ranges[-period:]) / period


def _log_anomaly(allocation_id: int, anomaly_type: str, snapshot: dict, db) -> None:
    """Persist AnomalyEvent to DB if table exists."""
    try:
        from app.db.models.bots import AnomalyEvent  # may not exist yet
        event = AnomalyEvent(
            allocation_id=allocation_id,
            anomaly_type=anomaly_type,
            snapshot=snapshot,
            detected_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
    except Exception as exc:
        logger.debug("[anomaly] Could not log AnomalyEvent (table may not exist): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def _pause_allocation(allocation_id: int, reason: str, db) -> None:
    """Set allocation enabled=False with paused_reason, then notify the user."""
    try:
        from app.db.models.bots import BotAllocation, BotProfile
        from app.db.models.users import User

        alloc = db.query(BotAllocation).filter(BotAllocation.id == allocation_id).first()
        if alloc:
            alloc.enabled = False
            alloc.paused_reason = reason
            db.commit()
            logger.warning(
                "[anomaly] Allocation %d paused: %s", allocation_id, reason
            )

            # Notify the allocation's owner
            try:
                from strategy_lab.notifier import notify

                user = db.query(User).filter(User.id == alloc.user_id).first()
                profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
                bot_label = profile.name if profile else f"allocation_{allocation_id}"
                if user:
                    notify(
                        user_id=user.id,
                        user_email=user.email,
                        notification_type="anomaly",
                        subject=f"Anomaly detected — {bot_label} auto-paused",
                        body=(
                            f"Bot <strong>{bot_label}</strong> has been automatically paused "
                            f"due to an anomaly: {reason}. "
                            f"Review the Command Center before resuming."
                        ),
                        bot_name=bot_label,
                    )
            except Exception as notify_exc:
                logger.debug("[anomaly] Notification failed for allocation %d: %s", allocation_id, notify_exc)

    except Exception as exc:
        logger.error("[anomaly] Could not pause allocation %d: %s", allocation_id, exc)
        try:
            db.rollback()
        except Exception:
            pass


def check_for_anomaly(
    symbol: str,
    bars: list[dict],
    allocation_id: int,
    db,
) -> dict:
    """Returns {halt: bool, anomaly_type: str | None, snapshot: dict}"""
    if not bars or len(bars) < 2:
        return {"halt": False, "anomaly_type": None, "snapshot": {}}

    latest = bars[-1]
    latest_close = float(latest.get("c") or latest.get("close") or 0)
    latest_high = float(latest.get("h") or latest.get("high") or 0)
    latest_low = float(latest.get("l") or latest.get("low") or 0)
    latest_vol = float(latest.get("v") or latest.get("volume") or 0)

    # ── 1. Exchange halt: 0 volume ────────────────────────────────────────────
    if latest_vol == 0:
        snapshot = {"symbol": symbol, "bar": latest, "check": "zero_volume"}
        _log_anomaly(allocation_id, "exchange_halt", snapshot, db)
        _pause_allocation(allocation_id, "anomaly:exchange_halt", db)
        logger.warning("[anomaly:%s] Exchange halt detected (zero volume)", symbol)
        return {"halt": True, "anomaly_type": "exchange_halt", "snapshot": snapshot}

    # ── 2. Flash crash: drop >3% in last 5 bars ───────────────────────────────
    window = bars[-_FLASH_CRASH_BARS:] if len(bars) >= _FLASH_CRASH_BARS else bars
    window_open = float(window[0].get("o") or window[0].get("open") or window[0].get("c") or window[0].get("close") or 0)
    if window_open > 0 and latest_close > 0:
        drop_pct = ((window_open - latest_close) / window_open) * 100
        if drop_pct >= _FLASH_CRASH_PCT:
            snapshot = {
                "symbol": symbol,
                "drop_pct": round(drop_pct, 4),
                "window_bars": _FLASH_CRASH_BARS,
                "open_price": window_open,
                "close_price": latest_close,
            }
            _log_anomaly(allocation_id, "flash_crash", snapshot, db)
            _pause_allocation(allocation_id, f"anomaly:flash_crash:{drop_pct:.1f}%", db)
            logger.warning(
                "[anomaly:%s] Flash crash: -%.2f%% in %d bars",
                symbol, drop_pct, _FLASH_CRASH_BARS,
            )
            return {"halt": True, "anomaly_type": "flash_crash", "snapshot": snapshot}

    # ── 3. Vol spike: bar range > 5x ATR ──────────────────────────────────────
    atr_val = _atr(bars[:-1])  # ATR from prior bars
    if atr_val is not None and atr_val > 0:
        bar_range = latest_high - latest_low
        if bar_range > atr_val * _VOL_SPIKE_MULTIPLIER:
            snapshot = {
                "symbol": symbol,
                "bar_range": round(bar_range, 4),
                "atr": round(atr_val, 4),
                "multiplier": round(bar_range / atr_val, 2),
            }
            _log_anomaly(allocation_id, "vol_spike", snapshot, db)
            _pause_allocation(allocation_id, f"anomaly:vol_spike:{bar_range / atr_val:.1f}x", db)
            logger.warning(
                "[anomaly:%s] Vol spike: range=%.4f is %.1fx ATR=%.4f",
                symbol, bar_range, bar_range / atr_val, atr_val,
            )
            return {"halt": True, "anomaly_type": "vol_spike", "snapshot": snapshot}

    # ── 4. Circuit breaker: >20% down from session open ───────────────────────
    # Use first bar of the day as session open
    session_open = float(bars[0].get("o") or bars[0].get("open") or bars[0].get("c") or bars[0].get("close") or 0)
    if session_open > 0 and latest_close > 0:
        session_drop = ((session_open - latest_close) / session_open) * 100
        if session_drop >= _CIRCUIT_BREAKER_PCT:
            snapshot = {
                "symbol": symbol,
                "session_drop_pct": round(session_drop, 4),
                "session_open": session_open,
                "current_price": latest_close,
            }
            _log_anomaly(allocation_id, "circuit_breaker", snapshot, db)
            _pause_allocation(allocation_id, f"anomaly:circuit_breaker:{session_drop:.1f}%", db)
            logger.warning(
                "[anomaly:%s] Circuit breaker: -%.2f%% from session open",
                symbol, session_drop,
            )
            return {"halt": True, "anomaly_type": "circuit_breaker", "snapshot": snapshot}

    return {"halt": False, "anomaly_type": None, "snapshot": {}}
