"""Bot execution runner.

run_bot_profile() is the single entry point called by APScheduler for each
of the six bot profiles.  It:
  1. Loads the YAML profile config.
  2. Fetches all enabled paper-mode allocations for the profile.
  3. Detects market regime (graceful if regime_detector not yet built).
  4. Applies risk overlay gate (graceful if risk_overlay not yet built).
  5. Runs generate_signals() for each strategy module listed in the profile YAML
     (dynamic import by strategy name).
  6. Applies ensemble vote: weighted_vote | majority_vote | factor_rank.
  7. Audits non-hold signals to bot_signals.
  8. Persists audit record including regime snapshot JSON.
  9. Returns a summary dict.
"""
from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── Ensemble helpers ──────────────────────────────────────────────────────────

def _weighted_vote(signals_by_strategy: list[list]) -> list:
    """Average confidence for each symbol/side combination across strategies.

    A symbol/side pair wins if its weighted-average confidence >= 0.5.
    Returns a deduplicated list of winning signals (highest confidence wins
    when multiple strategies agree on a symbol).
    """
    from strategy_lab.core.signals import Signal

    # Aggregate by (symbol, side)
    agg: dict[tuple[str, str], list[float]] = {}
    signal_map: dict[tuple[str, str], Any] = {}
    for strategy_signals in signals_by_strategy:
        for sig in strategy_signals:
            key = (sig.symbol, sig.side)
            agg.setdefault(key, []).append(sig.confidence)
            # Keep signal with highest individual confidence as template
            if key not in signal_map or sig.confidence > signal_map[key].confidence:
                signal_map[key] = sig

    winners = []
    for key, confs in agg.items():
        avg_conf = sum(confs) / len(confs)
        if avg_conf >= 0.5:
            template = signal_map[key]
            # Clone with averaged confidence
            winners.append(Signal(
                symbol=template.symbol,
                side=template.side,
                confidence=round(avg_conf, 4),
                size_hint=template.size_hint,
                reason=f"[ensemble:weighted_vote x{len(confs)}] {template.reason}",
                strategy=template.strategy,
            ))
    return winners


def _majority_vote(signals_by_strategy: list[list], n_strategies: int) -> list:
    """Return signals where >50% of strategies agree on the same symbol/side."""
    from strategy_lab.core.signals import Signal

    counts: dict[tuple[str, str], int] = {}
    best: dict[tuple[str, str], Any] = {}
    for strategy_signals in signals_by_strategy:
        seen = set()  # each strategy votes once per symbol/side
        for sig in strategy_signals:
            key = (sig.symbol, sig.side)
            if key not in seen:
                counts[key] = counts.get(key, 0) + 1
                seen.add(key)
            if key not in best or sig.confidence > best[key].confidence:
                best[key] = sig

    threshold = n_strategies / 2
    winners = []
    for key, count in counts.items():
        if count > threshold:
            template = best[key]
            winners.append(Signal(
                symbol=template.symbol,
                side=template.side,
                confidence=template.confidence,
                size_hint=template.size_hint,
                reason=f"[ensemble:majority_vote {count}/{n_strategies}] {template.reason}",
                strategy=template.strategy,
            ))
    return winners


def _factor_rank(signals_by_strategy: list[list]) -> list:
    """Sort all signals by composite confidence score and return top-ranked."""
    all_signals = [sig for strat_sigs in signals_by_strategy for sig in strat_sigs]
    if not all_signals:
        return []
    # Deduplicate by symbol — keep highest-confidence signal per symbol
    seen_symbols: dict[str, Any] = {}
    for sig in sorted(all_signals, key=lambda s: s.confidence, reverse=True):
        if sig.symbol not in seen_symbols:
            seen_symbols[sig.symbol] = sig
    ranked = list(seen_symbols.values())
    # Annotate reason
    for sig in ranked:
        sig.reason = f"[ensemble:factor_rank] {sig.reason}"
    return ranked


def _apply_ensemble(
    ensemble: str,
    signals_by_strategy: list[list],
    n_strategies: int,
) -> list:
    """Dispatch to the appropriate ensemble aggregator."""
    if ensemble == "weighted_vote":
        return _weighted_vote(signals_by_strategy)
    if ensemble == "majority_vote":
        return _majority_vote(signals_by_strategy, n_strategies)
    if ensemble == "factor_rank":
        return _factor_rank(signals_by_strategy)
    # Unknown ensemble — fall back to flat merge
    logger.warning("Unknown ensemble '%s', falling back to flat merge", ensemble)
    return [sig for strat_sigs in signals_by_strategy for sig in strat_sigs]


# ── Strategy dynamic importer ─────────────────────────────────────────────────

def _load_strategy_module(strategy_name: str):
    """Dynamically import a strategy module by name.

    Looks first in strategy_lab.strategies.<name>, then tries a bare import.
    Returns the module, or None if not found.
    """
    for module_path in (
        f"strategy_lab.strategies.{strategy_name}",
        strategy_name,
    ):
        try:
            return importlib.import_module(module_path)
        except ImportError:
            continue
    logger.warning("Strategy module '%s' not found", strategy_name)
    return None


# ── Main runner ───────────────────────────────────────────────────────────────

def run_bot_profile(profile_name: str) -> dict:
    """Execute one bot profile: fetch bars, run strategies, risk check, paper execute, audit.

    Args:
        profile_name: One of stock_swing, stock_day, stock_lt,
                      crypto_swing, crypto_day, crypto_lt.

    Returns:
        Summary dict with keys: profile, allocations, signals, ts, regime_snapshot.
        On skip: {"skipped": True, "reason": str}.
        On error: {"error": str}.
    """
    logger.info(">>> [runner:%s] scan cycle START", profile_name)
    try:
        # 1. Load profile YAML
        from strategy_lab.seeds import load_profile
        profile = load_profile(profile_name)

        # 2. Get all enabled allocations for this profile
        from app.db.session import SessionLocal
        from app.db.models.bots import BotProfile, BotAllocation

        db = SessionLocal()
        try:
            bp = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
            if not bp or not bp.enabled:
                return {"skipped": True, "reason": "profile disabled or not found"}

            allocations = (
                db.query(BotAllocation)
                .filter(
                    BotAllocation.profile_id == bp.id,
                    BotAllocation.enabled.is_(True),
                    BotAllocation.paper_mode.is_(True),
                )
                .all()
            )
            if not allocations:
                return {"skipped": True, "reason": "no enabled paper allocations"}

            # 3. Detect regime (graceful — may not be built yet)
            regime: dict = {}
            try:
                from strategy_lab.core.regime_detector import detect_regime  # type: ignore
                regime = detect_regime(profile_name, profile) or {}
                logger.debug("[runner:%s] Regime: %s", profile_name, regime)
            except (ImportError, Exception) as exc:
                logger.debug("[runner:%s] regime_detector unavailable: %s", profile_name, exc)

            # 4. Check catalyst calendar (graceful — may not be built yet)
            catalyst_ok = True
            try:
                from strategy_lab.core.catalyst_calendar import should_trade  # type: ignore
                catalyst_ok = should_trade(profile_name, profile, regime)
            except (ImportError, Exception) as exc:
                logger.debug("[runner:%s] catalyst_calendar unavailable: %s", profile_name, exc)

            if not catalyst_ok:
                return {"skipped": True, "reason": "catalyst_calendar halted trading"}

            # 5. Check regime filters from profile YAML
            regime_filters = profile.get("regime_filters", []) or []
            for f in regime_filters:
                halt_condition = f.get("halt_if", "")
                if _evaluate_regime_filter(halt_condition, regime):
                    logger.info("[runner:%s] Regime filter halt: %s", profile_name, halt_condition)
                    return {"skipped": True, "reason": f"regime_filter: {halt_condition}"}

            # 6. Fetch OHLCV bars from exchange-native feeds
            asset_class = profile.get("asset_class", "stock")
            universe = profile.get("universe", {})
            symbols: list[str] = (
                universe.get("symbols", []) if isinstance(universe, dict)
                else list(universe) if universe else []
            )
            timeframe = profile.get("scan_timeframe", "1h")
            limit = int(profile.get("scan_lookback_bars", 200))

            bars: dict[str, list[dict]] = {}
            if symbols:
                try:
                    if asset_class in ("crypto", "crypto_intraday"):
                        from app.screener.crypto_runner import _fetch_crypto_bars
                        raw_bars = _fetch_crypto_bars(symbols, timeframe=timeframe, limit=limit)
                    else:
                        from app.screener.runner import _fetch_bars_sync
                        raw_bars = _fetch_bars_sync(symbols, period="60d")
                    for sym, df in raw_bars.items():
                        if df is None or df.empty:
                            continue
                        bars[sym] = [
                            {
                                "c": float(row["close"]),
                                "o": float(row["open"]),
                                "h": float(row["high"]),
                                "l": float(row["low"]),
                                "v": float(row.get("volume", 0) or 0),
                                "ts": (row.name.isoformat()
                                       if hasattr(row.name, "isoformat")
                                       else str(row.name)),
                            }
                            for _, row in df.iterrows()
                        ]
                    logger.info(
                        "[runner:%s] fetched bars for %d/%d symbols",
                        profile_name, len(bars), len(symbols),
                    )
                except Exception as exc:
                    logger.warning("[runner:%s] bar fetch failed: %s", profile_name, exc)

            # 7. Run generate_signals for each strategy module in profile
            #    Strategy signals are weighted by Thompson-sampled strategy_weights.
            strategy_names: list[str] = profile.get("strategies", [])
            if not strategy_names:
                strategy_names = [_primary_strategy(profile_name)]

            # 7a. Load Thompson-sampled strategy weights (graceful)
            strategy_weight_map: dict[str, float] = {}
            try:
                from strategy_lab.core.expert.strategy_weights import get_weights
                for alloc in allocations:
                    strategy_weight_map = get_weights(alloc.profile_id, strategy_names, db)
                    break  # same profile → same weights
                logger.debug("[runner:%s] Strategy weights: %s", profile_name, strategy_weight_map)
            except Exception as exc:
                logger.warning("[runner:%s] strategy_weights unavailable: %s", profile_name, exc)

            signals_by_strategy: list[list] = []
            strategies_loaded = 0

            for strat_name in strategy_names:
                mod = _load_strategy_module(strat_name)
                if mod is None:
                    continue
                if not hasattr(mod, "generate_signals"):
                    logger.warning("[runner:%s] Strategy '%s' has no generate_signals()", profile_name, strat_name)
                    continue
                try:
                    strat_signals = mod.generate_signals(bars, profile, regime)
                    # Apply strategy weight as confidence multiplier
                    weight = strategy_weight_map.get(strat_name, 1.0)
                    if weight != 1.0 and strat_signals:
                        from strategy_lab.core.signals import Signal
                        strat_signals = [
                            Signal(
                                symbol=s.symbol,
                                side=s.side,
                                confidence=min(1.0, s.confidence * weight),
                                size_hint=s.size_hint,
                                reason=f"[w={weight:.3f}] {s.reason}",
                                strategy=s.strategy,
                            )
                            for s in strat_signals
                        ]
                    signals_by_strategy.append(strat_signals or [])
                    strategies_loaded += 1
                    logger.info(
                        "[runner:%s] strategy %s → %d signals",
                        profile_name, strat_name, len(strat_signals or []),
                    )
                except Exception as exc:
                    logger.error(
                        "[runner:%s] Strategy '%s' raised: %s",
                        profile_name, strat_name, exc, exc_info=True,
                    )
                    signals_by_strategy.append([])

            # When no strategies produced signals, proceed with empty list (no stub hold).
            # Strategies return [] when bars are empty or no entry conditions are met — both are
            # normal operating states, not errors.
            if not any(signals_by_strategy):
                logger.info(
                    "[runner:%s] %d strategies evaluated, 0 entry conditions met — skipping cycle",
                    profile_name, strategies_loaded,
                )
                # No-op: signals_by_strategy stays as-is (list of empty lists)

            # 8. Apply ensemble vote
            ensemble = profile.get("ensemble", "weighted_vote")
            signals = _apply_ensemble(ensemble, signals_by_strategy, max(1, strategies_loaded))
            logger.info(
                "[runner:%s] after ensemble (%s): %d signals",
                profile_name, ensemble, len(signals),
            )

            # 8a. Multi-timeframe confluence filter (graceful)
            bot_cadence = _cadence_for_profile(profile_name)
            filtered_signals = []
            for sig in signals:
                if sig.side == "hold":
                    filtered_signals.append(sig)
                    continue
                try:
                    from strategy_lab.core.expert.multi_timeframe import check_confluence
                    score = check_confluence(sig.symbol, sig, bars, bot_cadence)
                    if score >= 0.66:
                        filtered_signals.append(sig)
                        logger.info(
                            "[runner:%s] MTF %s %s: score=%.2f PASS",
                            profile_name, sig.symbol, sig.side, score,
                        )
                    else:
                        logger.info(
                            "[runner:%s] MTF %s %s: score=%.2f SKIP",
                            profile_name, sig.symbol, sig.side, score,
                        )
                except Exception as exc:
                    logger.warning("[runner:%s] multi_timeframe failed for %s: %s", profile_name, sig.symbol, exc)
                    filtered_signals.append(sig)  # degrade gracefully
            signals = filtered_signals
            logger.info(
                "[runner:%s] after MTF confluence: %d signals",
                profile_name, len(signals),
            )

            # 9. Apply risk overlay (graceful — may not be built yet)
            pre_overlay_count = len(signals)
            try:
                from strategy_lab.core.risk_overlay import apply_overlay  # type: ignore
                signals = apply_overlay(signals, profile, regime, db) or signals
            except (ImportError, Exception) as exc:
                logger.debug("[runner:%s] risk_overlay unavailable: %s", profile_name, exc)
            logger.info(
                "[runner:%s] after risk_overlay: %d signals (was %d)",
                profile_name, len(signals), pre_overlay_count,
            )

            # 10. Expert decision layer: per-signal processing for actionable signals
            from strategy_lab.core.audit import log_signal

            actionable = [s for s in signals if s.side != "hold"]
            logger.info(
                "[runner:%s] actionable signals: %d", profile_name, len(actionable),
            )
            processed_signals = []

            for alloc in allocations:
                alloc_user_id = alloc.user_id

                # ── FIX B: Daily-loss guardrail check ────────────────────────────
                try:
                    from app.services.guardrail_checker import check_guardrails
                    ok, reason = check_guardrails(alloc.user_id, db)
                    if not ok:
                        logger.warning(
                            "[runner:%s][guardrail] skipping alloc %d user %d: %s",
                            profile_name, alloc.id, alloc.user_id, reason,
                        )
                        continue
                except Exception as exc:
                    logger.warning("[runner:%s] guardrail_checker failed: %s", profile_name, exc)

                # Gather open positions for position_cap + exposure + correlation
                open_pos_rows: list = []
                open_symbols: list[str] = []
                try:
                    from app.db.models.bots import BotPosition
                    open_pos_rows = (
                        db.query(BotPosition)
                        .filter(
                            BotPosition.allocation_id == alloc.id,
                            BotPosition.closed_at.is_(None),
                        )
                        .all()
                    )
                    open_symbols = [p.symbol for p in open_pos_rows]
                except Exception as exc:
                    logger.warning("[runner:%s] Could not fetch open positions: %s", profile_name, exc)

                # ── FIX D: position_cap enforcement ──────────────────────────────
                position_cap = int(profile.get("position_cap", 999))
                if len(open_pos_rows) >= position_cap:
                    logger.info(
                        "[runner:%s][position_cap] skipping alloc %d: %d/%d positions held",
                        profile_name, alloc.id, len(open_pos_rows), position_cap,
                    )
                    continue

                # ── FIX E: max_gross_exposure_pct enforcement ─────────────────────
                try:
                    risk_overlay_cfg = profile.get("risk_overlay", {})
                    max_gross_pct = float(risk_overlay_cfg.get("max_gross_exposure_pct", 100.0))
                    cap_cents = alloc.starting_capital_cents or alloc.capital_cents_within_portfolio or 0
                    if cap_cents > 0 and open_pos_rows:
                        open_notional_cents = sum(
                            int(p.qty * p.avg_cost_cents) for p in open_pos_rows
                        )
                        gross_pct = (open_notional_cents / cap_cents) * 100
                        if gross_pct >= max_gross_pct:
                            logger.info(
                                "[runner:%s][exposure_cap] skipping alloc %d: %.1f%%/%.1f%% gross exposure",
                                profile_name, alloc.id, gross_pct, max_gross_pct,
                            )
                            continue
                except Exception as exc:
                    logger.warning("[runner:%s] exposure_cap check failed: %s", profile_name, exc)

                for sig in actionable:
                    if sig.side == "hold":
                        continue

                    symbol_bars = bars.get(sig.symbol, [])

                    # 10a. Anomaly detector — halt on abnormal conditions
                    try:
                        from strategy_lab.core.expert.anomaly_detector import check_for_anomaly
                        anomaly = check_for_anomaly(sig.symbol, symbol_bars, alloc.id, db)
                        if anomaly.get("halt"):
                            logger.warning(
                                "[runner:%s] Anomaly halt for %s: %s",
                                profile_name, sig.symbol, anomaly.get("anomaly_type"),
                            )
                            continue  # skip this signal
                    except Exception as exc:
                        logger.warning("[runner:%s] anomaly_detector failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10b. News entry block check
                    try:
                        from strategy_lab.core.expert.news_stop_adjuster import should_block_new_entries
                        if should_block_new_entries(sig.symbol, db):
                            logger.info(
                                "[runner:%s] News block on new entry: %s", profile_name, sig.symbol
                            )
                            continue
                    except Exception as exc:
                        logger.warning("[runner:%s] news_stop_adjuster failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10c. Cross-bot conflict resolution
                    adjusted_size_pct = sig.size_hint * 100  # convert 0-1 hint to pct
                    try:
                        from strategy_lab.core.expert.bot_coordinator import check_conflicts
                        coord_result = check_conflicts(
                            alloc_user_id, sig.symbol, profile_name,
                            sig.side, adjusted_size_pct, db,
                        )
                        if not coord_result.get("allowed", True):
                            logger.info(
                                "[runner:%s] Bot coordinator blocked %s: %s",
                                profile_name, sig.symbol, coord_result.get("reason"),
                            )
                            continue
                        adjusted_size_pct = coord_result.get("adjusted_size_pct", adjusted_size_pct)
                    except Exception as exc:
                        logger.warning("[runner:%s] bot_coordinator failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10d. Correlation size adjustment
                    try:
                        from strategy_lab.core.expert.correlation_sizer import adjust_size_for_correlation
                        adjusted_size_pct = adjust_size_for_correlation(
                            sig.symbol, adjusted_size_pct, open_symbols, bars,
                        )
                    except Exception as exc:
                        logger.warning("[runner:%s] correlation_sizer failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10e. Volatility-weighted final sizing
                    try:
                        from strategy_lab.core.expert.vol_weighted_sizing import compute_vol_weighted_size
                        risk_overlay_cfg = profile.get("risk_overlay", {})
                        target_risk = risk_overlay_cfg.get("max_position_risk_pct", 1.0)
                        max_size = risk_overlay_cfg.get("max_position_size_pct", 10.0)
                        vol_size = compute_vol_weighted_size(
                            sig.symbol, symbol_bars,
                            target_risk_pct=target_risk,
                            max_size_pct=max_size,
                        )
                        # Take the smaller of the two sizing methods
                        adjusted_size_pct = min(adjusted_size_pct, vol_size)
                    except Exception as exc:
                        logger.warning("[runner:%s] vol_weighted_sizing failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10f. Smart stop placement
                    stop_info: dict = {}
                    try:
                        from strategy_lab.core.expert.smart_stops import compute_stop
                        # Use a stub entry price (bars[-1].close or 0) since real fills happen in execution
                        entry_price = 0.0
                        if symbol_bars:
                            last_bar = symbol_bars[-1]
                            entry_price = float(last_bar.get("c") or last_bar.get("close") or 0)
                        if entry_price > 0:
                            stop_info = compute_stop(sig.symbol, sig.side, entry_price, symbol_bars)
                    except Exception as exc:
                        logger.warning("[runner:%s] smart_stops failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10g. Pyramid: enter at 50% of adjusted size
                    final_size_pct = adjusted_size_pct
                    try:
                        from strategy_lab.core.expert.position_pyramid import initial_size_pct
                        final_size_pct = initial_size_pct(adjusted_size_pct)
                    except Exception as exc:
                        logger.warning("[runner:%s] position_pyramid failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10h. Trade journal — write entry rationale
                    why_opened_json = "{}"
                    try:
                        from strategy_lab.core.expert.trade_journal import write_entry_journal
                        confluence_score = 1.0  # already passed confluence gate above
                        why_opened_json = write_entry_journal(
                            sig.symbol, sig, regime, confluence_score, stop_info, profile,
                        )
                    except Exception as exc:
                        logger.warning("[runner:%s] trade_journal failed for %s: %s", profile_name, sig.symbol, exc)

                    # Audit the signal
                    log_signal(db, alloc.id, sig)

                    # 10i. Execute: open position in Alpaca paper + create DB rows
                    try:
                        _execute_signal(
                            db=db,
                            alloc=alloc,
                            sig=sig,
                            final_size_pct=final_size_pct,
                            profile=profile,
                            profile_name=profile_name,
                            bars=bars,
                        )
                    except Exception as exc:
                        logger.warning("[runner:%s] execute_signal failed for %s: %s",
                                       profile_name, sig.symbol, exc)

                    processed_signals.append({
                        "signal": sig,
                        "final_size_pct": final_size_pct,
                        "stop_info": stop_info,
                        "why_opened_json": why_opened_json,
                    })

                    logger.info(
                        "[runner:%s] Signal ACCEPTED: %s %s size=%.2f%% stop=%s",
                        profile_name, sig.side, sig.symbol,
                        final_size_pct, stop_info.get("stop_price", "n/a"),
                    )

                    # Build signal dict for notification dispatch
                    _entry_price = None
                    if bars.get(sig.symbol):
                        _last = bars[sig.symbol][-1]
                        _entry_price = float(_last.get("c") or _last.get("close") or 0) or None
                    _signal_dict = {
                        "bot": profile_name,
                        "symbol": sig.symbol,
                        "side": sig.side,
                        "strategy": sig.strategy or profile_name,
                        "reason": sig.reason or "",
                        "confidence": sig.confidence,
                        "price": _entry_price,
                        "size_pct": final_size_pct,
                        "stop": stop_info.get("stop_price"),
                        "target": stop_info.get("target_price"),
                    }

                    # Private per-user notifications (Discord webhook, Telegram, Slack, Email)
                    try:
                        from app.services.notify import dispatch_signal
                        dispatch_signal(_signal_dict, db)
                    except Exception as _exc:
                        logger.debug("[runner:%s] private notify skipped: %s", profile_name, _exc)

                    # Public Discord signal feed (bot token + channel IDs)
                    try:
                        from app.services.discord_public import post_signal
                        post_signal(_signal_dict)
                    except Exception as _exc:
                        logger.debug("[runner:%s] public discord skipped: %s", profile_name, _exc)

                    # Legacy single-webhook Discord (DISCORD_SIGNAL_WEBHOOK_URL)
                    try:
                        from app.services.discord import send_signal
                        send_signal(
                            bot=profile_name, symbol=sig.symbol, side=sig.side,
                            strategy=sig.strategy or profile_name, reason=sig.reason or "",
                            confidence=sig.confidence, price=_entry_price, size_pct=final_size_pct,
                        )
                    except Exception as _exc:
                        logger.debug("[runner:%s] webhook discord skipped: %s", profile_name, _exc)

                    # One-shot: #announcements alert on the very first real crypto buy signal
                    if profile_name in {"crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain"} and sig.side == "buy":
                        try:
                            _maybe_announce_first_live_signal(
                                db=db,
                                bot_name=profile_name,
                                strategy=sig.strategy or profile_name,
                                symbol=sig.symbol,
                            )
                        except Exception as _exc:
                            logger.debug("[runner:%s] first_live_signal_announcement skipped: %s", profile_name, _exc)

            # Also audit hold signals per allocation (non-expert path)
            hold_signals = [s for s in signals if s.side == "hold"]
            for alloc in allocations:
                for sig in hold_signals:
                    log_signal(db, alloc.id, sig)

            # 11. Build and persist audit record
            regime_snapshot = json.dumps(regime, default=str) if regime else "{}"
            audit_record = {
                "profile": profile_name,
                "strategies_loaded": strategies_loaded,
                "ensemble": ensemble,
                "signals_total": len(signals),
                "signals_actionable": len(actionable),
                "signals_processed": len(processed_signals),
                "regime_snapshot": regime_snapshot,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            logger.info("[runner:%s] Audit: %s", profile_name, audit_record)

            return {
                "profile": profile_name,
                "allocations": len(allocations),
                "signals": len(actionable),
                "signals_processed": len(processed_signals),
                "strategies_loaded": strategies_loaded,
                "ensemble": ensemble,
                "regime_snapshot": regime_snapshot,
                "ts": audit_record["ts"],
            }

        finally:
            db.close()

    except Exception as exc:
        logger.error("Bot runner failed for %s: %s", profile_name, exc, exc_info=True)
        return {"error": str(exc)}


# ── One-shot first-live-signal announcement ───────────────────────────────────

_FIRST_SIGNAL_MIGRATION = "first_live_crypto_signal_announced"


def _maybe_announce_first_live_signal(db, bot_name: str, strategy: str, symbol: str) -> None:
    """Post a one-shot alert to #announcements on the first real crypto buy signal.

    Uses schema_migrations as the claim token — INSERT OR IGNORE + rowcount ensures
    exactly one process fires the announcement even under concurrent runners.
    """
    from sqlalchemy import text

    # Claim the one-shot slot: succeed only if the row doesn't exist yet
    result = db.execute(
        text("INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (:n)"),
        {"n": _FIRST_SIGNAL_MIGRATION},
    )
    db.commit()

    if result.rowcount != 1:
        # Another runner already posted (or the row was pre-existing)
        return

    logger.info(
        "first_live_signal: claimed slot for bot=%s strategy=%s symbol=%s — posting to #announcements",
        bot_name, strategy, symbol,
    )
    from app.services.discord_public import post_first_live_signal_announcement
    post_first_live_signal_announcement(bot_name, strategy, symbol)


# ── Signal execution (Step 4: open position at Alpaca paper) ─────────────────

def _execute_signal(db, alloc, sig, final_size_pct: float, profile: dict, profile_name: str, bars: dict | None = None) -> None:
    """Place a bracket order in Alpaca paper and persist BotPosition + BotTrade.

    Steps:
      1. Get current price from broker account/positions or fallback
      2. Size the position (final_size_pct % of alloc capital)
      3. Compute stop/target from profile YAML rules
      4. Submit bracket order to Alpaca paper
      5. Create BotPosition row (with stop_price_usd + target_price_usd)
      6. Create BotTrade row (entry fill)
    """
    if sig.side not in ("buy",):
        return  # only open long positions for now

    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade
    from strategy_lab.core.execution import get_broker, compute_bracket_prices

    asset_class = profile.get("asset_class", "stock")
    now = datetime.now(timezone.utc)

    # 1. Get current price
    try:
        broker = get_broker(asset_class)
        account = broker.get_account()
        equity = account.get("equity", 0.0)
    except Exception as exc:
        logger.warning("[execute:%s] broker.get_account failed: %s", profile_name, exc)
        return

    if equity <= 0:
        return

    # Fetch live price: Kraken (crypto) or Alpaca IEX (stocks) → fallback broker positions
    entry_price = 0.0
    try:
        from app.services.live_prices import fetch_live_prices
        live_map = fetch_live_prices([sig.symbol])
        entry_price = float(live_map.get(sig.symbol, 0) or 0)
        if entry_price > 0:
            logger.debug("[execute:%s] live price %s = %.4f", profile_name, sig.symbol, entry_price)
    except Exception as exc:
        logger.warning("[execute:%s] live_prices failed for %s: %s", profile_name, sig.symbol, exc)

    if entry_price <= 0:
        try:
            positions = broker.get_positions()
            for p in positions:
                if p.get("symbol") == sig.symbol and p.get("current_price", 0) > 0:
                    entry_price = float(p["current_price"])
                    break
        except Exception:
            pass

    if entry_price <= 0:
        # Last resort: use the bar close the strategy used to generate the signal
        symbol_bars = (bars or {}).get(sig.symbol, [])
        if symbol_bars:
            entry_price = float(symbol_bars[-1]["c"])
            logger.warning(
                "[execute:%s] live price unavailable for %s, using last bar close $%.4f",
                profile_name, sig.symbol, entry_price,
            )

    if entry_price <= 0:
        logger.warning("[execute:%s] no price for %s — skipping order (live=0, broker=0, bars_fallback=0)", profile_name, sig.symbol)
        return

    logger.info("[execute:%s] entry_price=%s=%.4f equity=%.2f", profile_name, sig.symbol, entry_price, equity)

    # 2. Size: pct of bot capital (capital_cents_within_portfolio or starting capital)
    capital_usd = (alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000) / 100.0
    position_dollars = capital_usd * (final_size_pct / 100.0)
    qty = round(position_dollars / entry_price, 6)
    if qty <= 0:
        return

    # 3. Compute stop and target from profile rules
    stop_price, target_price = compute_bracket_prices(entry_price, profile)

    # 4. Submit bracket order
    order_id: str | None = None
    try:
        result = broker.submit_bracket_order(
            symbol=sig.symbol,
            qty=qty,
            side="buy",
            stop_price=stop_price,
            target_price=target_price,
        )
        order_id = result.get("order_id")
    except Exception as exc:
        logger.warning("[execute:%s] bracket_order failed for %s: %s", profile_name, sig.symbol, exc)
        # Fall through — still create DB rows as simulated paper fill

    fill_cents = int(entry_price * 100)

    # 5. Create BotPosition
    pos = BotPosition(
        allocation_id=alloc.id,
        symbol=sig.symbol,
        qty=qty,
        avg_cost_cents=fill_cents,
        opened_at=now,
        closed_at=None,
        is_paper=True,
        stop_price_usd=stop_price,
        target_price_usd=target_price,
        trailing_stop_activated=False,
    )
    db.add(pos)
    db.flush()  # get pos.id

    # 6. Create BotTrade (entry)
    trade = BotTrade(
        allocation_id=alloc.id,
        symbol=sig.symbol,
        side="buy",
        qty=qty,
        fill_price_cents=fill_cents,
        fees_cents=0,
        ts=now,
        position_id=pos.id,
        is_paper=True,
        alpaca_order_id=order_id,
        expected_fill_cents=fill_cents,
        slippage_bps=0.0,
    )
    db.add(trade)
    db.commit()

    logger.info(
        "[execute:%s] Opened %s qty=%.6f @ %.4f stop=%.4f target=%.4f order=%s pos=%d trade=%d",
        profile_name, sig.symbol, qty, entry_price, stop_price, target_price,
        order_id or "sim", pos.id, trade.id,
    )


# ── Regime filter evaluator ───────────────────────────────────────────────────

def _evaluate_regime_filter(condition: str, regime: dict) -> bool:
    """Safely evaluate a simple regime filter expression.

    Supports expressions like: "btc_funding_rate > 0.002"
    Returns True if the halt condition is met.
    """
    if not condition:
        return False
    try:
        # Allow only regime dict keys as names — no arbitrary code execution
        allowed_vars = {k: v for k, v in regime.items() if isinstance(k, str)}
        return bool(eval(condition, {"__builtins__": {}}, allowed_vars))  # noqa: S307
    except Exception as exc:
        logger.debug("Could not evaluate regime filter '%s': %s", condition, exc)
        return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _default_symbol_for_profile(profile_name: str, profile: dict) -> str:
    """Pick a default symbol from the profile config, or a sensible fallback."""
    universe = profile.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", [])
    else:
        symbols = profile.get("symbols") or profile.get("universe") or []
    if symbols:
        return symbols[0]
    _defaults = {
        "stock_swing": "SPY",
        "stock_day": "SPY",
        "stock_lt": "VTI",
        "crypto_swing": "BTC/USD",
        "crypto_day": "ETH/USD",
        "crypto_lt": "BTC/USD",
    }
    return _defaults.get(profile_name, "SPY")


def _primary_strategy(profile_name: str) -> str:
    """Map profile name to its primary strategy name."""
    _map = {
        "stock_swing": "mean_reversion",
        "stock_day": "opening_range",
        "stock_lt": "factor_blend",
        "crypto_swing": "crypto_rsi_mean_reversion",
        "crypto_day": "crypto_intraday_momentum",
        "crypto_lt": "dca_btc_eth",
    }
    return _map.get(profile_name, "mean_reversion")


def _cadence_for_profile(profile_name: str) -> str:
    """Map profile name to bot cadence: 'day' | 'swing' | 'lt'."""
    if "day" in profile_name:
        return "day"
    if "lt" in profile_name:
        return "lt"
    return "swing"
