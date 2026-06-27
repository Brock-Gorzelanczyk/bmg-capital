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


def _current_et_session() -> str:
    """Return the current US equity trading session based on ET clock.

    Returns one of: 'premarket', 'regular', 'afterhours', 'closed'.
    Degrades to 'regular' if timezone data is unavailable.
    """
    try:
        import pytz
        _ET = pytz.timezone("America/New_York")
        now = datetime.now(_ET)
        weekday = now.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
        if weekday >= 5:
            return "closed"
        hour = now.hour + now.minute / 60.0
        if 4.0 <= hour < 9.5:
            return "premarket"
        if 9.5 <= hour < 16.0:
            return "regular"
        if 16.0 <= hour < 20.0:
            return "afterhours"
        return "closed"
    except Exception:
        return "regular"


# ── Ensemble helpers ──────────────────────────────────────────────────────────

def _weighted_vote(signals_by_strategy: list[list], threshold: float = 0.5) -> list:
    """Average confidence for each symbol/side combination across strategies.

    A symbol/side pair wins if its weighted-average confidence >= threshold.
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
        if avg_conf >= threshold:
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


def _any_above_threshold(signals_by_strategy: list[list], threshold: float = 0.5) -> list:
    """Accept any signal from any single strategy if confidence >= threshold.

    No consensus required — one strategy firing is enough. Deduplicates by
    (symbol, side), keeping the highest-confidence signal when multiple
    strategies agree on the same pair.
    """
    from strategy_lab.core.signals import Signal

    best: dict[tuple[str, str], Any] = {}
    for strategy_signals in signals_by_strategy:
        for sig in strategy_signals:
            if sig.confidence < threshold:
                continue
            key = (sig.symbol, sig.side)
            if key not in best or sig.confidence > best[key].confidence:
                best[key] = sig

    out = []
    for sig in best.values():
        out.append(Signal(
            symbol=sig.symbol,
            side=sig.side,
            confidence=sig.confidence,
            size_hint=sig.size_hint,
            reason=f"[ensemble:any_above_threshold≥{threshold:.2f}] {sig.reason}",
            strategy=sig.strategy,
        ))
    return out


def _apply_ensemble(
    ensemble: str,
    signals_by_strategy: list[list],
    n_strategies: int,
    confidence_threshold: float = 0.5,
) -> list:
    """Dispatch to the appropriate ensemble aggregator."""
    if ensemble == "weighted_vote":
        return _weighted_vote(signals_by_strategy, threshold=confidence_threshold)
    if ensemble == "majority_vote":
        return _majority_vote(signals_by_strategy, n_strategies)
    if ensemble == "factor_rank":
        return _factor_rank(signals_by_strategy)
    if ensemble == "any_above_threshold":
        return _any_above_threshold(signals_by_strategy, confidence_threshold)
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
        f"strategy_lab.strategies.candidates.options.{strategy_name}",
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
    _scan_start = datetime.now(timezone.utc)
    logger.warning("[scheduled] %s scan START %s", profile_name, _scan_start.isoformat())
    logger.warning(">>> [runner:%s] scan cycle START %s", profile_name, _scan_start.isoformat())
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
                logger.warning("[runner:%s] SKIP profile disabled or not found in DB", profile_name)
                return {"skipped": True, "reason": "profile disabled or not found"}

            allocations = (
                db.query(BotAllocation)
                .filter(
                    BotAllocation.profile_id == bp.id,
                    BotAllocation.enabled.is_(True),
                    BotAllocation.paper_mode.is_(True),
                    # Skip paused allocations (admin_lock / health_halt /
                    # consecutive_loss_demotion_*). Before this filter, any
                    # allocation marked as paused would still execute trades
                    # because only `enabled` was checked. Pauses are supposed
                    # to be hard stops — observed via /admin/bot-health.
                    BotAllocation.paused_reason.is_(None),
                )
                .all()
            )
            if not allocations:
                logger.warning(
                    "[runner:%s] SKIP no enabled paper allocations — "
                    "profile_id=%s enabled=%s alloc_count=%s",
                    profile_name, bp.id, bp.enabled,
                    db.query(BotAllocation).filter(BotAllocation.profile_id == bp.id).count(),
                )
                return {"skipped": True, "reason": "no enabled paper allocations"}

            # Write scan heartbeat immediately — confirms scanner is reaching this bot
            try:
                from strategy_lab.core.bot_health import record_heartbeat
                for _alloc in allocations:
                    record_heartbeat(_alloc.id, db)
                logger.info("[runner:%s] scan heartbeat written for %d allocations", profile_name, len(allocations))
            except Exception as _hb_exc:
                logger.warning("[runner:%s] record_heartbeat failed (non-fatal): %s", profile_name, _hb_exc)

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
            _bar_interval = "1d"  # default; overwritten for intraday non-crypto bots
            if symbols:
                try:
                    if asset_class in ("crypto", "crypto_intraday", "quant"):
                        from app.screener.crypto_runner import _fetch_crypto_bars
                        raw_bars = _fetch_crypto_bars(symbols, timeframe=timeframe, limit=limit)
                    else:
                        from app.screener.runner import _fetch_bars_sync
                        lookback_period = profile.get("scan_lookback_period", "60d")

                        # Infer bar interval from profile cadence so intraday bots
                        # (ORB, VWAP, momentum) receive intraday bars.
                        # cadence "*/5 ..." → 5m bars with 1-day window.
                        # cadence "*/15 ..." → 15m bars. Otherwise daily.
                        _cadence = profile.get("cadence", "")
                        _cron_freq = _cadence.split()[0] if _cadence else ""
                        if _cron_freq in ("*/5", "*/3", "*/2", "*/1"):
                            _bar_interval = "5m"
                            _bar_period = "1d"  # 5m limit is 60d but ORB only needs today
                        elif _cron_freq == "*/15":
                            _bar_interval = "15m"
                            _bar_period = "5d"
                        elif _cron_freq == "*/30":
                            _bar_interval = "30m"
                            _bar_period = "30d"
                        else:
                            _bar_interval = "1d"
                            _bar_period = lookback_period

                        raw_bars = _fetch_bars_sync(symbols, period=_bar_period, interval=_bar_interval)
                        logger.warning(
                            "[runner:%s] bar fetch: interval=%s period=%s (cadence=%s)",
                            profile_name, _bar_interval, _bar_period, _cron_freq or "none",
                        )
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
                    if bars and _bar_interval != "1d":
                        _sample_sym = next(iter(bars))
                        logger.warning(
                            "[runner:%s] sample bar count for %s: %d bars (interval=%s)",
                            profile_name, _sample_sym, len(bars[_sample_sym]), _bar_interval,
                        )
                    logger.warning(
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

            logger.warning("[scan] bot=%s starting, %d symbols", profile_name, len(symbols))

            for strat_name in strategy_names:
                mod = _load_strategy_module(strat_name)
                if mod is None:
                    logger.warning("[scan] strategy '%s' not in registry — skipping", strat_name)
                    continue
                if not hasattr(mod, "generate_signals"):
                    logger.warning("[scan] strategy '%s' not in registry — skipping (no generate_signals)", strat_name)
                    continue
                # Log per-symbol intent before the bulk generate_signals call
                for _sym in symbols:
                    logger.debug("[scan] bot=%s running strategy=%s on %s", profile_name, strat_name, _sym)
                try:
                    strat_signals_raw = mod.generate_signals(bars, profile, regime)
                    # Apply strategy weight as confidence multiplier
                    weight = strategy_weight_map.get(strat_name, 1.0)
                    if weight != 1.0 and strat_signals_raw:
                        from strategy_lab.core.signals import Signal
                        strat_signals_raw = [
                            Signal(
                                symbol=s.symbol,
                                side=s.side,
                                confidence=min(1.0, s.confidence * weight),
                                size_hint=s.size_hint,
                                reason=f"[w={weight:.3f}] {s.reason}",
                                strategy=s.strategy,
                            )
                            for s in strat_signals_raw
                        ]
                    signals_by_strategy.append(strat_signals_raw or [])
                    strategies_loaded += 1
                    logger.info(
                        "[runner:%s] strategy %s → %d signals",
                        profile_name, strat_name, len(strat_signals_raw or []),
                    )
                    for _sig in (strat_signals_raw or []):
                        logger.info(
                            "[scan] bot=%s/%s(%s) → confidence=%.3f",
                            profile_name, strat_name, _sig.symbol, _sig.confidence,
                        )
                except Exception as exc:
                    logger.error(
                        "[scan] EXCEPTION in %s/%s: %s",
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
            conf_threshold = float(profile.get("confidence_threshold", 0.5))
            raw_total = sum(len(s) for s in signals_by_strategy)
            logger.warning(
                "[runner:%s] FILTER raw_signals=%d across %d strategies (threshold=%.2f, ensemble=%s)",
                profile_name, raw_total, strategies_loaded, conf_threshold, ensemble,
            )
            signals = _apply_ensemble(ensemble, signals_by_strategy, max(1, strategies_loaded), conf_threshold)
            logger.warning(
                "[runner:%s] FILTER after_ensemble=%d (dropped %d)",
                profile_name, len(signals), raw_total - len(signals),
            )

            # 8a. Multi-timeframe confluence filter (graceful)
            bot_cadence = _cadence_for_profile(profile_name)
            _pre_mtf = len(signals)
            filtered_signals = []
            for sig in signals:
                if sig.side == "hold":
                    filtered_signals.append(sig)
                    continue
                try:
                    from strategy_lab.core.expert.multi_timeframe import check_confluence
                    score = check_confluence(sig.symbol, sig, bars, bot_cadence, strategy=sig.strategy)
                    if score >= 0.66:
                        filtered_signals.append(sig)
                        logger.info(
                            "[runner:%s] MTF %s %s [%s]: score=%.2f PASS",
                            profile_name, sig.symbol, sig.side, sig.strategy, score,
                        )
                    else:
                        logger.info(
                            "[runner:%s] MTF %s %s [%s]: score=%.2f SKIP (threshold=0.66)",
                            profile_name, sig.symbol, sig.side, sig.strategy, score,
                        )
                except Exception as exc:
                    logger.warning("[runner:%s] multi_timeframe failed for %s: %s", profile_name, sig.symbol, exc)
                    filtered_signals.append(sig)  # degrade gracefully
            signals = filtered_signals
            logger.info(
                "[scheduled] %s after_mtf=%d/%d cadence=%s",
                profile_name, len(signals), _pre_mtf, bot_cadence,
            )
            logger.info(
                "[runner:%s] FILTER after_mtf=%d cadence=%s (dropped %d)",
                profile_name, len(signals), bot_cadence,
                len([s for s in signals_by_strategy for _ in s]) - len(signals),  # not ideal but OK for log
            )

            # 9. Apply risk overlay (graceful — may not be built yet)
            pre_overlay_count = len(signals)
            try:
                from strategy_lab.core.risk_overlay import apply_overlay  # type: ignore
                signals = apply_overlay(signals, profile, regime, db) or signals
            except (ImportError, Exception) as exc:
                logger.debug("[runner:%s] risk_overlay unavailable: %s", profile_name, exc)
            logger.info(
                "[scheduled] %s after_overlay=%d/%d",
                profile_name, len(signals), pre_overlay_count,
            )
            logger.info(
                "[runner:%s] FILTER after_overlay=%d (dropped %d)",
                profile_name, len(signals), pre_overlay_count - len(signals),
            )

            # 10. Expert decision layer: per-signal processing for actionable signals
            from strategy_lab.core.audit import log_signal

            actionable = [s for s in signals if s.side != "hold"]
            logger.info(
                "[scheduled] %s actionable=%d hold=%d — entering alloc loop (%d allocs)",
                profile_name, len(actionable), len(signals) - len(actionable), len(allocations),
            )
            logger.info(
                "[runner:%s] FILTER actionable=%d hold=%d",
                profile_name, len(actionable), len(signals) - len(actionable),
            )
            processed_signals = []
            _alloc_skip_counts: dict[str, int] = {}

            for alloc in allocations:
                alloc_user_id = alloc.user_id

                # T0 incubation bots must never execute trades — signal-only staging
                _alloc_tier = getattr(alloc, "tier", None)
                if _alloc_tier == "T0":
                    logger.warning(
                        "[runner:%s] BLOCKED alloc=%d tier=T0 — incubation bots cannot execute; "
                        "run m004 migration to pause or promote via tier system",
                        profile_name, alloc.id,
                    )
                    _alloc_skip_counts["t0_blocked"] = _alloc_skip_counts.get("t0_blocked", 0) + 1
                    continue

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

                # Gather open positions for position_cap + exposure + correlation.
                # Must exclude quarantined_at IS NOT NULL — quarantined positions
                # are not real open positions and must not count toward position_cap.
                open_pos_rows: list = []
                open_symbols: list[str] = []
                try:
                    from app.db.models.bots import BotPosition
                    open_pos_rows = (
                        db.query(BotPosition)
                        .filter(
                            BotPosition.allocation_id == alloc.id,
                            BotPosition.closed_at.is_(None),
                            BotPosition.quarantined_at.is_(None),
                        )
                        .all()
                    )
                    open_symbols = [p.symbol for p in open_pos_rows]
                except Exception as exc:
                    logger.warning("[runner:%s] Could not fetch open positions: %s", profile_name, exc)

                # ── FIX D: max_concurrent_positions enforcement ──────────────────
                # Reads max_concurrent_positions first (Brock's 7-day push spec),
                # falls back to position_cap, then 999.
                position_cap = int(
                    profile.get("max_concurrent_positions")
                    or profile.get("position_cap")
                    or 999
                )
                if len(open_pos_rows) >= position_cap:
                    logger.warning(
                        "[guardrail] %s alloc=%d blocked: max_concurrent_positions_reached open=%d cap=%d",
                        profile_name, alloc.id, len(open_pos_rows), position_cap,
                    )
                    _alloc_skip_counts["max_concurrent_positions"] = (
                        _alloc_skip_counts.get("max_concurrent_positions", 0) + 1
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
                                "[runner:%s] FILTER[alloc=%d] SKIP exposure_cap=%.1f%% gross=%.1f%%",
                                profile_name, alloc.id, max_gross_pct, gross_pct,
                            )
                            _alloc_skip_counts["exposure_cap"] = _alloc_skip_counts.get("exposure_cap", 0) + 1
                            continue
                except Exception as exc:
                    logger.warning("[runner:%s] exposure_cap check failed: %s", profile_name, exc)

                for sig in actionable:
                    if sig.side == "hold":
                        continue

                    # Long-only bots: skip sell/short signals unless we already hold the position
                    if profile.get("long_only") and sig.side in ("sell", "short") and sig.symbol not in open_symbols:
                        logger.info(
                            "[runner:%s] SKIP short %s — long_only=true and not holding",
                            profile_name, sig.symbol,
                        )
                        continue

                    # sell signals now route to the short execution path in _execute_signal.

                    # 10-pre. Extended-hours session filter (equities only).
                    # Only applies when the profile has execution.extended_hours: true.
                    _ext_hours_cfg = profile.get("execution", {})
                    if _ext_hours_cfg.get("extended_hours"):
                        _session = _current_et_session()
                        if _session != "regular":
                            _ro = profile.get("risk_overlay", {})
                            _conf_boost = float(_ro.get("extended_hours_confidence_boost", 0.10))
                            _required_conf = float(profile.get("confidence_threshold", 0.55)) + _conf_boost
                            if sig.confidence < _required_conf:
                                logger.info(
                                    "[runner:%s] SKIP %s session=%s confidence=%.2f < required=%.2f (ext-hours boost)",
                                    profile_name, sig.symbol, _session, sig.confidence, _required_conf,
                                )
                                continue
                            _ext_ok = set(profile.get("session_filter", {}).get("extended_ok_strategies", []))
                            if _ext_ok and (sig.strategy or "") not in _ext_ok:
                                logger.info(
                                    "[runner:%s] SKIP %s session=%s strategy=%s not in extended_ok_strategies",
                                    profile_name, sig.symbol, _session, sig.strategy,
                                )
                                continue

                    symbol_bars = bars.get(sig.symbol, [])

                    # ── Pre-compute entry price and stop/target so we can persist the
                    # signal BEFORE execution guards that may skip/continue.  This
                    # ensures bot_signals is populated even when anomaly/news/coordinator
                    # blocks the actual trade.
                    _entry_price = None
                    if bars.get(sig.symbol):
                        _last = bars[sig.symbol][-1]
                        _entry_price = float(_last.get("c") or _last.get("close") or 0) or None

                    stop_info: dict = {}
                    try:
                        from strategy_lab.core.expert.smart_stops import compute_stop
                        if _entry_price and _entry_price > 0:
                            stop_info = compute_stop(sig.symbol, sig.side, _entry_price, symbol_bars)
                    except Exception as exc:
                        logger.warning("[runner:%s] smart_stops failed for %s: %s", profile_name, sig.symbol, exc)

                    # Fallback: profile stop_loss_pct / take_profit_pct when smart_stops returned nothing
                    if not stop_info.get("stop_price") and _entry_price and _entry_price > 0:
                        _sl_pct = float(profile.get("stop_loss_pct", 7.0)) / 100
                        _tp_pct = float(profile.get("take_profit_pct", 15.0)) / 100
                        stop_info = {
                            "stop_price": round(_entry_price * (1 - _sl_pct), 6),
                            "target_price": round(_entry_price * (1 + _tp_pct), 6),
                        }

                    # ── Compute notional before log_signal so the audit.py background
                    # Discord post (which fires immediately from log_signal) shows the
                    # deployment-sizer amount rather than position_size_pct × capital.
                    _log_capital = (alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000) / 100.0
                    _pre_size_pct = (sig.size_hint or 0.05) * 100
                    if os.getenv("ENABLE_DEPLOYMENT_TARGET_SIZING", "false").strip().lower() == "true":
                        try:
                            from strategy_lab.core.deployment_sizer import compute_per_trade_notional as _cpt_pre
                            _notional_usd = _cpt_pre(alloc, profile, db, _log_capital, profile_name) or (_log_capital * _pre_size_pct / 100.0)
                        except Exception:
                            _notional_usd = _log_capital * _pre_size_pct / 100.0
                    else:
                        _notional_usd = _log_capital * _pre_size_pct / 100.0

                    # ── Discipline filter — 3 gates (regime / score / confluence).
                    # Evaluate BEFORE log_signal so we can suppress Discord posts
                    # on filtered signals while still persisting the trace.
                    try:
                        from app.services.discipline import evaluate_gates as _eval_gates, persist_gate as _persist_gate
                        _gate_result = _eval_gates(db, sig, profile, alloc.id)
                    except Exception as _gate_exc:
                        logger.warning("[discipline] evaluate failed for %s %s: %s",
                                       profile_name, sig.symbol, _gate_exc)
                        _gate_result = None

                    _gates_filtered = bool(_gate_result and not _gate_result.all_passed)

                    # ── Persist signal to bot_signals now (before any execution guard
                    # that could continue/skip).  Wrapped so a DB error never aborts
                    # the scan loop.
                    _signal_id: int | None = None
                    try:
                        _signal_id = log_signal(
                            db, alloc.id, sig,
                            entry_price=_entry_price,
                            stop_price=stop_info.get("stop_price"),
                            target_price=stop_info.get("target_price"),
                            notional_usd=_notional_usd,
                            skip_discord=_gates_filtered,
                        )
                        logger.info(
                            "[scheduled] %s SIGNAL PERSISTED %s %s confidence=%.3f alloc=%d signal_id=%s",
                            profile_name, sig.side, sig.symbol, sig.confidence, alloc.id, _signal_id,
                        )
                    except Exception as _sig_persist_exc:
                        logger.error(
                            "[scheduled] %s log_signal FAILED %s %s — traceback:",
                            profile_name, sig.side, sig.symbol, exc_info=True,
                        )

                    # Write SignalGate trace row (best-effort) and short-circuit if filtered.
                    if _gate_result is not None:
                        try:
                            _persist_gate(db, _signal_id, profile_name, sig, _gate_result)
                        except Exception:
                            pass
                        if _gates_filtered:
                            _alloc_skip_counts["discipline_gate"] = _alloc_skip_counts.get("discipline_gate", 0) + 1
                            logger.info(
                                "[discipline] %s FILTERED %s %s — reason=%s score=%d/%d confluence=%d/%d",
                                profile_name, sig.side, sig.symbol,
                                _gate_result.filter_reason,
                                _gate_result.composite_score, _gate_result.composite_threshold,
                                _gate_result.confluence_factors_passed, _gate_result.confluence_required,
                            )
                            continue

                    # skip_execution_guards: true in YAML bypasses anomaly/news/coordinator blocks.
                    _skip_guards = profile.get("skip_execution_guards", False)

                    # 10a. Anomaly detector — halt on abnormal conditions
                    try:
                        from strategy_lab.core.expert.anomaly_detector import check_for_anomaly
                        anomaly = check_for_anomaly(sig.symbol, symbol_bars, alloc.id, db)
                        if anomaly.get("halt") and not _skip_guards:
                            logger.warning(
                                "[exec] SKIP anomaly_halt %s %s: %s",
                                profile_name, sig.symbol, anomaly.get("anomaly_type"),
                            )
                            continue  # skip this signal
                        elif anomaly.get("halt"):
                            logger.info(
                                "[exec] guard_bypassed anomaly_halt %s %s (skip_execution_guards=true)",
                                profile_name, sig.symbol,
                            )
                    except Exception as exc:
                        logger.warning("[runner:%s] anomaly_detector failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10b. News entry block check
                    try:
                        from strategy_lab.core.expert.news_stop_adjuster import should_block_new_entries
                        if should_block_new_entries(sig.symbol, db):
                            if not _skip_guards:
                                logger.info(
                                    "[exec] SKIP news_block %s %s",
                                    profile_name, sig.symbol,
                                )
                                continue
                            else:
                                logger.info(
                                    "[exec] guard_bypassed news_block %s %s (skip_execution_guards=true)",
                                    profile_name, sig.symbol,
                                )
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
                            if not _skip_guards:
                                logger.info(
                                    "[exec] SKIP bot_coordinator %s %s: %s",
                                    profile_name, sig.symbol, coord_result.get("reason"),
                                )
                                continue
                            else:
                                logger.info(
                                    "[exec] guard_bypassed bot_coordinator %s %s: %s (skip_execution_guards=true)",
                                    profile_name, sig.symbol, coord_result.get("reason"),
                                )
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

                    # 10f. (smart_stops already computed above, before signal persist)

                    # 10g. Pyramid: enter at 50% of adjusted size
                    final_size_pct = adjusted_size_pct
                    try:
                        from strategy_lab.core.expert.position_pyramid import initial_size_pct
                        final_size_pct = initial_size_pct(adjusted_size_pct)
                    except Exception as exc:
                        logger.warning("[runner:%s] position_pyramid failed for %s: %s", profile_name, sig.symbol, exc)

                    # 10g-ext. Extended-hours size multiplier (half-size in pre/post-market)
                    if profile.get("execution", {}).get("extended_hours"):
                        _ext_session = _current_et_session()
                        if _ext_session != "regular":
                            _ro = profile.get("risk_overlay", {})
                            _size_mult = float(_ro.get("extended_hours_size_multiplier", 0.5))
                            final_size_pct = round(final_size_pct * _size_mult, 4)
                            logger.info(
                                "[runner:%s] Extended-hours size ×%.2f → %.4f%% (session=%s)",
                                profile_name, _size_mult, final_size_pct, _ext_session,
                            )

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

                    # 10i-pre. Institutional risk gates (stock_day + stock_swing only)
                    if profile_name in ("stock_day", "stock_swing") and sig.side == "buy":
                        # Regime gate: VIX extreme halts, VIX high scales size
                        try:
                            from strategy_lab.core.regime_gate import regime_position_size_multiplier
                            _rm_mult = regime_position_size_multiplier(profile, regime)
                            if _rm_mult == 0.0:
                                logger.warning(
                                    "[runner:%s] HALT %s — regime_gate blocks entry",
                                    profile_name, sig.symbol,
                                )
                                continue
                            if _rm_mult != 1.0:
                                final_size_pct = round(final_size_pct * _rm_mult, 4)
                        except Exception as exc:
                            logger.warning("[runner:%s] regime_gate failed for %s: %s",
                                           profile_name, sig.symbol, exc)

                        # Sector concentration cap
                        try:
                            from strategy_lab.core.sector_map import get_sector
                            _rm_cfg = profile.get("risk_management", {})
                            _sec_max = int(_rm_cfg.get("sector_concentration_max", 99))
                            _this_sector = get_sector(sig.symbol)
                            if _this_sector and _this_sector != "etf":
                                _sector_count = sum(
                                    1 for _op in open_pos_rows
                                    if get_sector(_op.symbol) == _this_sector
                                )
                                if _sector_count >= _sec_max:
                                    logger.info(
                                        "[runner:%s] SKIP %s sector_cap: sector=%s count=%d/%d",
                                        profile_name, sig.symbol, _this_sector,
                                        _sector_count, _sec_max,
                                    )
                                    _alloc_skip_counts["sector_cap"] = (
                                        _alloc_skip_counts.get("sector_cap", 0) + 1
                                    )
                                    continue
                        except Exception as exc:
                            logger.warning("[runner:%s] sector_cap failed for %s: %s",
                                           profile_name, sig.symbol, exc)

                        # Earnings exclusion window
                        try:
                            _rm_cfg = profile.get("risk_management", {})
                            _exc_days = int(_rm_cfg.get("exclude_pending_earnings_days", 3))
                            from strategy_lab.core.catalyst_calendar import get_upcoming_earnings  # type: ignore
                            _earn_symbols = get_upcoming_earnings(days=_exc_days)
                            if sig.symbol in (_earn_symbols or []):
                                logger.info(
                                    "[runner:%s] SKIP %s earnings_window (%d days)",
                                    profile_name, sig.symbol, _exc_days,
                                )
                                continue
                        except ImportError:
                            pass  # earnings guard not available; universe filter still applies
                        except Exception as exc:
                            logger.warning("[runner:%s] earnings_guard failed for %s: %s",
                                           profile_name, sig.symbol, exc)

                        # Idempotency — suppress duplicate fills within same scan minute
                        try:
                            from strategy_lab.core.idempotency import (
                                order_idempotency_key, is_duplicate, log_order_attempt,
                            )
                            _idem_key = order_idempotency_key(
                                profile_name, sig.symbol, sig.side, _scan_start,
                            )
                            if is_duplicate(_idem_key):
                                logger.info(
                                    "[runner:%s] SKIP %s idempotency_dup key=%s",
                                    profile_name, sig.symbol, _idem_key,
                                )
                                continue
                            log_order_attempt(_idem_key, "pending")
                        except Exception as exc:
                            logger.warning("[runner:%s] idempotency check failed for %s: %s",
                                           profile_name, sig.symbol, exc)

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
                            signal_id=_signal_id,
                        )
                        logger.info(
                            "[scheduled] %s _execute_signal OK %s %s",
                            profile_name, sig.side, sig.symbol,
                        )
                    except Exception as exc:
                        logger.error(
                            "[scheduled] %s _execute_signal FAILED %s %s — traceback:",
                            profile_name, sig.side, sig.symbol, exc_info=True,
                        )

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

                    # Build signal dict for per-user notifications
                    _signal_dict = {
                        "bot": profile_name,
                        "symbol": sig.symbol,
                        "side": sig.side,
                        "strategy": sig.strategy or profile_name,
                        "reason": sig.reason or "",
                        "confidence": sig.confidence,
                        "price": _entry_price,
                        "size_pct": final_size_pct,
                        "notional_usd": _notional_usd,
                        "stop": stop_info.get("stop_price"),
                        "target": stop_info.get("target_price"),
                    }

                    # Private per-user notifications (Discord webhook, Telegram, Slack, Email)
                    try:
                        from app.services.notify import dispatch_signal
                        dispatch_signal(_signal_dict, db)
                    except Exception as _exc:
                        logger.debug("[runner:%s] private notify skipped: %s", profile_name, _exc)

                    # Channel-routed Discord post via bot token (stocks/options/crypto)
                    try:
                        from app.services.discord_public import post_signal as _pub_post
                        _pub_post(
                            signal=_signal_dict,
                            db=db,
                            signal_id=_signal_id,
                        )
                        logger.warning(
                            "[discord] %s posted %s %s to channel (signal_id=%s)",
                            profile_name, sig.side, sig.symbol, _signal_id,
                        )
                    except Exception as _exc:
                        logger.warning(
                            "[discord] %s post FAILED %s %s: %s",
                            profile_name, sig.side, sig.symbol, _exc,
                        )

                    # One-shot: #announcements alert on the very first real crypto buy signal
                    if profile_name in {"crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain", "crypto_quant_aggressive"} and sig.side == "buy":
                        try:
                            _maybe_announce_first_live_signal(
                                db=db,
                                bot_name=profile_name,
                                strategy=sig.strategy or profile_name,
                                symbol=sig.symbol,
                            )
                        except Exception as _exc:
                            logger.debug("[runner:%s] first_live_signal_announcement skipped: %s", profile_name, _exc)

            # Alloc-loop summary
            if _alloc_skip_counts:
                logger.info(
                    "[runner:%s] FILTER alloc_skips=%s (of %d allocs)",
                    profile_name, dict(_alloc_skip_counts), len(allocations),
                )

            # Also audit hold signals per allocation (non-expert path)
            hold_signals = [s for s in signals if s.side == "hold"]
            for alloc in allocations:
                for sig in hold_signals:
                    log_signal(db, alloc.id, sig)

            # 11. Update watchlist: score, reasons, and last_evaluated_at
            try:
                from app.db.models.bots import BotWatchlist

                # Build per-symbol best-confidence map from all strategy outputs.
                # score = int(best_confidence * 100), capped at 100.
                _sym_best: dict[str, dict] = {}  # symbol → {confidence, side, strategy}
                for _strat_idx, _strat_name in enumerate(strategy_names):
                    if _strat_idx >= len(signals_by_strategy):
                        break
                    for _s in (signals_by_strategy[_strat_idx] or []):
                        if _s.symbol not in _sym_best or _s.confidence > _sym_best[_s.symbol]["confidence"]:
                            _sym_best[_s.symbol] = {
                                "confidence": _s.confidence,
                                "side": _s.side,
                                "strategy": _s.strategy or _strat_name,
                            }

                _now_ts = datetime.now(timezone.utc)
                _wl_rows = (
                    db.query(BotWatchlist)
                    .filter(
                        BotWatchlist.profile_id == bp.id,
                        BotWatchlist.symbol.in_(symbols) if symbols else False,
                    )
                    .all()
                )
                for _wl in _wl_rows:
                    _wl.last_evaluated_at = _now_ts
                    _best = _sym_best.get(_wl.symbol)
                    if _best:
                        # Update score with real confidence × 100 (int, capped 0-100)
                        _wl.score = min(100, int(_best["confidence"] * 100))
                        _wl.reasons = {
                            _best["strategy"]: {
                                "confidence": round(_best["confidence"], 4),
                                "side": _best["side"],
                            }
                        }
                    else:
                        # Symbol scanned but no signal produced — update metadata only
                        _wl.reasons = {
                            "scanned": 1,
                            "strategies_run": strategies_loaded,
                            "signals_generated": sum(len(s) for s in signals_by_strategy),
                        }
                if _wl_rows:
                    db.commit()
                    _updated_with_score = sum(1 for _wl in _wl_rows if _wl.symbol in _sym_best)
                    logger.info(
                        "[runner:%s] Watchlist updated: %d rows, %d with real scores",
                        profile_name, len(_wl_rows), _updated_with_score,
                    )
            except Exception as _wl_exc:
                logger.warning("[runner:%s] watchlist update failed: %s", profile_name, _wl_exc)

            # 12. Build and persist audit record
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

            _scan_ms = int((datetime.now(timezone.utc) - _scan_start).total_seconds() * 1000)
            logger.warning(
                "[scheduled] %s COMPLETE %dms — allocs=%d actionable=%d persisted=%d",
                profile_name, _scan_ms, len(allocations), len(actionable), len(processed_signals),
            )
            logger.warning(
                "<<< [runner:%s] scan cycle COMPLETE in %dms — "
                "%d allocs, %d actionable signals, %d processed",
                profile_name, _scan_ms, len(allocations), len(actionable), len(processed_signals),
            )
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
        _scan_ms = int((datetime.now(timezone.utc) - _scan_start).total_seconds() * 1000)
        logger.error("Bot runner FAILED for %s after %dms: %s", profile_name, _scan_ms, exc, exc_info=True)
        return {"error": str(exc)}


# ── Debug scan trace (dry-run — no DB writes, no orders) ─────────────────────

def trace_bot_profile(profile_name: str, confidence_threshold_override: float | None = None) -> dict:
    """Dry-run scan pipeline for `profile_name` and return gate-by-gate counts.

    No orders are submitted and nothing is written to the database.
    Accepts an optional confidence_threshold_override so callers can test
    with a lower bar without editing the YAML.

    Returns a dict matching the /api/bots/debug/scan-trace response schema.
    """
    errors: list[str] = []
    trace: dict = {
        "profile": profile_name,
        "confidence_threshold_used": confidence_threshold_override,
        "bars_fetched": "0/0",
        "bars_per_symbol": {},
        "raw_signals_per_strategy": {},
        "candidates_from_strategy": 0,
        "after_ensemble": 0,
        "after_mtf_confluence": 0,
        "after_apply_overlay": 0,
        "after_check_guardrails": 0,
        "after_position_cap": 0,
        "after_exposure_cap": 0,
        "signals_inserted": 0,
        "errors": errors,
    }

    try:
        from strategy_lab.seeds import load_profile
        profile = load_profile(profile_name)

        # Apply confidence threshold override
        if confidence_threshold_override is not None:
            profile = dict(profile)
            profile["confidence_threshold"] = confidence_threshold_override
            trace["confidence_threshold_used"] = confidence_threshold_override
        else:
            trace["confidence_threshold_used"] = profile.get("confidence_threshold", 0.50)

        from app.db.session import SessionLocal
        from app.db.models.bots import BotProfile as _BP, BotAllocation as _BA, BotPosition as _BPos

        db = SessionLocal()
        try:
            bp = db.query(_BP).filter(_BP.name == profile_name).first()
            if not bp or not bp.enabled:
                trace["errors"].append("profile disabled or not found in DB")
                return trace

            allocations = (
                db.query(_BA)
                .filter(_BA.profile_id == bp.id, _BA.enabled.is_(True), _BA.paper_mode.is_(True))
                .all()
            )
            if not allocations:
                trace["errors"].append("no enabled paper allocations")
                return trace

            # ── Bars fetch ────────────────────────────────────────────────────
            asset_class = profile.get("asset_class", "stock")
            universe = profile.get("universe", {})
            symbols: list[str] = (
                universe.get("symbols", []) if isinstance(universe, dict) else list(universe or [])
            )
            timeframe = profile.get("scan_timeframe", "1h")
            limit = int(profile.get("scan_lookback_bars", 200))

            bars: dict[str, list[dict]] = {}
            try:
                if asset_class in ("crypto", "crypto_intraday", "quant"):
                    from app.screener.crypto_runner import _fetch_crypto_bars
                    raw = _fetch_crypto_bars(symbols, timeframe=timeframe, limit=limit)
                else:
                    from app.screener.runner import _fetch_bars_sync
                    _lookback = profile.get("scan_lookback_period", "60d")
                    raw = _fetch_bars_sync(symbols, period=_lookback)
                for sym, df in raw.items():
                    if df is None or df.empty:
                        continue
                    bars[sym] = [
                        {"c": float(r["close"]), "o": float(r["open"]),
                         "h": float(r["high"]), "l": float(r["low"]),
                         "v": float(r.get("volume", 0) or 0),
                         "ts": r.name.isoformat() if hasattr(r.name, "isoformat") else str(r.name)}
                        for _, r in df.iterrows()
                    ]
            except Exception as exc:
                errors.append(f"bar_fetch: {exc}")

            trace["bars_fetched"] = f"{len(bars)}/{len(symbols)}"
            trace["bars_per_symbol"] = {s: len(b) for s, b in bars.items()}

            # ── Regime (graceful) ─────────────────────────────────────────────
            regime: dict = {}
            try:
                from strategy_lab.core.regime_detector import detect_regime
                regime = detect_regime(profile_name, profile) or {}
            except Exception:
                pass

            # ── Strategies → raw signals ──────────────────────────────────────
            strategy_names: list[str] = profile.get("strategies", []) or [_primary_strategy(profile_name)]
            signals_by_strategy: list[list] = []
            strategies_loaded = 0

            for strat_name in strategy_names:
                mod = _load_strategy_module(strat_name)
                if mod is None or not hasattr(mod, "generate_signals"):
                    continue
                try:
                    sigs = mod.generate_signals(bars, profile, regime) or []
                    signals_by_strategy.append(sigs)
                    strategies_loaded += 1
                    trace["raw_signals_per_strategy"][strat_name] = len(sigs)
                    if sigs:
                        # Show first signal's confidence for debugging
                        trace["raw_signals_per_strategy"][f"{strat_name}_sample_conf"] = round(sigs[0].confidence, 4)
                except Exception as exc:
                    errors.append(f"strategy_{strat_name}: {exc}")
                    signals_by_strategy.append([])

            total_raw = sum(len(s) for s in signals_by_strategy)
            trace["candidates_from_strategy"] = total_raw

            # ── Ensemble ──────────────────────────────────────────────────────
            ensemble = profile.get("ensemble", "weighted_vote")
            conf_threshold = float(profile.get("confidence_threshold", 0.5))
            signals = _apply_ensemble(ensemble, signals_by_strategy, max(1, strategies_loaded), conf_threshold)
            trace["after_ensemble"] = len(signals)

            # ── MTF confluence ────────────────────────────────────────────────
            bot_cadence = _cadence_for_profile(profile_name)
            filtered: list = []
            mtf_detail: list[str] = []
            for sig in signals:
                if sig.side == "hold":
                    filtered.append(sig)
                    continue
                try:
                    from strategy_lab.core.expert.multi_timeframe import check_confluence
                    score = check_confluence(sig.symbol, sig, bars, bot_cadence, strategy=sig.strategy)
                    mtf_detail.append(f"{sig.symbol}/{sig.side}[{sig.strategy}]={score:.2f}")
                    if score >= 0.66:
                        filtered.append(sig)
                except Exception:
                    filtered.append(sig)
            signals = filtered
            trace["after_mtf_confluence"] = len(signals)
            trace["mtf_scores"] = mtf_detail

            # ── Risk overlay ──────────────────────────────────────────────────
            try:
                from strategy_lab.core.risk_overlay import apply_overlay
                signals = apply_overlay(signals, profile, regime, db) or signals
            except Exception:
                pass
            trace["after_apply_overlay"] = len(signals)

            # ── Per-alloc gates (check first alloc only for simplicity) ───────
            actionable = [s for s in signals if s.side != "hold"]
            # Use first alloc as representative sample
            alloc = allocations[0]

            guardrail_pass = True
            try:
                from app.services.guardrail_checker import check_guardrails
                ok, reason = check_guardrails(alloc.user_id, db)
                if not ok:
                    guardrail_pass = False
                    errors.append(f"guardrail_block: {reason}")
            except Exception as exc:
                errors.append(f"guardrail_check_failed: {exc}")

            trace["after_check_guardrails"] = len(actionable) if guardrail_pass else 0

            open_pos_rows = (
                db.query(_BPos)
                .filter(
                    _BPos.allocation_id == alloc.id,
                    _BPos.closed_at.is_(None),
                    _BPos.quarantined_at.is_(None),
                )
                .all()
            )
            position_cap = int(profile.get("position_cap", 999))
            positions_held = len(open_pos_rows)
            trace["open_positions"] = positions_held
            trace["position_cap"] = position_cap

            if positions_held >= position_cap:
                trace["after_position_cap"] = 0
                errors.append(f"position_cap_hit: {positions_held}/{position_cap}")
            else:
                after_pcap = len(actionable) if guardrail_pass else 0
                trace["after_position_cap"] = after_pcap

                # Exposure cap
                risk_overlay_cfg = profile.get("risk_overlay", {})
                max_gross_pct = float(risk_overlay_cfg.get("max_gross_exposure_pct", 100.0))
                cap_cents = alloc.starting_capital_cents or alloc.capital_cents_within_portfolio or 0
                blocked_by_exposure = False
                if cap_cents > 0 and open_pos_rows:
                    open_notional_cents = sum(int(p.qty * p.avg_cost_cents) for p in open_pos_rows)
                    gross_pct = (open_notional_cents / cap_cents) * 100
                    trace["gross_exposure_pct"] = round(gross_pct, 2)
                    if gross_pct >= max_gross_pct:
                        blocked_by_exposure = True
                        errors.append(f"exposure_cap_hit: {gross_pct:.1f}%/{max_gross_pct}%")

                trace["after_exposure_cap"] = 0 if blocked_by_exposure else after_pcap

            # signals_inserted stays 0 — this is a dry-run
            trace["signals_inserted"] = 0
            trace["note"] = "dry-run: no DB writes or orders submitted"

        finally:
            db.close()

    except Exception as exc:
        errors.append(f"outer: {exc}")

    return trace


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


# ── Options signal execution ──────────────────────────────────────────────────

def _resolve_option_details(sig, position_dollars: float) -> dict:
    """Extract/estimate option contract details from signal reason JSON.

    Returns a dict with: option_type, strike_price, expiration_date,
    underlying_symbol, contract_count, contract_premium_cents, display_premium.
    Falls back to estimation when yfinance is unavailable.

    Strike/DTE selection is *setup-aware*:
      • Long-directional debit buyers (long_call_directional, leaps_stock_replacement,
        bull_call_debit_spread): deep-ITM ~0.85 delta proxy (strike ≈ spot × 0.85
        for calls, spot × 1.15 for puts), 30-60 DTE clamp.
      • Short-premium credit sellers (cash_secured_put, wheel, bull_put_credit_spread,
        bear_call_credit_spread, iron_condor_45dte, jade_lizard): ~16-delta OTM
        short strike (~1 std dev OTM, approximated as ±8% from spot), 30-60 DTE
        clamp, force-close logic enforced elsewhere at 21 DTE.
      • Spreads/diagonals (pmcc, calendar): ATM-ish for the long leg.

    Sizing: notional capped at 5% of *sleeve* via the upstream position_dollars
    feed; if even 1 contract exceeds that budget we return contract_count=0 and
    the caller must skip the trade.
    """
    import json
    import math
    from datetime import date, timedelta

    underlying = sig.symbol
    option_type = "call"
    strike_price = None
    expiration_date = None
    contract_premium = None

    # Parse reason JSON from strategy signal
    reason_data: dict = {}
    if sig.reason:
        try:
            reason_data = json.loads(sig.reason)
        except Exception:
            pass

    setup = reason_data.get("setup", "")
    spot = float(reason_data.get("spot", 0) or 0)

    # ── Classify the setup → intent ──────────────────────────────────────────
    # intent ∈ {"long_directional", "short_credit", "spread_debit",
    #           "spread_credit", "diagonal", "neutral_credit"}
    LONG_DIRECTIONAL = {"long_call_directional", "leaps_stock_replacement"}
    SHORT_CREDIT_PUT = {"cash_secured_put", "wheel_strategy", "bull_put_credit_spread", "jade_lizard"}
    SHORT_CREDIT_CALL = {"covered_call_30d", "bear_call_credit_spread"}
    NEUTRAL_CREDIT = {"iron_condor_45dte", "neutral_calendar_spread"}
    SPREAD_DEBIT = {"bull_call_debit_spread"}
    DIAGONAL = {"pmcc_diagonal"}

    if setup in LONG_DIRECTIONAL:
        intent = "long_directional"
        option_type = "call"
    elif setup in SHORT_CREDIT_PUT:
        intent = "short_credit"
        option_type = "put"
    elif setup in SHORT_CREDIT_CALL:
        intent = "short_credit"
        option_type = "call"
    elif setup in NEUTRAL_CREDIT:
        intent = "neutral_credit"
        option_type = "iron condor" if "condor" in setup else "calendar"
    elif setup in SPREAD_DEBIT:
        intent = "spread_debit"
        option_type = "call"
    elif setup in DIAGONAL:
        intent = "diagonal"
        option_type = "call"
    else:
        # Conservative fallback: treat as short_credit put (safest default for
        # unknown income-style setups; long-bias would force lottery tickets).
        intent = "short_credit"
        option_type = "put" if any(k in setup for k in ("put", "csp", "wheel")) else "call"

    # ── DTE selection: target 45, clamp 30-60, hard reject > 90 ──────────────
    # All entries (directional AND income) target the same window per the
    # tastytrade canonical structure. LEAPS-style 12-18mo exposure is rebuilt
    # by rolling 45 DTE positions, NOT by buying 2027 contracts upfront.
    DTE_TARGET = 45
    DTE_MIN, DTE_MAX = 30, 60
    DTE_HARD_REJECT = 90

    # Diagonal/PMCC long leg wants longer-dated (~120-180 DTE), but the short
    # leg drives entries; for now keep diagonals on the 45 DTE path and surface
    # a TODO in the follow-up notes.
    target_dte = DTE_TARGET
    expiration_date = (date.today() + timedelta(days=target_dte)).isoformat()
    selected_dte = target_dte  # populated from real chain if available

    # ── Try yfinance for real option chain ───────────────────────────────────
    try:
        import yfinance as yf
        ticker = yf.Ticker(underlying)
        # Fetch spot price if not available from reason JSON
        if spot <= 0:
            try:
                _fi = ticker.fast_info
                spot = float(getattr(_fi, "last_price", 0) or 0)
            except Exception:
                pass
        exps = ticker.options
        if exps:
            from datetime import datetime
            today = date.today()
            # Filter expiries to the 30-60 DTE window
            eligible = []
            for e in exps:
                try:
                    edt = datetime.strptime(e, "%Y-%m-%d").date()
                    d = (edt - today).days
                    if DTE_MIN <= d <= DTE_MAX:
                        eligible.append((e, d))
                except Exception:
                    continue
            if not eligible:
                # Hard reject — no contract in the 30-60 DTE window
                logger.warning(
                    "[options] %s setup=%s: no expiry in [%d,%d] DTE window — REJECTING signal",
                    underlying, setup, DTE_MIN, DTE_MAX,
                )
                return {
                    "option_type": option_type,
                    "strike_price": None,
                    "expiration_date": None,
                    "underlying_symbol": underlying,
                    "contract_count": 0,
                    "contract_premium_cents": 0,
                    "display_premium": 0.0,
                    "reject_reason": f"no_expiry_in_{DTE_MIN}_{DTE_MAX}_dte",
                }
            # Pick the expiry closest to 45 DTE
            best_exp, best_dte = min(eligible, key=lambda x: abs(x[1] - DTE_TARGET))
            # Belt-and-suspenders: never trade > 90 DTE even if classified
            if best_dte > DTE_HARD_REJECT:
                logger.warning(
                    "[options] %s setup=%s: nearest expiry %dd > %dd hard limit — REJECTING",
                    underlying, setup, best_dte, DTE_HARD_REJECT,
                )
                return {
                    "option_type": option_type,
                    "strike_price": None,
                    "expiration_date": None,
                    "underlying_symbol": underlying,
                    "contract_count": 0,
                    "contract_premium_cents": 0,
                    "display_premium": 0.0,
                    "reject_reason": f"dte_{best_dte}_exceeds_hard_{DTE_HARD_REJECT}",
                }
            expiration_date = best_exp
            selected_dte = best_dte

            chain = ticker.option_chain(best_exp)
            # NB: spreads/condors will key off the *short* leg; we model the
            # short put for credit-put strategies and the short call for
            # credit-call/condor strategies. Premium is the *net* per-contract
            # cash flow we use for sizing.
            if intent == "short_credit" and option_type == "call":
                df = chain.calls
            elif intent == "short_credit" and option_type == "put":
                df = chain.puts
            elif intent == "neutral_credit":
                # Use the short call leg of the condor for sizing; the put-side
                # is symmetric and the resolver only emits one strike for the
                # legacy schema.
                df = chain.calls
            elif intent in ("long_directional", "spread_debit", "diagonal"):
                df = chain.calls if option_type == "call" else chain.puts
            else:
                df = chain.calls

            if not df.empty and spot > 0:
                # ── Strike selection by intent ────────────────────────────
                if intent == "long_directional":
                    # Delta-1 swing: target ~0.85 delta.
                    # Without a Greeks feed, deep-ITM proxy:
                    #   calls → strike ≈ spot × 0.85 (ITM by 15%)
                    #   puts  → strike ≈ spot × 1.15 (ITM by 15%)
                    if option_type == "call":
                        target_strike = spot * 0.85
                    else:
                        target_strike = spot * 1.15
                elif intent == "spread_debit":
                    # Long leg ATM, target slightly ITM call (delta ~0.55)
                    target_strike = spot * 0.99
                elif intent == "short_credit" and option_type == "put":
                    # ~16-delta short put: ~1 std dev OTM. For a 45 DTE
                    # at typical 25% IV that's roughly 8% OTM.
                    target_strike = spot * 0.92
                elif intent == "short_credit" and option_type == "call":
                    target_strike = spot * 1.08
                elif intent == "neutral_credit":
                    # 16-delta short call leg of the condor
                    target_strike = spot * 1.08
                elif intent == "diagonal":
                    # PMCC: long leg deep-ITM (delta ~0.80)
                    target_strike = spot * 0.85
                else:
                    target_strike = spot

                row = df.iloc[(df["strike"] - target_strike).abs().argsort()[:1]]
                if not row.empty:
                    strike_price = float(row["strike"].iloc[0])
                    mid = (float(row["bid"].iloc[0]) + float(row["ask"].iloc[0])) / 2
                    contract_premium = mid if mid > 0 else float(row["lastPrice"].iloc[0])
    except Exception as yf_exc:
        logger.debug("[options] yfinance chain lookup failed for %s: %s", underlying, yf_exc)

    # ── Fallback estimation when yfinance unavailable ────────────────────────
    if spot <= 0:
        spot = 100.0  # generic fallback
    if strike_price is None:
        # Mirror the intent-aware targets above for the fallback path so the
        # estimated trade still reflects the *correct* strike geometry.
        if intent == "long_directional":
            strike_price = round(spot * (0.85 if option_type == "call" else 1.15), 2)
        elif intent == "spread_debit":
            strike_price = round(spot * 0.99, 2)
        elif intent == "short_credit" and option_type == "put":
            strike_price = round(spot * 0.92, 2)
        elif intent == "short_credit" and option_type == "call":
            strike_price = round(spot * 1.08, 2)
        elif intent == "neutral_credit":
            strike_price = round(spot * 1.08, 2)
        elif intent == "diagonal":
            strike_price = round(spot * 0.85, 2)
        else:
            strike_price = round(spot, 2)
    if contract_premium is None:
        # Fallback premium estimate. Deep-ITM ≈ intrinsic + ~3% extrinsic.
        if intent == "long_directional":
            intrinsic = max(0.0, spot - strike_price) if option_type == "call" else max(0.0, strike_price - spot)
            contract_premium = round(intrinsic + spot * 0.03, 2)
        elif intent in ("short_credit", "neutral_credit"):
            # Short premium: ~1-1.5% of spot for 16-delta 45 DTE
            contract_premium = round(spot * 0.012, 2)
        else:
            contract_premium = round(spot * 0.035, 2)

    # ── Sizing: cap notional at 5% of sleeve per trade ───────────────────────
    # `position_dollars` is set upstream from profile.position_size_pct of
    # sleeve capital. We *additionally* hard-cap at 5% (NOTIONAL_CAP_PCT) of
    # the sleeve to prevent any single contract from blowing the budget.
    # NB: position_dollars already encodes the per-trade allocation; we
    # interpret it as the *max premium-at-risk for this trade*. If even one
    # contract exceeds it, we return contract_count=0 → caller must skip.
    max_premium_at_risk = position_dollars  # already sleeve_capital × position_size_pct
    per_contract_cost = max(0.01, contract_premium) * 100
    raw_count = math.floor(max_premium_at_risk / per_contract_cost)
    contract_count = max(0, raw_count)

    if contract_count == 0:
        logger.warning(
            "[options] %s setup=%s: 1 contract ($%.0f premium) exceeds per-trade budget "
            "$%.0f — REJECTING signal (was previously forced to 1 contract = over-allocation bug)",
            underlying, setup, per_contract_cost, max_premium_at_risk,
        )

    contract_premium_cents = round(contract_premium * 100, 2)

    return {
        "option_type": option_type,
        "strike_price": strike_price,
        "expiration_date": expiration_date,
        "underlying_symbol": underlying,
        "contract_count": contract_count,
        "contract_premium_cents": contract_premium_cents,
        "display_premium": contract_premium,
        "selected_dte": selected_dte,
        "intent": intent,
    }


# Options routing is driven entirely by the profile's `asset_class: options`.
# A hard-coded strategy frozenset used to double-check this, but maintaining
# two sources of truth caused drift: any new options strategy added to a
# profile YAML had to also be added to the frozenset to route correctly, and
# the safety-net behaviour just hid misconfigured profiles. Trust the YAML.


def _execute_options_signal(
    db, alloc, sig, final_size_pct: float, profile: dict, profile_name: str,
    signal_id: int | None = None,
) -> None:
    """Execute an options signal — creates BotPosition + BotTrade with options fields."""
    import os
    import json
    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade

    now = datetime.now(timezone.utc)
    capital_usd = (alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000) / 100.0
    position_dollars = capital_usd * (final_size_pct / 100.0)

    # Hard sleeve-level notional cap: never risk more than 5% of sleeve capital
    # on a single options contract (regardless of profile.position_size_pct).
    # This is the third leg of the AMD-LEAPS fix — even if the profile says
    # 15% and the smart-sizer agrees, options notional gets clamped here.
    OPTIONS_MAX_NOTIONAL_PCT = 0.05
    notional_cap = capital_usd * OPTIONS_MAX_NOTIONAL_PCT
    if position_dollars > notional_cap:
        logger.info(
            "[options:%s] %s clamping per-trade budget $%.0f → $%.0f (5%% sleeve cap)",
            profile_name, sig.symbol, position_dollars, notional_cap,
        )
        position_dollars = notional_cap

    # ── Phase 5: per-user concentration / sector / cluster gates (options) ──
    # Wire-in is BEFORE contract count compute. Options notional measured at
    # the budget level (post per-trade sleeve clamp). _resolve_option_details
    # will scale contract_count off this same budget so it's consistent.
    try:
        from strategy_lab.core.concentration_gate import check_concentration
        from app.db.models.bots import BotSignal as _BotSig_conc_opt
        _allowed_conc, _conc_reason = check_concentration(
            db,
            user_id=int(alloc.user_id),
            allocation_id=int(alloc.id),
            symbol=sig.symbol,
            proposed_notional=float(position_dollars),
            profile=profile or {},
        )
        if not _allowed_conc:
            logger.warning(
                "[concentration] %s %s blocked: %s",
                profile_name, sig.symbol, _conc_reason,
            )
            try:
                db.add(_BotSig_conc_opt(
                    allocation_id=alloc.id,
                    ts=now,
                    symbol=sig.symbol,
                    side="hold",
                    confidence=float(getattr(sig, "confidence", 0.0) or 0.0),
                    reason=f"concentration: {_conc_reason}",
                    strategy=getattr(sig, "strategy", None),
                ))
                db.commit()
            except Exception as _conc_log_exc:
                logger.warning("[concentration] hold-row write failed: %s", _conc_log_exc)
                try:
                    db.rollback()
                except Exception:
                    pass
            return
    except Exception as _conc_exc:
        logger.warning("[concentration] gate raised, continuing: %s", _conc_exc)

    opt = _resolve_option_details(sig, position_dollars)
    premium = opt["display_premium"]
    contract_count = opt["contract_count"]

    # Skip if sizing logic rejected the trade (DTE filter or 1-contract > budget)
    if contract_count <= 0:
        reject_reason = opt.get("reject_reason", "contract_count_zero")
        setup_label = "?"
        if sig.reason:
            try:
                setup_label = json.loads(sig.reason).get("setup", "?")
            except Exception:
                pass
        logger.warning(
            "[options:%s] SKIPPING %s %s setup=%s — reason=%s strike=%s exp=%s premium=%.2f budget=$%.0f",
            profile_name, sig.side, sig.symbol, setup_label,
            reject_reason, opt.get("strike_price"), opt.get("expiration_date"),
            premium, position_dollars,
        )
        return

    # fill_price_cents = total premium paid per contract (in cents)
    fill_cents = premium * 100

    logger.warning(
        "[options:%s] %s %s %s strike=%.2f exp=%s contracts=%d premium=%.2f total=$%.0f",
        profile_name, sig.side, sig.symbol, opt["option_type"],
        opt["strike_price"] or 0, opt["expiration_date"] or "?",
        contract_count, premium, premium * 100 * contract_count,
    )

    logger.warning(
        "[OPTIONS-EXEC:%s] CONFIRMED OPTIONS PATH — %s %s opt_type=%s contracts=%d "
        "strike=%.2f exp=%s premium=%.2f total=$%.0f",
        profile_name, sig.side, sig.symbol, opt["option_type"],
        contract_count, opt["strike_price"] or 0, opt["expiration_date"] or "?",
        premium, premium * 100 * contract_count,
    )
    try:
        pos = BotPosition(
            allocation_id=alloc.id,
            symbol=sig.symbol,
            qty=float(contract_count),
            avg_cost_cents=fill_cents,
            side="long" if sig.side == "buy" else "short",
            opened_at=now,
            closed_at=None,
            is_paper=True,
            stop_price_usd=None,
            target_price_usd=None,
            trailing_stop_activated=False,
            # Options fields
            option_type=opt["option_type"],
            strike_price=opt["strike_price"],
            expiration_date=opt["expiration_date"],
            underlying_symbol=opt["underlying_symbol"],
            contract_count=contract_count,
            contract_premium_cents=opt["contract_premium_cents"],
        )
        db.add(pos)
        db.flush()

        # Friction model: options pay slippage 5bps + $0.65/contract commission
        try:
            from app.services.friction import model_friction_cents, slippage_bps_for
            _opt_friction_cents = model_friction_cents(
                asset_class="options",
                qty=float(contract_count),
                fill_price_dollars=fill_cents / 100.0,
                contracts=float(contract_count),
            )
            _opt_slip_bps = float(slippage_bps_for("options"))
        except Exception:
            _opt_friction_cents = 0
            _opt_slip_bps = 0.0

        trade = BotTrade(
            allocation_id=alloc.id,
            symbol=sig.symbol,
            side=sig.side,
            qty=float(contract_count),
            fill_price_cents=fill_cents,
            fees_cents=_opt_friction_cents,
            ts=now,
            position_id=pos.id,
            signal_id=signal_id,
            is_paper=True,
            expected_fill_cents=fill_cents,
            slippage_bps=_opt_slip_bps,
            # Options fields
            option_type=opt["option_type"],
            strike_price=opt["strike_price"],
            expiration_date=opt["expiration_date"],
            underlying_symbol=opt["underlying_symbol"],
            contract_count=contract_count,
            contract_premium_cents=opt["contract_premium_cents"],
        )
        db.add(trade)
        db.commit()
        logger.info(
            "[options:%s] Opened %s × %d contracts %s @ $%.2f/contract (pos=%d trade=%d)",
            profile_name, sig.symbol, contract_count, opt["option_type"], premium, pos.id, trade.id,
        )
    except Exception as exc:
        logger.error("[options:%s] DB write failed for %s: %s", profile_name, sig.symbol, exc)
        try:
            db.rollback()
        except Exception:
            pass


# ── Signal execution (Step 4: open position at Alpaca paper) ─────────────────

def _execute_signal(db, alloc, sig, final_size_pct: float, profile: dict, profile_name: str, bars: dict | None = None, signal_id: int | None = None) -> None:
    """Place a simulated paper trade and persist BotPosition + BotTrade.

    Steps:
      1. Resolve equity — from Alpaca paper if creds available, else alloc capital
      2. Size the position (final_size_pct % of alloc capital)
      3. Compute stop/target from profile YAML rules
      4. Submit bracket order to Alpaca paper (best-effort; simulated fill if unavailable)
      5. Create BotPosition row (with stop_price_usd + target_price_usd)
      6. Create BotTrade row (entry fill)
    """
    import os

    if sig.side not in ("buy", "sell"):
        logger.info(
            "[exec] SKIP side=%s symbol=%s profile=%s — only buy/sell handled",
            sig.side, sig.symbol, profile_name,
        )
        return

    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade
    from strategy_lab.core.execution import compute_bracket_prices

    asset_class = profile.get("asset_class", "stock")
    _sig_strategy = (getattr(sig, "strategy", "") or "").strip()

    # Hard routing gate — log decision so Railway logs are proof
    logger.warning(
        "[ROUTE:%s] %s %s — asset_class=%r strategy=%r → path=%s",
        profile_name, sig.side, sig.symbol,
        asset_class, _sig_strategy,
        "OPTIONS" if asset_class == "options" else "EQUITY",
    )

    if asset_class == "options":
        _execute_options_signal(db, alloc, sig, final_size_pct, profile, profile_name, signal_id=signal_id)
        return
    now = datetime.now(timezone.utc)

    # 1. Resolve equity — skip Alpaca call when paper creds are absent to avoid
    #    a 10-second network timeout on every signal (which starves the scheduler).
    equity = 0.0
    broker = None
    _has_paper_creds = bool(
        (os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")).strip()
    )
    if _has_paper_creds:
        try:
            from strategy_lab.core.execution import get_broker
            broker = get_broker(asset_class)
            account = broker.get_account()
            equity = float(account.get("equity", 0.0))
        except Exception as exc:
            logger.warning("[execute:%s] broker.get_account failed: %s", profile_name, exc)
            broker = None

    if equity <= 0:
        # Fallback: use the allocation's configured paper capital
        equity = (alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000) / 100.0

    if equity <= 0:
        logger.warning("[execute:%s] no equity source for %s — skipping", profile_name, sig.symbol)
        return

    # Fetch live price from bar cache first (already in memory); broker positions as last resort
    entry_price = 0.0
    try:
        from app.services.live_prices import fetch_live_prices
        live_map = fetch_live_prices([sig.symbol])
        entry_price = float(live_map.get(sig.symbol, 0) or 0)
        if entry_price > 0:
            logger.debug("[execute:%s] live price %s = %.4f", profile_name, sig.symbol, entry_price)
    except Exception as exc:
        logger.warning("[execute:%s] live_prices failed for %s: %s", profile_name, sig.symbol, exc)

    if entry_price <= 0 and broker is not None:
        try:
            positions = broker.get_positions()
            for p in positions:
                if p.get("symbol") == sig.symbol and p.get("current_price", 0) > 0:
                    entry_price = float(p["current_price"])
                    break
        except Exception:
            pass

    bar_close_used = False
    bar_close_ts: float | None = None
    if entry_price <= 0:
        # Last resort: use the bar close the strategy used to generate the signal
        symbol_bars = (bars or {}).get(sig.symbol, [])
        if symbol_bars:
            last_bar = symbol_bars[-1]
            entry_price = float(last_bar["c"])
            bar_close_used = True
            bar_close_ts = float(last_bar.get("t", 0))
            logger.warning(
                "[execute:%s] live price unavailable for %s, using last bar close $%.4f",
                profile_name, sig.symbol, entry_price,
            )

    if entry_price <= 0:
        logger.warning("[execute:%s] no price for %s — skipping order (live=0, broker=0, bars_fallback=0)", profile_name, sig.symbol)
        return

    # Staleness guard: refuse the bar-close fallback if the bar is more than a
    # trading-session-worth old. 2h was too strict for options bots running pre-
    # and post-market — a legitimate close from earlier the same session would
    # trip it. The 20% deviation check below catches truly stale prices when a
    # live ticker is available; this is the belt for when it isn't.
    _STALE_BAR_MAX_HOURS = 6.0
    if bar_close_used and bar_close_ts and bar_close_ts > 0:
        import time as _time
        bar_age_hours = (_time.time() - bar_close_ts) / 3600
        if bar_age_hours > _STALE_BAR_MAX_HOURS:
            logger.error(
                "SANITY_FAIL: stale_bar_suspected for %s — bar close ts is %.1fh old, refusing trade "
                "(price=%.4f; use live ticker to avoid bad fill)",
                sig.symbol, bar_age_hours, entry_price,
            )
            return

    # Sanity check: cross-validate fill_price against live Kraken ticker.
    # Rejects trades where bar-close or other fallback is >20% off the real market price
    # (catches yfinance returning 730-day-old historical prices).
    try:
        from app.services.live_prices import fetch_live_prices as _flp_sanity
        _sanity_map = _flp_sanity([sig.symbol])
        _ticker_price = float(_sanity_map.get(sig.symbol, 0) or 0)
        if _ticker_price > 0:
            _deviation = abs(entry_price - _ticker_price) / _ticker_price
            if _deviation > 0.20:
                logger.error(
                    "SANITY_FAIL: stale_bar_suspected for %s — fill_price=%.4f deviates %.1f%% "
                    "from live ticker %.4f; refusing trade",
                    sig.symbol, entry_price, _deviation * 100, _ticker_price,
                )
                return
            # If ticker is fresher and live_prices originally returned 0, upgrade to ticker price
            if bar_close_used and _ticker_price > 0:
                logger.info(
                    "[execute:%s] upgrading fill price %s from bar-close %.4f to live ticker %.4f",
                    profile_name, sig.symbol, entry_price, _ticker_price,
                )
                entry_price = _ticker_price
    except Exception as _sanity_exc:
        logger.warning("[execute:%s] sanity check fetch failed for %s: %s", profile_name, sig.symbol, _sanity_exc)

    logger.info("[execute:%s] entry_price=%s=%.4f equity=%.2f", profile_name, sig.symbol, entry_price, equity)

    # 2. Size: pct of bot capital (capital_cents_within_portfolio or starting capital)
    capital_usd = (alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000) / 100.0
    _raw_flag = os.getenv("ENABLE_DEPLOYMENT_TARGET_SIZING", "false").strip().lower()
    _use_deployment_sizer = _raw_flag == "true"
    if _use_deployment_sizer:
        from strategy_lab.core.deployment_sizer import compute_per_trade_notional
        position_dollars = compute_per_trade_notional(alloc, profile, db, capital_usd, profile_name)
        if position_dollars == 0.0:
            logger.warning(
                "[sizing] %s %s — deployment cap reached, skipping entry",
                profile_name, sig.symbol,
            )
            return
    else:
        position_dollars = capital_usd * (final_size_pct / 100.0)
    logger.warning(
        "[sizing-mode] %s %s: enabled=%s notional=%.2f capital=%.0f",
        profile_name, sig.symbol, _use_deployment_sizer, position_dollars, capital_usd,
    )

    # ── Phase 5: per-user concentration / sector / cluster gates ────────────
    # Stacked, fail-fast. On reject we write a bot_signals hold row so the
    # decision is visible in the signal log and bail before qty/order.
    try:
        from strategy_lab.core.concentration_gate import check_concentration
        from app.db.models.bots import BotSignal as _BotSig_conc
        _allowed_conc, _conc_reason = check_concentration(
            db,
            user_id=int(alloc.user_id),
            allocation_id=int(alloc.id),
            symbol=sig.symbol,
            proposed_notional=float(position_dollars),
            profile=profile or {},
        )
        if not _allowed_conc:
            logger.warning(
                "[concentration] %s %s blocked: %s",
                profile_name, sig.symbol, _conc_reason,
            )
            try:
                db.add(_BotSig_conc(
                    allocation_id=alloc.id,
                    ts=now,
                    symbol=sig.symbol,
                    side="hold",
                    confidence=float(getattr(sig, "confidence", 0.0) or 0.0),
                    reason=f"concentration: {_conc_reason}",
                    strategy=getattr(sig, "strategy", None),
                    entry_price=entry_price if entry_price > 0 else None,
                ))
                db.commit()
            except Exception as _conc_log_exc:
                logger.warning("[concentration] hold-row write failed: %s", _conc_log_exc)
                try:
                    db.rollback()
                except Exception:
                    pass
            return
    except Exception as _conc_exc:
        logger.warning("[concentration] gate raised, continuing: %s", _conc_exc)

    qty = round(position_dollars / entry_price, 6)
    if qty <= 0:
        return

    is_short = sig.side == "sell"

    # ── Per-name concentration cap (3% of fleet NAV) ──────────────────────
    # Reject longs that would push single-name exposure over the cap.
    # No-op if fleet NAV is unavailable (fresh deploy / empty nav_history)
    # so trading doesn't grind to a halt on a missing baseline.
    if not is_short:
        try:
            from app.services.concentration import check_per_name_cap
            new_notional_cents = int(round(position_dollars * 100))
            allowed, conc_reason, conc_details = check_per_name_cap(
                db, sig.symbol, new_notional_cents,
            )
            if not allowed:
                logger.warning(
                    "[concentration] REJECT %s %s: %s details=%s",
                    profile_name, sig.symbol, conc_reason, conc_details,
                )
                try:
                    from app.services.discord import send_ops_alert
                    send_ops_alert(
                        title="[concentration] entry rejected",
                        message=(
                            f"{profile_name} {sig.side} {sig.symbol} rejected: "
                            f"would push exposure to "
                            f"{conc_details['post_exposure_pct']:.2f}% (cap {conc_details['cap_pct']:.2f}%)"
                        ),
                        severity="warn",
                        source="runner.concentration_cap",
                        fields=[
                            {"name": "Symbol",       "value": sig.symbol, "inline": True},
                            {"name": "Cap %",        "value": f"{conc_details['cap_pct']:.2f}", "inline": True},
                            {"name": "Post-entry %", "value": f"{conc_details['post_exposure_pct']:.2f}", "inline": True},
                        ],
                    )
                except Exception:
                    pass
                return
        except Exception as conc_exc:
            logger.warning("[concentration] check raised, continuing: %s", conc_exc)

    # 3. Compute stop and target from profile rules (reversed for shorts)
    if is_short:
        _sl_pct = abs(profile.get("stop_loss_pct", 8.0)) / 100
        _tp_pct = abs(profile.get("take_profit_pct", 18.0)) / 100
        stop_price = round(entry_price * (1 + _sl_pct), 8)
        target_price = round(entry_price * (1 - _tp_pct), 8)
    else:
        stop_price, target_price = compute_bracket_prices(entry_price, profile)

    # 4. Submit bracket order to Alpaca (best-effort — sim fill if unavailable)
    _in_ext_hours = (
        asset_class not in ("crypto", "crypto_intraday", "quant")
        and profile.get("execution", {}).get("extended_hours")
        and _current_et_session() != "regular"
    )
    # order_id stays None when broker is unavailable or submit fails — the DB rows
    # are still created as a simulated paper fill.  alpaca_order_id=null in bot_trades
    # is the expected state when Alpaca paper creds are present but the API rejects the
    # order (e.g. market closed for crypto doesn't exist, but position sizing edge cases).
    order_id: str | None = None
    if broker is not None:
        try:
            result = broker.submit_bracket_order(
                symbol=sig.symbol,
                qty=qty,
                side="sell" if is_short else "buy",
                stop_price=stop_price,
                target_price=target_price,
                extended_hours=_in_ext_hours,
            )
            order_id = result.get("order_id")
        except Exception as exc:
            logger.warning("[execute:%s] bracket_order failed for %s: %s", profile_name, sig.symbol, exc)
            # Fall through — still create DB rows as simulated paper fill

    fill_cents = entry_price * 100  # float — preserves sub-penny precision (e.g. SHIB)

    # 5–6. Create BotPosition + BotTrade — wrapped so a DB error can't corrupt the
    # session and block all subsequent signals in this scan cycle.
    try:
        # Ensure every entry trade has a signal_id — synthetic backfill if upstream log_signal failed
        if signal_id is None:
            try:
                from app.db.models.bots import BotSignal as _BotSig
                _syn = _BotSig(
                    allocation_id=alloc.id,
                    ts=now,
                    symbol=sig.symbol,
                    side=sig.side,
                    confidence=sig.confidence,
                    reason=getattr(sig, "reason", "synthetic_backfill") or "synthetic_backfill",
                    strategy=getattr(sig, "strategy", None),
                    entry_price=entry_price if entry_price > 0 else None,
                )
                db.add(_syn)
                db.flush()
                signal_id = _syn.id
                logger.warning(
                    "[execute:%s] synthetic signal created for %s %s (log_signal failed upstream)",
                    profile_name, sig.side, sig.symbol,
                )
            except Exception as _syn_exc:
                logger.error(
                    "[execute:%s] INTEGRITY: trade proceeding WITHOUT signal_id for %s %s: %s",
                    profile_name, sig.side, sig.symbol, _syn_exc,
                )

        pos = BotPosition(
            allocation_id=alloc.id,
            symbol=sig.symbol,
            qty=qty,
            avg_cost_cents=fill_cents,
            side="short" if is_short else "long",
            opened_at=now,
            closed_at=None,
            is_paper=True,
            stop_price_usd=stop_price,
            target_price_usd=target_price,
            trailing_stop_activated=False,
        )
        db.add(pos)
        db.flush()  # get pos.id

        # ── Friction model (slippage + commission) ─────────────────────
        # Apply per-asset-class friction so the headline Sharpe isn't
        # inflated by zero-cost paper fills. Written to fees_cents — the
        # existing column already subtracted from realized P&L by
        # canonical.compute_bot_snapshot.
        try:
            from app.services.friction import model_friction_cents, slippage_bps_for
            _friction_cents = model_friction_cents(
                asset_class=asset_class,
                qty=qty,
                fill_price_dollars=entry_price,
            )
            _slip_bps = float(slippage_bps_for(asset_class))
        except Exception:
            _friction_cents = 0
            _slip_bps = 0.0

        trade = BotTrade(
            allocation_id=alloc.id,
            symbol=sig.symbol,
            side="short" if is_short else "buy",  # "short" marks entry; "cover" marks exit
            qty=qty,
            fill_price_cents=fill_cents,
            fees_cents=_friction_cents,
            ts=now,
            position_id=pos.id,
            signal_id=signal_id,
            is_paper=True,
            alpaca_order_id=order_id,
            expected_fill_cents=fill_cents,
            slippage_bps=_slip_bps,
        )
        db.add(trade)
        db.commit()
    except Exception as _db_exc:
        logger.error("[execute:%s] DB write failed for %s: %s", profile_name, sig.symbol, _db_exc)
        try:
            db.rollback()
        except Exception:
            pass
        return

    # For institutional bots: ensure stop is set using risk_management config
    if profile_name in ("stock_day", "stock_swing"):
        try:
            from strategy_lab.core.stop_management import place_initial_stop
            _rm = profile.get("risk_management", {})
            _stop_pct = float(_rm.get("stop_loss_pct", profile.get("stop_loss_pct", 7.0)))
            place_initial_stop(db, pos.id, entry_price, _stop_pct)
        except Exception as exc:
            logger.warning("[execute:%s] place_initial_stop failed for %s: %s",
                           profile_name, sig.symbol, exc)

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
    """Map profile name to bot cadence: 'day' | 'swing' | 'lt'.

    Quant bots run on 5min/15min bars with intraday signals → 'day' cadence
    so MTF confluence uses short-window SMA slices, not daily/weekly/monthly.
    """
    if "lt" in profile_name:
        return "lt"
    # Options bots have their own multi-factor gates — MTF always passes.
    if "options" in profile_name or "income" in profile_name or "directional" in profile_name:
        return "lt"
    # Intraday bots: day-trading + quant strategies (5 min cadence, 15m bars)
    if "day" in profile_name or "quant" in profile_name:
        return "day"
    return "swing"
