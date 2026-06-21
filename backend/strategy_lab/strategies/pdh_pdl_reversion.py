"""PDH/PDL Reversion — fade approaches without volume confirmation.

Thesis: On range-bound days, price respects the prior day's high/low.
When price approaches PDH from below (or PDL from above) WITHOUT a
volume spike, the move is likely to fail — fade it back to the
PDH-PDL midpoint.

Regime: choppy. The discipline filter's regime gate downweights this
in trending markets where breakouts dominate.

Active hours: 10:00-15:00 ET (intraday only). On daily-bar bots the
guard is a no-op — the swing scan fires once after market close.

Edge cases handled:
  - Symbol with no prior data (< 25 bars): skip
  - PDH == PDL (rare 0-range day, halted): skip
  - Today actually breaks the level (high > PDH or low < PDL): skip,
    that's a breakout setup, not a reversion
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "pdh_pdl_reversion"

MIN_BARS = 25
ATR_PERIOD = 14
APPROACH_MAX_ATR = 0.20         # current price must be within 0.20 ATR of the level
VOLUME_RATIO_MAX = 0.80         # current volume must be < 0.80 × avg (no spike)
FAILED_BREAK_LOOKBACK = 3
MAX_CONFIDENCE = 0.75


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


def _ranging_mtf_score(closes: list[float]) -> float:
    """1.0 = market is ranging (sma5 close to sma20). 0.0 = strong trend."""
    if len(closes) < 25:
        return 0.5
    sma5 = sum(closes[-5:]) / 5.0
    sma20 = sum(closes[-20:]) / 20.0
    if sma20 <= 0:
        return 0.5
    divergence_pct = abs(sma5 - sma20) / sma20 * 100
    # 0% divergence → 1.0 score; 3%+ divergence → 0.0
    return max(0.0, min(1.0, 1.0 - divergence_pct / 3.0))


def _spy_ranging(bars: dict) -> Optional[bool]:
    """Returns True if SPY is ranging (5d range < 1.5% of 20d midpoint)."""
    spy = bars.get("SPY") or bars.get("SPY/USD")
    if not spy or len(spy) < 20:
        return None
    try:
        closes = [float(b.get("c", 0)) for b in spy[-20:]]
        if any(c <= 0 for c in closes):
            return None
        rng = max(closes[-5:]) - min(closes[-5:])
        mid = sum(closes) / len(closes)
        if mid <= 0:
            return None
        return (rng / mid) < 0.015
    except Exception:
        return None


def _failed_break_count(bar_list: list, level: float, direction: str) -> int:
    """How many of the last N bars (excluding today) attempted to break the level and failed.

    For 'short' (level = PDH): bar.h > level but bar.c < level → failed upward break
    For 'long'  (level = PDL): bar.l < level but bar.c > level → failed downward break
    """
    lookback = bar_list[-(FAILED_BREAK_LOOKBACK + 1):-1]
    count = 0
    for b in lookback:
        h = float(b.get("h", 0) or 0)
        l = float(b.get("l", 0) or 0)
        c = float(b.get("c", 0) or 0)
        if direction == "short" and h > level and c < level:
            count += 1
        elif direction == "long" and l < level and c > level:
            count += 1
    return count


def _build_signal_for_symbol(symbol: str, bar_list: list, spy_ranging: Optional[bool]) -> Optional[Signal]:
    if not bar_list or len(bar_list) < MIN_BARS:
        return None

    yesterday = bar_list[-2]
    today = bar_list[-1]

    pdh = float(yesterday.get("h", 0) or 0)
    pdl = float(yesterday.get("l", 0) or 0)
    if pdh <= 0 or pdl <= 0 or pdh <= pdl:
        return None  # 0-range or invalid bar

    today_h = float(today.get("h", 0) or 0)
    today_l = float(today.get("l", 0) or 0)
    today_c = float(today.get("c", 0) or 0)
    today_v = float(today.get("v", 0) or 0)
    if today_h <= 0 or today_l <= 0 or today_c <= 0:
        return None

    atr = _atr(bar_list)
    if atr <= 0:
        return None

    # Volume must NOT be spiking — current volume < 0.80 × recent average
    recent_vols = [float(b.get("v", 0) or 0) for b in bar_list[-21:-1]]
    avg_vol = (sum(recent_vols) / len(recent_vols)) if recent_vols else 0.0
    if avg_vol <= 0:
        return None
    vol_ratio = today_v / avg_vol
    if vol_ratio >= VOLUME_RATIO_MAX:
        return None

    closes = [float(b.get("c", 0) or 0) for b in bar_list[-25:]]
    mtf = _ranging_mtf_score(closes)
    cross_agree = bool(spy_ranging) if spy_ranging is not None else False
    midpoint = (pdh + pdl) / 2.0

    # ── SHORT setup: approaching PDH from below, didn't break ──
    if today_c < pdh:
        distance_to_pdh = (pdh - today_c) / atr
        if distance_to_pdh <= APPROACH_MAX_ATR and today_h <= pdh:
            failed_breaks = _failed_break_count(bar_list, pdh, "short")
            proximity_score = (APPROACH_MAX_ATR - distance_to_pdh) / APPROACH_MAX_ATR
            low_vol_bonus = (VOLUME_RATIO_MAX - vol_ratio) / VOLUME_RATIO_MAX
            confidence = min(MAX_CONFIDENCE, 0.50 + 0.10 * proximity_score + 0.10 * low_vol_bonus + 0.05 * min(failed_breaks, 3))
            reason_payload = {
                "setup": "pdh_pdl_reversion",
                "side": "short",
                "level": round(pdh, 4),
                "distance_atr": round(distance_to_pdh, 3),
                "volume_vs_avg": round(vol_ratio, 2),
                "failed_break_count": failed_breaks,
                "midpoint_target": round(midpoint, 4),
                "volume_agreement": round(1.0 - vol_ratio, 2),
                "mtf_alignment": round(mtf, 2),
                "cross_asset_agree": cross_agree,
            }
            return Signal(
                symbol=symbol,
                side="sell",   # runner filters on long_only bots
                confidence=round(confidence, 3),
                size_hint=0.04,
                strategy=STRATEGY_NAME,
                reason=json.dumps(reason_payload),
            )

    # ── LONG setup: approaching PDL from above, didn't break ──
    if today_c > pdl:
        distance_to_pdl = (today_c - pdl) / atr
        if distance_to_pdl <= APPROACH_MAX_ATR and today_l >= pdl:
            failed_breaks = _failed_break_count(bar_list, pdl, "long")
            proximity_score = (APPROACH_MAX_ATR - distance_to_pdl) / APPROACH_MAX_ATR
            low_vol_bonus = (VOLUME_RATIO_MAX - vol_ratio) / VOLUME_RATIO_MAX
            confidence = min(MAX_CONFIDENCE, 0.50 + 0.10 * proximity_score + 0.10 * low_vol_bonus + 0.05 * min(failed_breaks, 3))
            reason_payload = {
                "setup": "pdh_pdl_reversion",
                "side": "long",
                "level": round(pdl, 4),
                "distance_atr": round(distance_to_pdl, 3),
                "volume_vs_avg": round(vol_ratio, 2),
                "failed_break_count": failed_breaks,
                "midpoint_target": round(midpoint, 4),
                "volume_agreement": round(1.0 - vol_ratio, 2),
                "mtf_alignment": round(mtf, 2),
                "cross_asset_agree": cross_agree,
            }
            return Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=0.04,
                strategy=STRATEGY_NAME,
                reason=json.dumps(reason_payload),
            )

    return None


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if not bars:
        return []

    sample_sym = next(iter(bars))
    if _is_intraday_timeframe(bars.get(sample_sym, [])):
        h_et = _et_hour_now()
        if not (10 <= h_et < 15):
            return []

    spy_ranging = _spy_ranging(bars)
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list, spy_ranging)
            if sig is not None:
                out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out
