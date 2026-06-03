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

            # 6. Fetch bars (stub: empty dict; real bar-fetch wired in data-feed phase)
            # When the data feed is available, this will call bar_fetcher.fetch(profile)
            bars: dict[str, list[dict]] = {}

            # 7. Run generate_signals for each strategy module in profile
            strategy_names: list[str] = profile.get("strategies", [])
            if not strategy_names:
                strategy_names = [_primary_strategy(profile_name)]

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
                    signals_by_strategy.append(strat_signals or [])
                    strategies_loaded += 1
                    logger.debug(
                        "[runner:%s] %s → %d signals",
                        profile_name, strat_name, len(strat_signals or []),
                    )
                except Exception as exc:
                    logger.error(
                        "[runner:%s] Strategy '%s' raised: %s",
                        profile_name, strat_name, exc, exc_info=True,
                    )
                    signals_by_strategy.append([])

            # Fallback stub signal when no strategies returned anything
            if not any(signals_by_strategy):
                from strategy_lab.core.signals import Signal
                default_symbol = _default_symbol_for_profile(profile_name, profile)
                signals_by_strategy = [[Signal(
                    symbol=default_symbol,
                    side="hold",
                    confidence=0.5,
                    size_hint=1.0,
                    reason="No strategy signals — stub hold",
                    strategy=_primary_strategy(profile_name),
                )]]

            # 8. Apply ensemble vote
            ensemble = profile.get("ensemble", "weighted_vote")
            signals = _apply_ensemble(ensemble, signals_by_strategy, max(1, strategies_loaded))

            # 9. Apply risk overlay (graceful — may not be built yet)
            try:
                from strategy_lab.core.risk_overlay import apply_overlay  # type: ignore
                signals = apply_overlay(signals, profile, regime, db) or signals
            except (ImportError, Exception) as exc:
                logger.debug("[runner:%s] risk_overlay unavailable: %s", profile_name, exc)

            # 10. Audit non-hold signals
            from strategy_lab.core.audit import log_signal

            actionable = [s for s in signals if s.side != "hold"]
            for alloc in allocations:
                for sig in actionable:
                    log_signal(db, alloc.id, sig)

            # 11. Build and persist audit record
            regime_snapshot = json.dumps(regime, default=str) if regime else "{}"
            audit_record = {
                "profile": profile_name,
                "strategies_loaded": strategies_loaded,
                "ensemble": ensemble,
                "signals_total": len(signals),
                "signals_actionable": len(actionable),
                "regime_snapshot": regime_snapshot,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            logger.info("[runner:%s] Audit: %s", profile_name, audit_record)

            return {
                "profile": profile_name,
                "allocations": len(allocations),
                "signals": len(actionable),
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
