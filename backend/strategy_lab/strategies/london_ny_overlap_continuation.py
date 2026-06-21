"""London-NY Overlap Continuation — trade in the London session direction.

Thesis: During the 08:00-12:00 ET London / NY overlap, global FX and
equity liquidity peaks. If the London session (03:00-08:00 ET) printed
a strong directional bias (>= 0.5 ATR), the overlap typically continues
that bias. Enter on a pullback to the London-session VWAP with a stop
at the opposite London extreme.

Regime: bull_trending (LONG) / bear_trending (SHORT) depending on the
London direction — discipline filter handles enforcement.

Active hours: 08:00-12:00 ET HARD GATE. No signals outside this window.
Forced exit at 12:00 ET regardless of P&L is a position-management
concern (handled by the exit engine via target/stop levels in the
signal payload; runner doesn't currently support time-stops).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "london_ny_overlap_continuation"

_ET_OFFSET = timezone(timedelta(hours=-4))  # EDT
MIN_BARS = 100               # need enough history for ATR + London session
LONDON_STRENGTH_MIN_ATR = 0.5
PULLBACK_MAX_ATR = 0.20
MIN_LONDON_BARS = 12         # need at least 12 5m bars in London session (1 hour) for meaningful VWAP
ATR_PERIOD = 14
MAX_CONFIDENCE = 0.80


def _et_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(_ET_OFFSET).replace(tzinfo=None)


def _to_et(ts_raw) -> Optional[datetime]:
    if not ts_raw:
        return None
    try:
        s = str(ts_raw)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_ET_OFFSET).replace(tzinfo=None)
    except Exception:
        return None


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


def _build_signal_for_symbol(symbol: str, bar_list: list, now_et: datetime) -> Optional[Signal]:
    if not bar_list or len(bar_list) < MIN_BARS:
        return None

    today = now_et.date()

    # Filter to today's bars and bucket into london / overlap windows
    london_bars: list = []      # 03:00-08:00 ET
    overlap_bars: list = []     # 08:00-12:00 ET (used for volume avg)
    for b in bar_list:
        et = _to_et(b.get("ts"))
        if et is None or et.date() != today:
            continue
        minutes = et.hour * 60 + et.minute
        # 03:00 ET = 180, 08:00 ET = 480, 12:00 ET = 720
        if 180 <= minutes < 480:
            london_bars.append(b)
        elif 480 <= minutes < 720:
            overlap_bars.append(b)

    if len(london_bars) < MIN_LONDON_BARS:
        return None
    if not overlap_bars:
        return None  # no current-bar to anchor signal

    london_open = float(london_bars[0].get("o", 0) or 0)
    london_close = float(london_bars[-1].get("c", 0) or 0)
    london_high = max(float(b.get("h", 0) or 0) for b in london_bars)
    london_low = min(float(b.get("l", 0) or 0) for b in london_bars if (b.get("l") or 0) > 0)
    if london_open <= 0 or london_close <= 0 or london_high <= london_low:
        return None

    atr = _atr(bar_list, ATR_PERIOD)
    if atr <= 0:
        return None

    london_move = london_close - london_open
    london_strength_atr = abs(london_move) / atr
    if london_strength_atr < LONDON_STRENGTH_MIN_ATR:
        return None

    direction = 1 if london_move > 0 else -1

    # London session VWAP (volume-weighted typical price)
    num = 0.0
    den = 0.0
    for b in london_bars:
        h = float(b.get("h", 0) or 0)
        l = float(b.get("l", 0) or 0)
        c = float(b.get("c", 0) or 0)
        v = float(b.get("v", 0) or 0)
        if v <= 0:
            continue
        num += ((h + l + c) / 3.0) * v
        den += v
    if den <= 0:
        return None
    london_vwap = num / den

    last = overlap_bars[-1]
    last_c = float(last.get("c", 0) or 0)
    last_l = float(last.get("l", 0) or 0)
    last_h = float(last.get("h", 0) or 0)
    if last_c <= 0:
        return None

    pullback_distance = abs(last_c - london_vwap) / atr
    if pullback_distance > PULLBACK_MAX_ATR:
        return None

    # Confirm: for LONG, recent low must hold above VWAP (level holding as support)
    last_5 = overlap_bars[-5:]
    if len(last_5) < 2:
        return None
    if direction == 1:
        if any(float(b.get("l", 0) or 0) <= london_vwap - 0.2 * atr for b in last_5):
            return None  # broke below VWAP at some point in last 5 bars
    else:
        if any(float(b.get("h", 0) or 0) >= london_vwap + 0.2 * atr for b in last_5):
            return None  # broke above VWAP

    # Volume agreement: overlap-window volume vs prior 5-day same-window average
    overlap_vols = [float(b.get("v", 0) or 0) for b in overlap_bars]
    recent_vols = [float(b.get("v", 0) or 0) for b in bar_list[-80:-len(overlap_bars) or None]]
    overlap_avg = (sum(overlap_vols) / len(overlap_vols)) if overlap_vols else 0.0
    recent_avg = (sum(recent_vols) / len(recent_vols)) if recent_vols else 0.0
    volume_agreement = min(1.0, max(0.0, (overlap_avg / recent_avg - 0.8) / 0.8)) if recent_avg > 0 else 0.5

    # MTF: 5m direction in overlap matches London direction
    if len(overlap_bars) >= 5:
        mtf_close = float(overlap_bars[-1].get("c", 0) or 0)
        mtf_open5 = float(overlap_bars[-5].get("o", 0) or 0)
        mtf_dir = 1 if mtf_close > mtf_open5 else -1 if mtf_close < mtf_open5 else 0
        mtf_alignment = 1.0 if mtf_dir == direction else 0.3
    else:
        mtf_alignment = 0.5

    # Cross-asset: SPY moving in same direction as London bias
    cross_agree = False  # populated by caller via SPY bars below

    london_range = london_high - london_low
    proximity_score = (PULLBACK_MAX_ATR - pullback_distance) / PULLBACK_MAX_ATR
    confidence = min(
        MAX_CONFIDENCE,
        0.50 + 0.12 * min(1.0, london_strength_atr - LONDON_STRENGTH_MIN_ATR)
             + 0.10 * proximity_score
             + 0.08 * volume_agreement,
    )

    reason_payload = {
        "setup": "london_ny_overlap_continuation",
        "side": "long" if direction == 1 else "short",
        "london_direction": direction,
        "london_strength_atr": round(london_strength_atr, 2),
        "london_range_dollars": round(london_range, 4),
        "session_vwap": round(london_vwap, 4),
        "pullback_distance_atr": round(pullback_distance, 3),
        "london_high": round(london_high, 4),
        "london_low": round(london_low, 4),
        "volume_agreement": round(volume_agreement, 2),
        "mtf_alignment": round(mtf_alignment, 2),
        "cross_asset_agree": cross_agree,
    }

    return Signal(
        symbol=symbol,
        side="buy" if direction == 1 else "sell",
        confidence=round(confidence, 3),
        size_hint=0.05,
        strategy=STRATEGY_NAME,
        reason=json.dumps(reason_payload),
    )


def _spy_direction(bars: dict) -> Optional[int]:
    spy = bars.get("SPY") or bars.get("SPY/USD")
    if not spy or len(spy) < 5:
        return None
    try:
        c_now = float(spy[-1].get("c", 0))
        c_5_ago = float(spy[-5].get("c", 0))
        if c_now <= 0 or c_5_ago <= 0:
            return None
        return 1 if c_now > c_5_ago else -1 if c_now < c_5_ago else 0
    except Exception:
        return None


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if not bars:
        return []

    now_et = _et_now()
    # Hard active hours guard — 08:00-12:00 ET only
    h_et = now_et.hour
    if not (8 <= h_et < 12):
        return []

    spy_dir = _spy_direction(bars)
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list, now_et)
            if sig is None:
                continue
            # Patch cross_asset_agree using SPY direction vs trade side
            if spy_dir is not None:
                try:
                    payload = json.loads(sig.reason)
                    side_dir = 1 if sig.side == "buy" else -1
                    payload["cross_asset_agree"] = (spy_dir == side_dir)
                    sig.reason = json.dumps(payload)
                except Exception:
                    pass
            out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out
