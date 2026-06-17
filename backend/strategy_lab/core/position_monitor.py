"""Position monitor — runs every minute.

Checks all open BotPosition rows against their stop_price_usd / target_price_usd.
Closes positions that hit stop or target, records the exit trade, and handles
trailing-stop activation (ratchets stop to entry once position is up X%).

Steps 5–8 from the risk pipeline spec:
  5. Monitor loop checks every minute: did stop hit? did target hit?
  6. If stop hit → exit and record loss
  7. If target hit → exit and record gain
  8. If trailing stop activates (position up >= activate_pct) →
       stop ratchets up to breakeven (locks in scratch at worst)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# How many cents capital to treat as "zero" to skip sizing
_MIN_CAPITAL_CENTS = 1_00  # $1


def _get_current_prices(symbols: list[str], asset_class: str) -> dict[str, float]:
    """Fetch current prices from Alpaca paper for a list of symbols."""
    try:
        from strategy_lab.core.execution import get_broker
        broker = get_broker(asset_class)
        positions = broker.get_positions()
        prices = {p["symbol"]: p["current_price"] for p in positions if p.get("current_price")}
        return prices
    except Exception as exc:
        logger.warning("[monitor] broker.get_positions failed (%s): %s", asset_class, exc)
        return {}


def _fetch_latest_prices_fallback(symbols: list[str]) -> dict[str, float]:
    """Fallback: fetch live prices via Kraken (crypto) or Alpaca (stocks).

    yfinance is intentionally NOT used here — it returns stale/delayed data
    that has caused incorrect exit prices in production (e.g. ETH at $1,596
    when the real price was $2,500+).
    """
    try:
        from app.services.live_prices import fetch_live_prices
        return fetch_live_prices(symbols)
    except Exception as exc:
        logger.warning("[monitor] live_prices fallback failed: %s", exc)
        return {}


def _close_position(db, pos, alloc, price_usd: float, reason: str, now: datetime) -> None:
    """Record exit trade and mark position closed."""
    from app.db.models.bots import BotTrade, BotSignal

    is_short = getattr(pos, "side", "long") == "short"
    fill_cents = price_usd * 100  # float — preserves sub-penny precision

    # Log exit signal so health checker sees recent bot activity; capture id for trade FK.
    # Uses begin_nested() (savepoint) so a flush failure never corrupts the outer transaction.
    _exit_signal_id: int | None = None
    _exit_signal_dict: dict | None = None
    try:
        with db.begin_nested():
            _exit_sig = BotSignal(
                allocation_id=alloc.id,
                ts=now,
                symbol=pos.symbol,
                side="cover" if is_short else "sell",
                confidence=1.0,
                reason=reason,
                entry_price=price_usd,
            )
            db.add(_exit_sig)
            db.flush()
            _exit_signal_id = _exit_sig.id
        # Build signal dict for Discord AFTER savepoint commits (id is stable now)
        from app.db.models.bots import BotProfile
        _prof = db.get(BotProfile, alloc.profile_id)
        _exit_signal_dict = {
            "bot":        _prof.name if _prof else "unknown",
            "symbol":     pos.symbol,
            "side":       "cover" if is_short else "sell",
            "confidence": 1.0,
            "reason":     reason,
            "fill_price": price_usd,
            "ts":         now.isoformat(),
        }
    except Exception as _sig_exc:
        logger.warning("[monitor] exit signal log failed for %s: %s", pos.symbol, _sig_exc)

    exit_trade = BotTrade(
        allocation_id=alloc.id,
        symbol=pos.symbol,
        side="cover" if is_short else "sell",  # cover = buy-to-close for shorts
        qty=pos.qty,
        fill_price_cents=fill_cents,
        fees_cents=0,
        ts=now,
        position_id=pos.id,
        signal_id=_exit_signal_id,
        is_paper=True,
        expected_fill_cents=fill_cents,
        slippage_bps=0.0,
    )
    db.add(exit_trade)

    pos.closed_at = now
    pos.exit_reason = reason
    db.commit()

    # Fire Discord embed for exit signal — must be AFTER commit so signal row is visible
    if _exit_signal_id is not None and _exit_signal_dict is not None:
        try:
            import threading
            from strategy_lab.core.audit import _post_signal_to_discord
            threading.Thread(
                target=_post_signal_to_discord,
                args=(_exit_signal_id, _exit_signal_dict),
                daemon=True,
            ).start()
        except Exception as _disc_exc:
            logger.debug("[monitor] exit discord post skipped for %s: %s", pos.symbol, _disc_exc)

    entry_usd = pos.avg_cost_cents / 100.0
    pnl = (entry_usd - price_usd) * pos.qty if is_short else (price_usd - entry_usd) * pos.qty
    logger.info(
        "[monitor] CLOSED %s qty=%.6f entry=%.4f exit=%.4f pnl=%.2f reason=%s pos_id=%d",
        pos.symbol, pos.qty, entry_usd, price_usd, pnl, reason, pos.id,
    )

    # Update daily P&L snapshot
    try:
        from app.db.models.bots import BotDailyPnL
        from datetime import date
        today = date.today()
        pnl_row = (
            db.query(BotDailyPnL)
            .filter(BotDailyPnL.allocation_id == alloc.id, BotDailyPnL.date == today)
            .first()
        )
        pnl_cents = int(pnl * 100)
        if pnl_row:
            pnl_row.realized_cents = (pnl_row.realized_cents or 0) + pnl_cents
        else:
            db.add(BotDailyPnL(
                allocation_id=alloc.id,
                date=today,
                realized_cents=pnl_cents,
                unrealized_cents=0,
                fees_cents=0,
            ))
        db.commit()
    except Exception as exc:
        logger.warning("[monitor] daily_pnl update failed: %s", exc)


def run_position_monitor() -> dict:
    """Main entry point — called by APScheduler every minute.

    Returns a summary dict for logging.
    """
    from app.db.session import SessionLocal
    from app.db.models.bots import BotPosition, BotAllocation, BotProfile

    db = SessionLocal()
    checked = closed_stop = closed_target = trailing_activated = closed_time = 0

    try:
        # Load all open positions that have stop or target set
        open_positions = (
            db.query(BotPosition)
            .filter(BotPosition.closed_at.is_(None))
            .all()
        )

        if not open_positions:
            return {"checked": 0, "closed": 0}

        # Group by asset class to minimize broker calls
        crypto_syms: list[str] = []
        stock_syms: list[str] = []
        for pos in open_positions:
            if "/" in pos.symbol:
                crypto_syms.append(pos.symbol)
            else:
                stock_syms.append(pos.symbol)

        # Fetch prices
        price_map: dict[str, float] = {}
        if crypto_syms:
            crypto_prices = _get_current_prices(list(set(crypto_syms)), "crypto")
            price_map.update(crypto_prices)
            # Fallback for any missing
            missing = [s for s in set(crypto_syms) if s not in price_map]
            if missing:
                price_map.update(_fetch_latest_prices_fallback(missing))
        if stock_syms:
            stock_prices = _get_current_prices(list(set(stock_syms)), "stock")
            price_map.update(stock_prices)

        now = datetime.now(timezone.utc)

        for pos in open_positions:
            current_price = price_map.get(pos.symbol)
            if current_price is None or current_price <= 0:
                continue

            checked += 1
            is_short = getattr(pos, "side", "long") == "short"
            entry_usd = pos.avg_cost_cents / 100.0
            alloc = db.get(BotAllocation, pos.allocation_id)
            if not alloc:
                continue

            profile = db.get(BotProfile, alloc.profile_id)
            profile_cfg = profile.config_json or {} if profile else {}
            activate_pct = float(profile_cfg.get("trailing_stop_activate_at_pct", 20.0))

            # ── Hold-time checks (min and max): must run BEFORE stop/target ─────
            if pos.opened_at is not None:
                opened_aware = (
                    pos.opened_at.replace(tzinfo=timezone.utc)
                    if pos.opened_at.tzinfo is None
                    else pos.opened_at
                )
                held_hours = (now - opened_aware).total_seconds() / 3_600.0

                # FIX F: hold_min_days — skip ALL exits until minimum hold met
                hold_min_days = profile_cfg.get("hold_min_days")
                if hold_min_days is not None and float(hold_min_days) > 0:
                    min_hours = float(hold_min_days) * 24.0
                    if held_hours < min_hours:
                        logger.debug(
                            "[monitor] %s pos=%d held=%.1fh < min=%.1fh — skipping exits",
                            pos.symbol, pos.id, held_hours, min_hours,
                        )
                        continue

                # hold_max_hours / hold_max_days force-exit
                max_hours: Optional[float] = None
                if profile_cfg.get("hold_max_hours") is not None:
                    max_hours = float(profile_cfg["hold_max_hours"])
                elif profile_cfg.get("hold_max_days") is not None:
                    max_hours = float(profile_cfg["hold_max_days"]) * 24.0
                if max_hours is not None and held_hours >= max_hours:
                    _close_position(db, pos, alloc, current_price, "hold_max_hours_force_exit", now)
                    closed_time += 1
                    continue

            # ── Trailing stop (longs only for now) ────────────────────────────────
            if (
                not is_short
                and not pos.trailing_stop_activated
                and entry_usd > 0
                and current_price >= entry_usd * (1 + activate_pct / 100)
            ):
                # Ratchet stop to entry (breakeven) — never lose money on this position
                new_stop = entry_usd
                if pos.stop_price_usd is None or new_stop > pos.stop_price_usd:
                    pos.stop_price_usd = new_stop
                    pos.trailing_stop_activated = True
                    pos.trailing_stop_price_usd = new_stop
                    db.commit()
                    trailing_activated += 1
                    logger.info(
                        "[monitor] Trailing stop activated on %s: stop ratcheted to entry %.4f (was None)",
                        pos.symbol, new_stop,
                    )

            # ── Stop loss check (direction-aware) ────────────────────────────────
            if pos.stop_price_usd is not None:
                # Short: stop is above entry — hit when price rises above it
                # Long:  stop is below entry — hit when price falls below it
                stop_hit = (
                    current_price >= pos.stop_price_usd if is_short
                    else current_price <= pos.stop_price_usd
                )
                if stop_hit:
                    _close_position(db, pos, alloc, current_price, "stop_loss", now)
                    closed_stop += 1
                    continue

            # ── Take profit check (direction-aware) ──────────────────────────────
            if pos.target_price_usd is not None:
                # Short: target is below entry — profit when price falls below it
                # Long:  target is above entry — profit when price rises above it
                target_hit = (
                    current_price <= pos.target_price_usd if is_short
                    else current_price >= pos.target_price_usd
                )
                if target_hit:
                    _close_position(db, pos, alloc, current_price, "take_profit", now)
                    closed_target += 1
                    continue

    except Exception as exc:
        logger.error("[monitor] position_monitor error: %s", exc, exc_info=True)
    finally:
        db.close()

    total_closed = closed_stop + closed_target + closed_time
    if total_closed or trailing_activated:
        logger.info(
            "[monitor] Run complete: checked=%d stop_exits=%d target_exits=%d time_exits=%d trailing_activated=%d",
            checked, closed_stop, closed_target, closed_time, trailing_activated,
        )
    return {
        "checked": checked,
        "closed_stop": closed_stop,
        "closed_target": closed_target,
        "closed_time": closed_time,
        "trailing_activated": trailing_activated,
    }


def monitor_bot_positions(bot_name: str) -> dict:
    """Per-bot intraday monitor for stock_day and stock_swing.

    Runs every 5 min during market hours. Layers on top of the global
    run_position_monitor() to add:
      - Trailing stop ratchet (risk_management config)
      - ensure_stop_exists (catches any position that slipped through entry)
      - Drawdown circuit breaker (bot-level, configurable via YAML)
    """
    from app.db.session import SessionLocal
    from app.db.models.bots import BotPosition, BotAllocation, BotProfile
    from strategy_lab.core.stop_management import ratchet_trailing_stop, ensure_stop_exists

    stats: dict = {
        "bot": bot_name, "checked": 0, "ratcheted": 0,
        "stopped": 0, "circuit_breaker": False,
    }
    db = SessionLocal()
    try:
        profile = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
        if not profile:
            return stats
        cfg = profile.config_json or {}
        rm = cfg.get("risk_management", {})

        ratchet_pct = float(rm.get("trailing_stop_ratchet_pct", 10.0))
        min_pct = float(rm.get("trailing_stop_min_pct", 7.0))
        stop_pct = float(rm.get("stop_loss_pct", 7.0))
        cb_pct = float(rm.get("drawdown_circuit_breaker_pct", 30.0))

        open_positions = (
            db.query(BotPosition)
            .join(BotAllocation, BotPosition.allocation_id == BotAllocation.id)
            .filter(
                BotAllocation.profile_id == profile.id,
                BotPosition.closed_at.is_(None),
                BotPosition.quarantined_at.is_(None),
            )
            .all()
        )

        if not open_positions:
            return stats

        symbols = list({p.symbol for p in open_positions})
        price_map: dict[str, float] = _fetch_latest_prices_fallback(symbols)
        if not price_map:
            price_map = _get_current_prices(symbols, cfg.get("asset_class", "stock"))

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        # ── Drawdown circuit breaker ──────────────────────────────────────────
        total_cost = sum((p.avg_cost_cents / 100.0) * p.qty for p in open_positions)
        total_current = sum(
            price_map.get(p.symbol, p.avg_cost_cents / 100.0) * p.qty
            for p in open_positions
        )
        if total_cost > 0:
            dd_pct = (total_cost - total_current) / total_cost * 100
            if dd_pct >= cb_pct:
                logger.warning(
                    "[monitor:%s] CIRCUIT BREAKER triggered: drawdown=%.1f%% >= limit=%.1f%%",
                    bot_name, dd_pct, cb_pct,
                )
                stats["circuit_breaker"] = True
                for pos in open_positions:
                    alloc = db.get(BotAllocation, pos.allocation_id)
                    if not alloc:
                        continue
                    exit_price = price_map.get(pos.symbol, pos.avg_cost_cents / 100.0)
                    _close_position(db, pos, alloc, exit_price, "drawdown_circuit_breaker", now)
                    stats["stopped"] += 1
                return stats

        # ── Per-position: ensure stop + ratchet ──────────────────────────────
        for pos in open_positions:
            current_price = price_map.get(pos.symbol)
            if not current_price or current_price <= 0:
                continue

            entry_price = pos.avg_cost_cents / 100.0
            stats["checked"] += 1

            ensure_stop_exists(db, pos.id, entry_price, stop_pct)

            result = ratchet_trailing_stop(
                db, pos.id, current_price, entry_price,
                min_pct=min_pct, ratchet_pct=ratchet_pct,
            )
            if result == "ratcheted":
                stats["ratcheted"] += 1

        if stats["checked"] or stats["ratcheted"] or stats["stopped"]:
            logger.info(
                "[monitor:%s] checked=%d ratcheted=%d stopped=%d circuit_breaker=%s",
                bot_name, stats["checked"], stats["ratcheted"],
                stats["stopped"], stats["circuit_breaker"],
            )

    except Exception as exc:
        logger.error("[monitor:%s] monitor_bot_positions error: %s", bot_name, exc, exc_info=True)
    finally:
        db.close()

    return stats
