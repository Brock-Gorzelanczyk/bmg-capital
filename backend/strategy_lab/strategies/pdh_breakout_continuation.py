"""PDH Breakout Continuation — long-only.

Thesis: Previous Day High (PDH) is the most-watched intraday resistance.
When today's bar prints a high above PDH on above-average volume AND
closes near PDH with the day's low staying above PDH, the level has
been accepted as the new support. Entry on the pullback to PDH.

Regime: bull_trending. The discipline filter's regime gate downweights
this strategy outside bull/up regimes.

Active hours: 10:00-15:00 ET (intraday only). On daily-bar bots the
guard is a no-op — the swing scan fires once after market close.

Edge cases handled:
  - Symbol with no prior data (< 25 bars): skip
  - Today bar with zero high/low/close: skip
  - PDH == today's low (no pullback room): skip
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "pdh_breakout_continuation"

MIN_BARS = 25
ATR_PERIOD = 14
PULLBACK_MAX_ATR = 0.30           # close must be within 0.3 ATR of PDH (pullback zone)
VOLUME_MULTIPLE_REQUIRED = 1.2    # break-day volume vs recent 20-bar average
MAX_CONFIDENCE = 0.80


def _et_hour_now() -> int:
    return (datetime.now(timezone.utc).hour - 4) % 24


def _is_intraday_timeframe(bars_for_symbol: list) -> bool:
    if len(bars_for_symbol) < 2:
        return False
    try:
        ts1 = datetime.fromisoformat(str(bars_for_symbol[-1]["ts"]).replace("Z", "+00:00"))
        ts2 = datetime.fromisoformat(str(bars_for_symbol[-2]["ts"]).replace("Z", "+00:00"))
        delta_min = abs((ts1 - ts2).total_seconds()) / 60.0
        return delta_min < 240
    except Exception:
        return False


def _atr(bars: list, period: int = ATR_PERIOD) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(len(bars) - period, len(bars)):
        if i == 0:
            continue
        cur = bars[i]
        prev = bars[i - 1]
        h = float(cur.get("h", 0) or 0)
        l = float(cur.get("l", 0) or 0)
        prev_c = float(prev.get("c", 0) or 0)
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return (sum(trs) / len(trs)) if trs else 0.0


def _mtf_alignment(closes: list[float]) -> float:
    """Coarse multi-timeframe alignment proxy: today.close > 5-bar SMA > 20-bar SMA → 1.0."""
    if len(closes) < 25:
        return 0.5
    today = closes[-1]
    sma5 = sum(closes[-5:]) / 5.0
    sma20 = sum(closes[-20:]) / 20.0
    if today > sma5 > sma20:
        return 1.0
    if today > sma5:
        return 0.7
    if today > sma20:
        return 0.5
    return 0.2


def _spy_direction(bars: dict) -> Optional[bool]:
    """Returns True if SPY's most recent bar closed higher than the previous bar."""
    spy = bars.get("SPY") or bars.get("SPY/USD")
    if not spy or len(spy) < 2:
        return None
    try:
        c_now = float(spy[-1].get("c", 0))
        c_prev = float(spy[-2].get("c", 0))
        if c_now <= 0 or c_prev <= 0:
            return None
        return c_now > c_prev
    except Exception:
        return None


def _build_signal_for_symbol(symbol: str, bar_list: list, spy_up: Optional[bool]) -> Optional[Signal]:
    if not bar_list or len(bar_list) < MIN_BARS:
        return None

    today = bar_list[-1]
    yesterday = bar_list[-2]

    pdh = float(yesterday.get("h", 0) or 0)
    if pdh <= 0:
        return None

    today_h = float(today.get("h", 0) or 0)
    today_l = float(today.get("l", 0) or 0)
    today_c = float(today.get("c", 0) or 0)
    today_v = float(today.get("v", 0) or 0)
    if today_h <= 0 or today_l <= 0 or today_c <= 0:
        return None

    # 1. Today made a new high above PDH (acceptance)
    if today_h <= pdh:
        return None

    # 2. Volume confirmation (today vs recent 20-bar average, excluding today)
    recent_vols = [float(b.get("v", 0) or 0) for b in bar_list[-21:-1]]
    avg_vol = (sum(recent_vols) / len(recent_vols)) if recent_vols else 0.0
    if avg_vol <= 0:
        return None
    break_vol_ratio = today_v / avg_vol
    if break_vol_ratio < VOLUME_MULTIPLE_REQUIRED:
        return None

    # 3. ATR-normalized pullback distance — close must be within 0.3 ATR of PDH
    atr = _atr(bar_list)
    if atr <= 0:
        return None
    pullback_distance_atr = abs(today_c - pdh) / atr
    if pullback_distance_atr > PULLBACK_MAX_ATR:
        return None

    # 4. Today's low held above PDH (level became support)
    if today_l <= pdh:
        return None

    # ── Confidence + reason payload ──
    vol_excess = break_vol_ratio - VOLUME_MULTIPLE_REQUIRED
    proximity_score = (PULLBACK_MAX_ATR - pullback_distance_atr) / PULLBACK_MAX_ATR
    confidence = min(MAX_CONFIDENCE, 0.55 + 0.10 * vol_excess + 0.10 * proximity_score)

    closes = [float(b.get("c", 0) or 0) for b in bar_list[-25:]]
    mtf = _mtf_alignment(closes)

    # cross_asset_agree: SPY up on the most recent bar → confirms broad market bid
    if spy_up is None:
        cross_agree = False
    else:
        cross_agree = bool(spy_up)

    reason_payload = {
        "setup": "pdh_breakout_continuation",
        "pdh": round(pdh, 4),
        "break_volume_ratio": round(break_vol_ratio, 2),
        "atr_distance_from_pdh": round(pullback_distance_atr, 3),
        "volume_agreement": round(min(1.0, vol_excess / 0.8 + 0.4), 2),
        "mtf_alignment": round(mtf, 2),
        "cross_asset_agree": cross_agree,
    }

    return Signal(
        symbol=symbol,
        side="buy",
        confidence=round(confidence, 3),
        size_hint=0.05,
        strategy=STRATEGY_NAME,
        reason=json.dumps(reason_payload),
    )


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if not bars:
        return []

    # Active hours guard — intraday only
    sample_sym = next(iter(bars))
    if _is_intraday_timeframe(bars.get(sample_sym, [])):
        h_et = _et_hour_now()
        if not (10 <= h_et < 15):
            return []

    spy_up = _spy_direction(bars)
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list, spy_up)
            if sig is not None:
                out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out
