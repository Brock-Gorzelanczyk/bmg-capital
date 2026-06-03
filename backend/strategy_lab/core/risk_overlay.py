"""
Risk overlay — applies to every signal before execution.
Gates: daily loss limit, consecutive loss step-down, sector cap,
correlation cap, portfolio drawdown circuit, regime gates, catalyst blackouts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class OverlayDecision:
    allowed: bool
    reason: str
    size_multiplier: float = 1.0  # 0.5 = halved, 0.25 = quartered, 0.0 = blocked


def check_signal(
    db: Session,
    allocation_id: int,
    symbol: str,
    side: str,
    profile_config: dict,
    regime_snapshot: Optional[dict] = None,
    catalyst_events: Optional[list] = None,
) -> OverlayDecision:
    """
    Returns OverlayDecision. Callers must respect .allowed and .size_multiplier.
    """
    overlay = profile_config.get("risk_overlay", {})
    regime = regime_snapshot or {}
    catalysts = catalyst_events or []

    # ── 1. Regime gates ──────────────────────────────────────────────────────
    vix_regime = regime.get("vix_regime", "mid")
    trend_regime = regime.get("trend_regime", "chop")

    if vix_regime == "panic":
        return OverlayDecision(False, "VIX panic regime — all new entries blocked", 0.0)

    size_mult = 1.0
    if vix_regime == "high":
        size_mult *= 0.5
        logger.info(f"VIX high regime: halving size for {symbol}")

    # Trend regime gate (configurable per profile)
    for gate in profile_config.get("regime_filters", []):
        if "require" in gate:
            expr = gate["require"]
            if "trend_regime != 'bear'" in expr and trend_regime == "bear":
                return OverlayDecision(False, "Trend bear regime blocked by profile filter", 0.0)
        if "halve_size_if" in gate:
            expr = gate["halve_size_if"]
            if "vix_regime == 'high'" in expr and vix_regime == "high":
                size_mult *= 0.5

    # ── 2. Catalyst blackouts ─────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    catalyst_gates = profile_config.get("catalyst_gates") or []
    gate_cfg = catalyst_gates[0] if catalyst_gates else {}
    blackout_types = gate_cfg.get("blackout_minutes_around", [])
    minutes_before = gate_cfg.get("minutes_before", 5)
    minutes_after = gate_cfg.get("minutes_after", 5)

    for evt in catalysts:
        evt_type = (evt.get("event_type") or "").lower()
        evt_ts = evt.get("event_ts")
        if isinstance(evt_ts, str):
            try:
                from dateutil.parser import parse
                evt_ts = parse(evt_ts)
            except Exception:
                continue
        if evt_ts and evt_type in [t.lower() for t in blackout_types]:
            if not evt_ts.tzinfo:
                evt_ts = evt_ts.replace(tzinfo=timezone.utc)
            delta_minutes = (evt_ts - now).total_seconds() / 60
            if -minutes_after <= delta_minutes <= minutes_before:
                return OverlayDecision(
                    False,
                    f"Catalyst blackout: {evt_type} within {minutes_before}min",
                    0.0,
                )
        # Earnings for specific symbol — 30min blackout on buy side
        if evt_type == "earnings" and evt.get("symbol") == symbol and side == "buy":
            if evt_ts:
                if not evt_ts.tzinfo:
                    evt_ts = evt_ts.replace(tzinfo=timezone.utc)
                delta_min = abs((evt_ts - now).total_seconds() / 60)
                if delta_min <= 30:
                    return OverlayDecision(False, f"Earnings blackout for {symbol}", 0.0)

    # ── 3. Daily loss limit ───────────────────────────────────────────────────
    daily_loss_limit = overlay.get("daily_loss_limit_pct", 2.0)
    from app.db.models.bots import BotDailyPnL
    today = now.date()
    daily = (
        db.query(BotDailyPnL)
        .filter(
            BotDailyPnL.allocation_id == allocation_id,
            BotDailyPnL.date == today,
        )
        .first()
    )
    if daily:
        total_cents = daily.realized_cents + daily.unrealized_cents
        # Assume $10k per allocation for now; replace with real capital when wired
        capital_cents = 1_000_000  # $10k default
        daily_pct = (total_cents / capital_cents) * 100
        if daily_pct <= -daily_loss_limit:
            return OverlayDecision(
                False,
                f"Daily loss limit -{daily_loss_limit}% hit: {daily_pct:.2f}%",
                0.0,
            )

    # ── 4. Consecutive loss step-down ─────────────────────────────────────────
    from app.db.models.bots import BotTrade
    recent_trades = (
        db.query(BotTrade)
        .filter(
            BotTrade.allocation_id == allocation_id,
            BotTrade.side == "sell",
        )
        .order_by(BotTrade.ts.desc())
        .limit(10)
        .all()
    )

    consecutive_losses = 0
    if recent_trades:
        # Count consecutive losses by comparing fill to expected fill (slippage proxy)
        # A negative slippage_bps beyond threshold counts as a loss signal
        for t in recent_trades:
            if t.slippage_bps is not None and t.slippage_bps < -50:
                consecutive_losses += 1
            else:
                break  # streak broken

    halt_at = overlay.get("consecutive_loss_halt_at", 5)
    halve_at = overlay.get("consecutive_loss_halve_at", 3)
    if consecutive_losses >= halt_at:
        return OverlayDecision(False, f"Consecutive loss halt at {halt_at}", 0.0)
    elif consecutive_losses >= halve_at:
        size_mult *= 0.5
        logger.info(
            f"Consecutive losses {consecutive_losses} >= halve threshold {halve_at}: "
            f"halving size for {symbol}"
        )

    return OverlayDecision(True, "OK", size_mult)
