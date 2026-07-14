"""Gap Fade Intraday — fade opening gaps > 2%.

Thesis: opening gaps often over-react to overnight news. Fading gaps of
2%+ (in either direction) captures the intraday reversion to VWAP that
happens as the tape absorbs the imbalance and initial reactive traders
get shaken out.

Entry rules:
  - Gap magnitude ≥ 2% (open vs prior close)
  - Time-of-day: signal fires when called any time during market hours;
    caller (bot_scheduler) constrains the entry window to 9:35-10:00 ET
    via cron. This module only checks that the fade setup is present.
  - Direction: fade the gap. Gap up → short. Gap down → buy.

Exit rules (managed by execution layer, not this module):
  - Stop: 1× the gap magnitude beyond entry
  - Target: 2R (mean-reversion to prior close or VWAP)
  - Time stop: 3:45 PM ET (caller responsibility)

Sizing: 5% of allocation per trade (set at profile level, not here).

Returns a Signal with:
  side="sell" for gap-up (fade short) or "buy" for gap-down (fade long)
  confidence: scaled 0.55-0.85 based on gap magnitude
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "gap_fade_intraday"

# 2026-07-02: entry thresholds. Same aggressive-tuning philosophy as the
# 2026-07-01 options overhaul — go easy on the entry gate so the strategy
# fires; execution layer manages risk.
MIN_GAP_PCT   = 0.010   # 2026-07-13 fire-more: was 2.0%, dropped to 1.0%
                         # — stock_gap_fade had 0 trades in 10 days at
                         # 2% gap threshold. 1% gaps happen 3-5× more
                         # often, execution layer risk-manages exits.
MAX_GAP_PCT   = 0.15    # 15% max — beyond this, the news is real (M&A etc.)
BASE_SIZE     = 0.05    # 5% position size hint


def _detect_gap(closes: list[float], opens: list[float]) -> Optional[dict]:
    """Return gap dict if today's open gaps >= MIN_GAP_PCT vs prior close.

    Expects the last element of `opens` to be today's open, and the
    second-to-last element of `closes` to be yesterday's close.
    """
    if len(closes) < 2 or len(opens) < 1:
        return None
    prior_close = closes[-2]
    today_open  = opens[-1]
    if prior_close <= 0 or today_open <= 0:
        return None
    gap_pct = (today_open - prior_close) / prior_close
    if abs(gap_pct) < MIN_GAP_PCT or abs(gap_pct) > MAX_GAP_PCT:
        return None
    return {
        "prior_close": prior_close,
        "today_open":  today_open,
        "gap_pct":     round(gap_pct * 100, 2),
        "gap_up":      gap_pct > 0,
    }


def _confidence_from_gap(gap_pct_abs: float) -> float:
    """Scale confidence 0.55-0.85 as gap grows 2% → 6% (past that, plateau)."""
    normalized = min(1.0, max(0.0, (gap_pct_abs - 0.02) / 0.04))
    return round(0.55 + 0.30 * normalized, 3)


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    # Regime guard: skip fading gaps during panic (news drives moves further)
    if regime.get("vix_regime") == "panic":
        return out
    for symbol, bar_list in bars.items():
        if not bar_list or len(bar_list) < 2:
            continue
        closes = [float(b.get("c") or b.get("close") or 0) for b in bar_list]
        opens  = [float(b.get("o") or b.get("open") or 0) for b in bar_list]
        gap = _detect_gap(closes, opens)
        if gap is None:
            continue
        # Fade — gap up → sell (expect down), gap down → buy (expect up)
        side = "sell" if gap["gap_up"] else "buy"
        conf = _confidence_from_gap(abs(gap["gap_pct"]) / 100.0)
        reason = json.dumps({
            "setup":       "gap_fade_intraday",
            "gap_pct":     gap["gap_pct"],
            "prior_close": round(gap["prior_close"], 2),
            "today_open":  round(gap["today_open"], 2),
            "direction":   "short_gap_up" if gap["gap_up"] else "long_gap_down",
            "manage":      "1x gap magnitude stop, 2R target, EOD flat",
        })
        out.append(Signal(
            symbol=symbol,
            side=side,
            confidence=conf,
            size_hint=BASE_SIZE,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
    return out
