"""
CANDIDATE — not scheduled. 10-ETF monthly momentum rotation.
Reference: Antonacci, Global Equities Momentum (2014)
"""
from __future__ import annotations

import logging
import numpy as np

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "name": "Cross-Asset Momentum",
    "asset_class": "multi",
    "style": "cross_asset_momentum",
    "data_source": "yfinance",
    "expected_sharpe": "0.7-1.0",
    "academic_refs": ["Antonacci (2014) Global Equities Momentum"],
    "promotion_minimum_paper_trades": 30,
    "promotion_minimum_days_observed": 60,
    "universe_hint": ["SPY", "QQQ", "EEM", "TLT", "GLD", "PDBC",
                      "UUP", "VNQ", "HYG", "TIP"],
}

STRATEGY_NAME = "cross_asset_momentum"
TOP_N = 3
LOOKBACKS = [21, 63, 252]
ABSOLUTE_FILTER_DAYS = 126
MIN_BARS = 270


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    cfg = profile_config.get("cross_asset_momentum", {})
    top_n = cfg.get("top_n", TOP_N)

    credit_mult = 1.0
    try:
        from strategy_lab.core.altdata.credit_spread_signal import get_credit_regime
        credit_mult = get_credit_regime()["equity_multiplier"]
    except Exception:
        pass

    scores: dict[str, float] = {}
    absolute_pass: dict[str, bool] = {}

    for symbol, bar_list in bars.items():
        closes = [float(b.get("c", 0) or 0) for b in bar_list if b.get("c")]
        if len(closes) < MIN_BARS:
            continue
        mom_scores = []
        for lb in LOOKBACKS:
            if len(closes) > lb:
                ret = (closes[-1] - closes[-(lb + 1)]) / closes[-(lb + 1)]
                mom_scores.append(ret)
        if not mom_scores:
            continue
        scores[symbol] = float(np.mean(mom_scores))
        if len(closes) > ABSOLUTE_FILTER_DAYS:
            abs_ret = (closes[-1] - closes[-(ABSOLUTE_FILTER_DAYS + 1)]) / closes[-(ABSOLUTE_FILTER_DAYS + 1)]
            absolute_pass[symbol] = abs_ret > 0
        else:
            absolute_pass[symbol] = False

    eligible = {s: v for s, v in scores.items() if absolute_pass.get(s, False)}

    if not eligible:
        return [
            Signal(
                symbol=s, side="hold", confidence=0.0, size_hint=0.0,
                reason="cross_asset_mom: all below absolute filter — cash mode",
                strategy=STRATEGY_NAME,
            )
            for s in bars
        ]

    ranked = sorted(eligible.items(), key=lambda x: x[1], reverse=True)
    top_symbols = {s for s, _ in ranked[:top_n]}
    signals = []
    for symbol in bars:
        if symbol in top_symbols:
            rank_pos = next(i for i, (s, _) in enumerate(ranked) if s == symbol)
            confidence = min(1.0, max(0.60, (0.80 - rank_pos * 0.05)) * credit_mult)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=confidence,
                size_hint=1.0 / top_n,
                reason=(
                    f"cross_asset_mom: rank {rank_pos + 1} "
                    f"score={scores[symbol]:.3f} credit_mult={credit_mult:.2f}"
                ),
                strategy=STRATEGY_NAME,
            ))
        else:
            signals.append(Signal(
                symbol=symbol, side="hold", confidence=0.0, size_hint=0.0,
                reason="cross_asset_mom: not in top-N",
                strategy=STRATEGY_NAME,
            ))
    return signals
