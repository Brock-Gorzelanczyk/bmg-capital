"""
Crypto News Sentiment Strategy
Uses LunarCrush or Polygon News sentiment to enter trades.

Implementation (paper phase, no API keys required):
- Synthetic sentiment based on BTC price momentum as proxy for market sentiment
- 4h return > 3%: bullish sentiment signal
- 4h return < -3%: bearish sentiment signal
- Social volume proxy: volume ratio (24h / 30d avg)

With LUNARCRUSH_API_KEY:
  - GET https://lunarcrush.com/api4/public/coins/BTC/time-series/v2
  - Use galaxy_score as sentiment, alt_rank for relative sentiment

Long signal: sentiment_score > 60 AND social_volume_ratio > 1.5
Short signal: sentiment_score < 40 AND social_volume_ratio > 1.5
confidence = abs(sentiment_score - 50) / 50 * 0.75

Only applies to: BTC, ETH, SOL (most liquid with best news coverage).
"""
from __future__ import annotations

import logging
import os
from statistics import mean, stdev
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_news_sentiment"

# Only these symbols — most liquid with best news coverage
TARGET_SYMBOLS = frozenset({"BTC/USD", "ETH/USD", "SOL/USD", "BTC", "ETH", "SOL"})

# Synthetic momentum thresholds (proxy when no API key)
BULLISH_4H_RETURN = 0.03   # +3%
BEARISH_4H_RETURN = -0.03  # -3%

# Social volume ratio threshold
SOCIAL_VOL_RATIO_THRESHOLD = 1.5

# LunarCrush thresholds
LUNARCRUSH_BULLISH_SCORE = 60
LUNARCRUSH_BEARISH_SCORE = 40

MAX_CONFIDENCE = 0.75

# Approximate number of bars in 4h window for different bar sizes
# 5-min bars: 48 bars; 15-min bars: 16 bars; 1h bars: 4 bars
_4H_BAR_COUNTS = {5: 48, 15: 16, 60: 4}


def _detect_bar_size_minutes(bar_list: list[dict]) -> int:
    """Guess bar size in minutes from timestamps; default 5."""
    if len(bar_list) < 2:
        return 5
    t0 = bar_list[-2].get("t")
    t1 = bar_list[-1].get("t")
    if t0 is None or t1 is None:
        return 5
    try:
        if isinstance(t0, (int, float)) and isinstance(t1, (int, float)):
            diff_s = abs(t1 - t0)
        else:
            from datetime import datetime
            def _parse(ts: Any) -> float:
                if isinstance(ts, (int, float)):
                    return float(ts)
                if isinstance(ts, str):
                    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if isinstance(ts, datetime):
                    return ts.timestamp()
                return 0.0
            diff_s = abs(_parse(t1) - _parse(t0))
        diff_m = int(round(diff_s / 60))
        if diff_m in (5, 15, 30, 60):
            return diff_m
    except Exception:
        pass
    return 5


def _compute_4h_return(bar_list: list[dict]) -> float | None:
    """Compute the 4-hour return using the last ~4h of bars."""
    bar_size = _detect_bar_size_minutes(bar_list)
    n_bars = _4H_BAR_COUNTS.get(bar_size, 48)

    if len(bar_list) < n_bars + 1:
        return None

    start_bar = bar_list[-(n_bars + 1)]
    end_bar = bar_list[-1]

    start_price = start_bar.get("c", start_bar.get("close", 0))
    end_price = end_bar.get("c", end_bar.get("close", 0))

    if start_price <= 0:
        return None

    return (end_price - start_price) / start_price


def _compute_social_volume_ratio(bar_list: list[dict]) -> float:
    """
    Proxy for social volume ratio using the current bar volume vs. 30-bar average.
    A ratio > 1.5 indicates elevated market activity.
    """
    if not bar_list:
        return 1.0

    volumes = [b.get("v", b.get("volume", 0)) for b in bar_list if b.get("v", b.get("volume", 0)) > 0]
    if len(volumes) < 2:
        return 1.0

    # Current volume vs. long-term average (last 30 bars as proxy for 30d avg)
    lookback = min(30, len(volumes))
    avg_vol = mean(volumes[-lookback:])
    current_vol = volumes[-1]

    if avg_vol <= 0:
        return 1.0

    return current_vol / avg_vol


def _fetch_lunarcrush_sentiment(symbol: str, api_key: str) -> dict | None:
    """
    Fetch sentiment from LunarCrush API.
    Returns dict with galaxy_score and social_volume_ratio, or None on error.
    """
    # Normalize symbol: BTC/USD → BTC
    coin = symbol.split("/")[0].lower()
    url = f"https://lunarcrush.com/api4/public/coins/{coin}/time-series/v2?interval=1d&bucket=day"
    try:
        req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read())

        time_series = data.get("data", {}).get("timeSeries", [])
        if not time_series:
            return None

        latest = time_series[-1]
        galaxy_score = latest.get("galaxy_score", 50)

        # Social volume ratio: latest / 30d avg
        social_vols = [ts.get("social_volume", 0) for ts in time_series[-30:] if ts.get("social_volume")]
        avg_social_vol = mean(social_vols) if social_vols else 1
        latest_social_vol = latest.get("social_volume", avg_social_vol)
        social_vol_ratio = latest_social_vol / max(avg_social_vol, 1)

        return {
            "galaxy_score": galaxy_score,
            "social_volume_ratio": social_vol_ratio,
        }
    except (URLError, KeyError, ValueError, Exception) as exc:
        logger.debug(f"LunarCrush fetch failed for {symbol}: {exc}")
        return None


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate crypto news sentiment signals for BTC, ETH, SOL.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first.
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, btc_dominance, btc_funding_rate, ...}.
    """
    lunarcrush_api_key = os.getenv("LUNARCRUSH_API_KEY", "")
    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        # Normalize to check against target set
        base_symbol = symbol.split("/")[0] if "/" in symbol else symbol
        if base_symbol not in {"BTC", "ETH", "SOL"}:
            continue
        if not bar_list or len(bar_list) < 10:
            continue

        if lunarcrush_api_key:
            # Live LunarCrush path
            lc_data = _fetch_lunarcrush_sentiment(symbol, lunarcrush_api_key)
            if lc_data:
                galaxy_score = lc_data["galaxy_score"]
                social_vol_ratio = lc_data["social_volume_ratio"]

                if galaxy_score > LUNARCRUSH_BULLISH_SCORE and social_vol_ratio > SOCIAL_VOL_RATIO_THRESHOLD:
                    side = "buy"
                elif galaxy_score < LUNARCRUSH_BEARISH_SCORE and social_vol_ratio > SOCIAL_VOL_RATIO_THRESHOLD:
                    side = "sell"
                else:
                    continue

                confidence = abs(galaxy_score - 50) / 50 * MAX_CONFIDENCE
                confidence = max(0.0, min(MAX_CONFIDENCE, confidence))

                reason = (
                    f"Crypto news sentiment (LunarCrush): {symbol} galaxy_score={galaxy_score:.1f}, "
                    f"social_vol_ratio={social_vol_ratio:.2f}; side={side}"
                )

                signals.append(Signal(
                    symbol=symbol,
                    side=side,
                    confidence=confidence,
                    size_hint=round(confidence * 0.8, 3),
                    reason=reason,
                    strategy=STRATEGY_NAME,
                ))
                continue

        # Synthetic proxy path (no API key or LunarCrush unavailable)
        four_h_return = _compute_4h_return(bar_list)
        if four_h_return is None:
            continue

        social_vol_ratio = _compute_social_volume_ratio(bar_list)

        if four_h_return > BULLISH_4H_RETURN and social_vol_ratio > SOCIAL_VOL_RATIO_THRESHOLD:
            side = "buy"
        elif four_h_return < BEARISH_4H_RETURN and social_vol_ratio > SOCIAL_VOL_RATIO_THRESHOLD:
            side = "sell"
        else:
            continue

        # Confidence: scale from 3% return → proportional up to MAX_CONFIDENCE
        confidence = min(1.0, abs(four_h_return) / 0.06) * MAX_CONFIDENCE
        confidence = max(0.0, min(MAX_CONFIDENCE, confidence))

        reason = (
            f"Crypto news sentiment (proxy): {symbol} 4h_return={four_h_return * 100:.2f}%, "
            f"social_vol_ratio={social_vol_ratio:.2f} (proxy); side={side}"
        )

        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            size_hint=round(confidence * 0.8, 3),
            reason=reason,
            strategy=STRATEGY_NAME,
        ))

    return signals
