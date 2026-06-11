"""CANDIDATE — not scheduled. Graduate manually after paper trading.
Strategy: Cycle-Aware Altcoin Momentum Rotation

Uses the crypto cycle phase and BTC dominance rotation stage to select which
altcoins to hold, then ranks them by 28-day risk-adjusted momentum (return /
volatility). Applies token unlock suppression to avoid entering pre-cliff events.

Rotation stage ladder (based on BTC dominance):
  Stage 1 (BTC dom >55%): BTC/ETH only
  Stage 2 (50-55%):       Add SOL, AVAX, BNB, ADA
  Stage 3 (46-50%):       Add DOT, NEAR, ATOM, ARB, OP, SUI, APT
  Stage 4 (42-46%):       Add LINK, UNI, AAVE
  Stage 5 (<=42%):        Reduce all sizes 50%, no new positions

References:
  - Altcoin cycle theory: BTC season → ETH season → large caps → mid caps → memes
  - Risk-adjusted momentum: Sharpe-proxy ranking for cross-sectional selection
"""
from __future__ import annotations

import logging
import statistics
from typing import List

from strategy_lab.core.signals import Signal
from strategy_lab.core.crypto_signal_aggregator import get_crypto_regime_snapshot
from strategy_lab.core.altdata.token_unlock_monitor import should_suppress_buy

logger = logging.getLogger(__name__)

STRATEGY_NAME = "altcoin_cycle_rotation"
TOP_N = 3
LOOKBACK_DAYS = 28
MIN_CONFIDENCE = 0.55

# Rotation stage universe (ordered: smaller stage = more conservative)
_STAGE_UNIVERSES: dict[int, list[str]] = {
    1: ["BTC-USD", "ETH-USD"],
    2: ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "BNB-USD", "ADA-USD"],
    3: [
        "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "BNB-USD", "ADA-USD",
        "DOT-USD", "NEAR-USD", "ATOM-USD", "ARB-USD", "OP-USD", "SUI-USD", "APT-USD",
    ],
    4: [
        "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "BNB-USD", "ADA-USD",
        "DOT-USD", "NEAR-USD", "ATOM-USD", "ARB-USD", "OP-USD", "SUI-USD", "APT-USD",
        "LINK-USD", "UNI-USD", "AAVE-USD",
    ],
    5: [
        "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "BNB-USD", "ADA-USD",
        "DOT-USD", "NEAR-USD", "ATOM-USD", "ARB-USD", "OP-USD", "SUI-USD", "APT-USD",
        "LINK-USD", "UNI-USD", "AAVE-USD",
    ],
}


def _trailing_return(closes: list[float], lookback: int) -> float | None:
    """Compute trailing return over `lookback` periods. Returns None if insufficient data."""
    if len(closes) < lookback:
        return None
    p0 = closes[-lookback]
    if p0 <= 0:
        return None
    return (closes[-1] - p0) / p0


def _trailing_volatility(closes: list[float], lookback: int) -> float:
    """Compute std-dev of daily returns over `lookback` periods. Returns 0.001 floor."""
    if len(closes) < lookback + 1:
        return 0.001
    daily_returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(max(1, len(closes) - lookback), len(closes))
        if closes[i - 1] > 0
    ]
    if len(daily_returns) < 2:
        return 0.001
    try:
        return max(statistics.stdev(daily_returns), 0.001)
    except statistics.StatisticsError:
        return 0.001


def _risk_adjusted_momentum(closes: list[float], lookback: int) -> float | None:
    """28-day return / 28-day volatility (Sharpe-proxy)."""
    ret = _trailing_return(closes, lookback)
    if ret is None:
        return None
    vol = _trailing_volatility(closes, lookback)
    return ret / vol


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    """
    Generate buy/sell signals for the altcoin cycle rotation strategy.

    Parameters
    ----------
    bars          : {symbol: [bar_dict, ...]} — bar_dicts have "c" (close) key
    profile_config: strategy profile settings
    regime        : market regime dict (passed by runner; may be ignored in favour of fresh snapshot)

    Returns
    -------
    List[Signal] — empty list if cycle is unfavourable.
    """
    # ── Step 1: Get fresh crypto regime snapshot ──────────────────────────────
    try:
        snapshot = get_crypto_regime_snapshot()
    except Exception as exc:
        logger.warning("[%s] get_crypto_regime_snapshot failed: %s", STRATEGY_NAME, exc)
        return []

    cycle_phase = snapshot.get("cycle_phase", "mid_bull")
    rotation_stage = snapshot.get("rotation_stage", 2)
    position_size_multiplier = snapshot.get("combined_size_multiplier", 1.0)

    # Do not trade in distribution or bear phases
    if cycle_phase in ("distribution", "bear"):
        logger.info("[%s] Cycle phase=%s — no new positions", STRATEGY_NAME, cycle_phase)
        return []

    # ── Step 2: Determine allowed universe for this rotation stage ────────────
    allowed_symbols = set(_STAGE_UNIVERSES.get(rotation_stage, _STAGE_UNIVERSES[2]))

    # Stage 5: reduce sizes by 50% and do not open new positions
    stage5_mode = rotation_stage == 5

    # ── Step 3 & 4: Compute risk-adjusted momentum for eligible symbols ───────
    scores: dict[str, float] = {}
    raw_returns: dict[str, float] = {}

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue

        # Normalize: "BTC/USD" or "BTC-USD" or "BTCUSD"
        sym_normalized = symbol.upper().replace("/", "-")
        if sym_normalized not in allowed_symbols:
            continue

        # Token unlock suppression
        ticker = sym_normalized.split("-")[0]
        try:
            if should_suppress_buy(ticker, days_ahead=14):
                logger.info("[%s] Suppressing %s — cliff unlock within 14d", STRATEGY_NAME, symbol)
                continue
        except Exception as exc:
            logger.debug("[%s] Token unlock check failed for %s: %s", STRATEGY_NAME, symbol, exc)

        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < LOOKBACK_DAYS:
            continue

        ram = _risk_adjusted_momentum(closes, LOOKBACK_DAYS)
        ret = _trailing_return(closes, LOOKBACK_DAYS)
        if ram is not None and ret is not None:
            scores[sym_normalized] = ram
            raw_returns[sym_normalized] = ret

    if not scores:
        logger.info("[%s] No eligible symbols with momentum data", STRATEGY_NAME)
        return []

    # ── Step 5: Absolute momentum gate ───────────────────────────────────────
    positive_scores = {s: r for s, r in scores.items() if raw_returns.get(s, 0) > 0}
    if not positive_scores:
        logger.info("[%s] All symbols have negative 28d return — no signals", STRATEGY_NAME)
        return []

    if stage5_mode:
        logger.info("[%s] Stage 5 mode: no new positions", STRATEGY_NAME)
        # Still generate exit signals below
        top_symbols = set()
    else:
        # ── Step 6: Rank by risk-adjusted momentum, take top N ─────────────────
        ranked = sorted(positive_scores, key=lambda s: positive_scores[s], reverse=True)
        top_symbols = set(ranked[:TOP_N])

    out: List[Signal] = []

    if not stage5_mode:
        confidence_by_rank = {0: 0.65, 1: 0.60, 2: 0.55}
        top_list = sorted(positive_scores, key=lambda s: positive_scores[s], reverse=True)[:TOP_N]
        for rank, sym in enumerate(top_list):
            confidence = confidence_by_rank.get(rank, MIN_CONFIDENCE)
            if confidence < MIN_CONFIDENCE:
                continue
            size_hint = min(1.0, position_size_multiplier * 0.33)
            out.append(Signal(
                symbol=sym,
                side="buy",
                confidence=round(confidence, 4),
                size_hint=round(min(size_hint, 1.0), 4),
                reason=f"cycle_rotation_stage_{rotation_stage}",
                strategy=STRATEGY_NAME,
            ))

    # ── Step 7: Exit signals for symbols no longer qualifying ─────────────────
    # Symbols currently in bars that were previously held but no longer in top N
    # or have negative momentum — generate sell/exit signals.
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        sym_normalized = symbol.upper().replace("/", "-")
        if sym_normalized not in allowed_symbols:
            continue
        # Only generate exits for symbols with data but not in top selection
        ret = raw_returns.get(sym_normalized)
        if sym_normalized not in top_symbols and ret is not None and ret <= 0:
            out.append(Signal(
                symbol=sym_normalized,
                side="sell",
                confidence=0.55,
                size_hint=1.0,  # close full position
                reason=f"cycle_rotation_exit_stage_{rotation_stage}_neg_momentum",
                strategy=STRATEGY_NAME,
            ))

    return out
