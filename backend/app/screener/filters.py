from __future__ import annotations

from typing import Any, List

import pandas as pd
import ta


# ---------------------------------------------------------------------------
# Base / helpers
# ---------------------------------------------------------------------------

class BaseFilter:
    def __init__(self, field: str, operator: str, value: Any) -> None:
        self.field = field
        self.operator = operator
        self.value = value

    def apply(self, df: pd.DataFrame) -> bool:
        raise NotImplementedError


def _compare(val: float, operator: str, threshold: float) -> bool:
    ops = {
        "gt": val > threshold,
        "lt": val < threshold,
        "gte": val >= threshold,
        "lte": val <= threshold,
        "eq": val == threshold,
    }
    return ops.get(operator, False)


# ---------------------------------------------------------------------------
# Concrete filters — original
# ---------------------------------------------------------------------------

class RSIFilter(BaseFilter):
    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 15:
            return False
        rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        last = rsi.iloc[-1]
        if pd.isna(last):
            return False
        return _compare(float(last), self.operator, float(self.value))


class PriceFilter(BaseFilter):
    def apply(self, df: pd.DataFrame) -> bool:
        return _compare(float(df["close"].iloc[-1]), self.operator, float(self.value))


class VolumeFilter(BaseFilter):
    def apply(self, df: pd.DataFrame) -> bool:
        return _compare(float(df["volume"].iloc[-1]), self.operator, float(self.value))


class MACrossFilter(BaseFilter):
    """field: 'ma_cross'; value: 'golden' or 'death'."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 201:
            return False
        fast = df["close"].rolling(50).mean()
        slow = df["close"].rolling(200).mean()
        if self.value == "golden":
            return bool(fast.iloc[-2] < slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1])
        return bool(fast.iloc[-2] > slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1])


class MACDCrossFilter(BaseFilter):
    """field: 'macd_cross'; value: 'bull' or 'bear'."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 35:
            return False
        macd = ta.trend.MACD(df["close"])
        line = macd.macd()
        signal = macd.macd_signal()
        if pd.isna(line.iloc[-1]) or pd.isna(line.iloc[-2]):
            return False
        if self.value == "bull":
            return bool(line.iloc[-2] < signal.iloc[-2] and line.iloc[-1] > signal.iloc[-1])
        return bool(line.iloc[-2] > signal.iloc[-2] and line.iloc[-1] < signal.iloc[-1])


class VolumeBreakoutFilter(BaseFilter):
    """Passes if volume > value × 20-day average."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 22:
            return False
        avg = df["volume"].iloc[-22:-1].mean()
        if avg == 0:
            return False
        return bool(float(df["volume"].iloc[-1]) > float(self.value) * avg)


class BreakoutFilter(BaseFilter):
    """52-week high breakout."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 254:
            return False
        return bool(float(df["close"].iloc[-1]) > df["close"].iloc[-253:-1].max())


# ---------------------------------------------------------------------------
# New institutional filters
# ---------------------------------------------------------------------------

class PriceAboveMAFilter(BaseFilter):
    """close > SMA(period). field: 'price_above_ma'; value: MA period (e.g. 50)."""

    def apply(self, df: pd.DataFrame) -> bool:
        period = int(self.value)
        if len(df) < period + 1:
            return False
        ma = df["close"].rolling(period).mean()
        last_ma = ma.iloc[-1]
        if pd.isna(last_ma):
            return False
        return bool(float(df["close"].iloc[-1]) > float(last_ma))


class StageFilter(BaseFilter):
    """Mark Minervini Stage 2: close > SMA50 > SMA150 > SMA200, SMA200 trending up."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 220:
            return False
        c = df["close"]
        sma50 = c.rolling(50).mean()
        sma150 = c.rolling(150).mean()
        sma200 = c.rolling(200).mean()
        last = c.iloc[-1]
        s50, s150, s200 = sma50.iloc[-1], sma150.iloc[-1], sma200.iloc[-1]
        s200_20ago = sma200.iloc[-21]
        if any(pd.isna(v) for v in [s50, s150, s200, s200_20ago]):
            return False
        return bool(last > s50 > s150 > s200 and s200 > s200_20ago)


class EMAStackFilter(BaseFilter):
    """EMA(8) > EMA(21) > EMA(55) on last bar."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 60:
            return False
        c = df["close"]
        e8 = c.ewm(span=8, adjust=False).mean()
        e21 = c.ewm(span=21, adjust=False).mean()
        e55 = c.ewm(span=55, adjust=False).mean()
        return bool(e8.iloc[-1] > e21.iloc[-1] > e55.iloc[-1])


class ConsecutiveGainsFilter(BaseFilter):
    """Last N bars all closed higher than previous. value: N (e.g. 3)."""

    def apply(self, df: pd.DataFrame) -> bool:
        n = int(self.value)
        if len(df) < n + 1:
            return False
        closes = df["close"].iloc[-(n + 1):]
        return bool(all(closes.iloc[i + 1] > closes.iloc[i] for i in range(n)))


class BollingerSqueezeFilter(BaseFilter):
    """BB width (upper-lower)/middle < threshold%. value: threshold (e.g. 5 = 5%)."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 22:
            return False
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        upper = bb.bollinger_hband().iloc[-1]
        lower = bb.bollinger_lband().iloc[-1]
        middle = bb.bollinger_mavg().iloc[-1]
        if pd.isna(middle) or middle == 0:
            return False
        width_pct = (upper - lower) / middle * 100
        return bool(width_pct < float(self.value))


class RelativeHighFilter(BaseFilter):
    """close within X% of N-day high. field: 'relative_high'; value: threshold 0-1 (e.g. 0.85 = within 15%)."""

    def apply(self, df: pd.DataFrame) -> bool:
        n = 252  # 52-week high
        if len(df) < 10:
            return False
        lookback = min(n, len(df))
        high_n = df["close"].iloc[-lookback:].max()
        if high_n == 0:
            return False
        ratio = float(df["close"].iloc[-1]) / float(high_n)
        return bool(ratio >= float(self.value))


class TurtleBreakoutFilter(BaseFilter):
    """55-day channel breakout (Richard Dennis Turtle Trading)."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 57:
            return False
        channel_high = df["high"].iloc[-56:-1].max()
        return bool(float(df["close"].iloc[-1]) > float(channel_high))


class Momentum12MFilter(BaseFilter):
    """12-month price return > value (e.g. 0.20 = 20%). value: decimal return threshold."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 253:
            return False
        ret = float(df["close"].iloc[-1]) / float(df["close"].iloc[-253]) - 1
        return bool(ret > float(self.value))


class ZScoreReversionFilter(BaseFilter):
    """Price z-score (20-day) < value (e.g. -2.0). Finds statistically oversold stocks."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 22:
            return False
        ma = df["close"].rolling(20).mean().iloc[-1]
        std = df["close"].rolling(20).std().iloc[-1]
        if pd.isna(std) or std == 0:
            return False
        z = (float(df["close"].iloc[-1]) - float(ma)) / float(std)
        return bool(z < float(self.value))


class DarvasBoxFilter(BaseFilter):
    """Darvas Box: new 52-week high in last 3 weeks AND tight BB consolidation."""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 60:
            return False
        lookback = min(252, len(df))
        high_252 = float(df["close"].iloc[-lookback:].max())
        made_new_high = float(df["close"].iloc[-15:].max()) >= high_252 * 0.99
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        middle = bb.bollinger_mavg().iloc[-1]
        if pd.isna(middle) or middle == 0:
            return False
        width_pct = (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / middle * 100
        return bool(made_new_high and width_pct < 8.0)


# ---------------------------------------------------------------------------
# Phase 3 v2 filters
# ---------------------------------------------------------------------------

class RelativeVolumeFilter(BaseFilter):
    """field: 'rel_volume'; value: float multiplier (e.g., 1.5 = 1.5x avg vol)"""

    def apply(self, df: pd.DataFrame) -> bool:
        avg_vol = float(df["volume"].iloc[-21:-1].mean()) if len(df) >= 22 else float(df["volume"].mean())
        if avg_vol == 0:
            return False
        rel_vol = float(df["volume"].iloc[-1]) / avg_vol
        return _compare(rel_vol, self.operator, float(self.value))


class ChangePercentFilter(BaseFilter):
    """field: 'change_pct'; value: float (e.g., 5.0 = 5%)"""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 2:
            return False
        chg = (df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100
        return _compare(float(chg), self.operator, float(self.value))


class ATRFilter(BaseFilter):
    """field: 'atr'; value: float dollar amount"""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 15:
            return False
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        return _compare(float(atr), self.operator, float(self.value))


class Near52WHighFilter(BaseFilter):
    """field: 'near_52w_high'; value: float pct from high (e.g., 5.0 = within 5%)"""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 10:
            return False
        high_52w = df["high"].rolling(min(252, len(df))).max().iloc[-1]
        current = df["close"].iloc[-1]
        pct_from_high = (high_52w - current) / high_52w * 100
        return _compare(float(pct_from_high), self.operator, float(self.value))


class GoldenCrossFilter(BaseFilter):
    """field: 'golden_cross'; operator: 'eq'; value: True/'true'"""

    def apply(self, df: pd.DataFrame) -> bool:
        if len(df) < 201:
            return False
        fast = df["close"].rolling(50).mean()
        slow = df["close"].rolling(200).mean()
        return bool(fast.iloc[-2] < slow.iloc[-2] and fast.iloc[-1] >= slow.iloc[-1])


class AboveMaFilter(BaseFilter):
    """field: 'above_ma50' or 'above_ma200'; operator: 'is_true'; value: any"""

    def apply(self, df: pd.DataFrame) -> bool:
        window = 200 if "200" in self.field else 50
        if len(df) < window:
            return False
        ma = df["close"].rolling(window).mean().iloc[-1]
        return bool(df["close"].iloc[-1] > ma)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FILTER_MAP = {
    "rsi": RSIFilter,
    "price": PriceFilter,
    "volume": VolumeFilter,
    "ma_cross": MACrossFilter,
    "macd_cross": MACDCrossFilter,
    "volume_breakout": VolumeBreakoutFilter,
    "breakout_52w": BreakoutFilter,
    "price_above_ma": PriceAboveMAFilter,
    "stage": StageFilter,
    "ema_stack": EMAStackFilter,
    "consecutive_gains": ConsecutiveGainsFilter,
    "bollinger_squeeze": BollingerSqueezeFilter,
    "relative_high": RelativeHighFilter,
    "turtle_breakout": TurtleBreakoutFilter,
    "momentum_12m": Momentum12MFilter,
    "zscore_reversion": ZScoreReversionFilter,
    "darvas_box": DarvasBoxFilter,
    # Phase 3 v2
    "rel_volume": RelativeVolumeFilter,
    "change_pct": ChangePercentFilter,
    "atr": ATRFilter,
    "near_52w_high": Near52WHighFilter,
    "golden_cross": GoldenCrossFilter,
    "above_ma50": AboveMaFilter,
    "above_ma200": AboveMaFilter,
}

# ---------------------------------------------------------------------------
# Pre-built preset screens
# ---------------------------------------------------------------------------

PRESET_SCREENS: dict[str, list[dict]] = {
    # --- Classic ---
    "rsi_oversold": [
        {"field": "rsi", "operator": "lt", "value": 30},
    ],
    "golden_cross": [
        {"field": "ma_cross", "operator": "eq", "value": "golden"},
    ],
    "macd_bullish": [
        {"field": "macd_cross", "operator": "eq", "value": "bull"},
    ],
    "volume_surge": [
        {"field": "volume_breakout", "operator": "gt", "value": 2.0},
    ],
    "breakout_52w": [
        {"field": "breakout_52w", "operator": "eq", "value": True},
    ],

    # --- Growth & Momentum ---
    "stage2_breakout": [
        {"field": "stage", "operator": "eq", "value": True},
        {"field": "relative_high", "operator": "gte", "value": 0.75},
    ],
    "canslim_leaders": [
        {"field": "price_above_ma", "operator": "eq", "value": 50},
        {"field": "rsi", "operator": "gt", "value": 60},
        {"field": "volume_breakout", "operator": "gt", "value": 1.2},
    ],
    "momentum_surge": [
        {"field": "relative_high", "operator": "gte", "value": 0.95},
        {"field": "rsi", "operator": "gt", "value": 50},
        {"field": "volume_breakout", "operator": "gt", "value": 1.5},
    ],
    "high_rs_momentum": [
        {"field": "relative_high", "operator": "gte", "value": 0.85},
        {"field": "rsi", "operator": "gt", "value": 55},
        {"field": "consecutive_gains", "operator": "gte", "value": 2},
    ],
    "power_trend": [
        {"field": "ema_stack", "operator": "eq", "value": True},
        {"field": "price_above_ma", "operator": "eq", "value": 50},
    ],

    # --- Value & Mean Reversion ---
    "mean_reversion_quality": [
        {"field": "rsi", "operator": "lt", "value": 40},
        {"field": "price_above_ma", "operator": "eq", "value": 200},
        {"field": "price", "operator": "gt", "value": 10},
    ],
    "deep_value_bounce": [
        {"field": "rsi", "operator": "lt", "value": 35},
        {"field": "price_above_ma", "operator": "eq", "value": 200},
        {"field": "volume_breakout", "operator": "gt", "value": 1.2},
    ],

    # --- Technical Patterns ---
    "volatility_contraction": [
        {"field": "bollinger_squeeze", "operator": "lt", "value": 5},
        {"field": "price_above_ma", "operator": "eq", "value": 50},
    ],
    "ema_stack_uptrend": [
        {"field": "ema_stack", "operator": "eq", "value": True},
    ],
    "consecutive_gains": [
        {"field": "consecutive_gains", "operator": "gte", "value": 3},
        {"field": "rsi", "operator": "gt", "value": 40},
    ],

    # --- New institutional strategies ---
    "turtle_breakout": [
        {"field": "turtle_breakout", "operator": "eq", "value": True},
        {"field": "price_above_ma", "operator": "eq", "value": 200},
    ],
    "momentum_12m": [
        {"field": "momentum_12m", "operator": "gt", "value": 0.20},
        {"field": "price_above_ma", "operator": "eq", "value": 200},
        {"field": "rsi", "operator": "gt", "value": 50},
    ],
    "zscore_reversion": [
        {"field": "zscore_reversion", "operator": "lt", "value": -2.0},
        {"field": "price_above_ma", "operator": "eq", "value": 200},
    ],
    "darvas_box": [
        {"field": "darvas_box", "operator": "eq", "value": True},
        {"field": "price_above_ma", "operator": "eq", "value": 50},
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_filters(filter_configs: List[dict]) -> List[BaseFilter]:
    filters: List[BaseFilter] = []
    for fc in filter_configs:
        cls = FILTER_MAP.get(fc["field"])
        if cls:
            filters.append(cls(fc["field"], fc.get("operator", "eq"), fc["value"]))
    return filters


def apply_filters(df: pd.DataFrame, filters: List[BaseFilter]) -> bool:
    return all(f.apply(df) for f in filters)
