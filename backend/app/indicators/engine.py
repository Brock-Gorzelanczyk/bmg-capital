from __future__ import annotations

import math
from typing import Any, Dict, List

import pandas as pd
import ta


def _clean(values: list) -> list:
    return [
        None if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))
        else round(float(v), 6)
        for v in values
    ]


def compute_indicators(df: pd.DataFrame, requested: List[str]) -> Dict[str, List[Any]]:
    result: Dict[str, List[Any]] = {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    for key in requested:
        if key.startswith("SMA_"):
            period = int(key.split("_")[1])
            result[key] = _clean(close.rolling(period).mean().tolist())

        elif key.startswith("EMA_"):
            period = int(key.split("_")[1])
            result[key] = _clean(ta.trend.ema_indicator(close, window=period).tolist())

        elif key.startswith("BB_"):
            period = int(key.split("_")[1])
            bb = ta.volatility.BollingerBands(close, window=period)
            result[f"BB_{period}_upper"] = _clean(bb.bollinger_hband().tolist())
            result[f"BB_{period}_middle"] = _clean(bb.bollinger_mavg().tolist())
            result[f"BB_{period}_lower"] = _clean(bb.bollinger_lband().tolist())

        elif key.startswith("RSI_"):
            period = int(key.split("_")[1])
            result[key] = _clean(ta.momentum.RSIIndicator(close, window=period).rsi().tolist())

        elif key == "MACD":
            macd = ta.trend.MACD(close)
            result["MACD_line"] = _clean(macd.macd().tolist())
            result["MACD_signal"] = _clean(macd.macd_signal().tolist())
            result["MACD_hist"] = _clean(macd.macd_diff().tolist())

        elif key == "VWAP":
            result["VWAP"] = _clean(
                ta.volume.VolumeWeightedAveragePrice(
                    high=high, low=low, close=close, volume=volume
                ).volume_weighted_average_price().tolist()
            )

        elif key == "ATR":
            result["ATR"] = _clean(
                ta.volatility.AverageTrueRange(high=high, low=low, close=close).average_true_range().tolist()
            )

        elif key == "STOCH":
            stoch = ta.momentum.StochasticOscillator(high=high, low=low, close=close)
            result["STOCH_k"] = _clean(stoch.stoch().tolist())
            result["STOCH_d"] = _clean(stoch.stoch_signal().tolist())

        elif key == "WILLR":
            result["WILLR"] = _clean(
                ta.momentum.WilliamsRIndicator(high=high, low=low, close=close).williams_r().tolist()
            )

        elif key == "OBV":
            result["OBV"] = _clean(
                ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume().tolist()
            )

        elif key == "CCI":
            result["CCI"] = _clean(
                ta.trend.CCIIndicator(high=high, low=low, close=close).cci().tolist()
            )

        elif key == "ADX":
            adx = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
            result["ADX"] = _clean(adx.adx().tolist())
            result["ADX_pos"] = _clean(adx.adx_pos().tolist())
            result["ADX_neg"] = _clean(adx.adx_neg().tolist())

        elif key == "ICHIMOKU":
            ichimoku = ta.trend.IchimokuIndicator(high=high, low=low, window1=9, window2=26, window3=52)
            result["ICHI_tenkan"] = _clean(ichimoku.ichimoku_conversion_line().tolist())
            result["ICHI_kijun"] = _clean(ichimoku.ichimoku_base_line().tolist())
            result["ICHI_senkou_a"] = _clean(ichimoku.ichimoku_a().tolist())
            result["ICHI_senkou_b"] = _clean(ichimoku.ichimoku_b().tolist())

        elif key == "PSAR":
            try:
                psar = ta.trend.PSARIndicator(high=high, low=low, close=close)
                result["PSAR"] = _clean(psar.psar().tolist())
                result["PSAR_up"] = _clean(psar.psar_up().tolist())
                result["PSAR_down"] = _clean(psar.psar_down().tolist())
            except Exception:
                result["PSAR"] = [None] * len(close)

        elif key == "DONCHIAN":
            don = ta.volatility.DonchianChannel(high=high, low=low, close=close, window=20)
            result["DONCHIAN_upper"] = _clean(don.donchian_channel_hband().tolist())
            result["DONCHIAN_mid"] = _clean(don.donchian_channel_mband().tolist())
            result["DONCHIAN_lower"] = _clean(don.donchian_channel_lband().tolist())

        elif key == "KELTNER":
            kc = ta.volatility.KeltnerChannel(high=high, low=low, close=close, window=20)
            result["KELTNER_upper"] = _clean(kc.keltner_channel_hband().tolist())
            result["KELTNER_mid"] = _clean(kc.keltner_channel_mband().tolist())
            result["KELTNER_lower"] = _clean(kc.keltner_channel_lband().tolist())

        elif key.startswith("DEMA_"):
            period = int(key.split("_")[1])
            ema1 = ta.trend.ema_indicator(close, window=period)
            ema2 = ta.trend.ema_indicator(ema1, window=period)
            dema = 2 * ema1 - ema2
            result[key] = _clean(dema.tolist())

        elif key == "CMF":
            result["CMF"] = _clean(
                ta.volume.ChaikinMoneyFlowIndicator(high=high, low=low, close=close, volume=volume, window=20).chaikin_money_flow().tolist()
            )

        elif key == "ROC":
            result["ROC"] = _clean(
                ta.momentum.ROCIndicator(close=close, window=12).roc().tolist()
            )

        elif key == "MFI":
            result["MFI"] = _clean(
                ta.volume.MFIIndicator(high=high, low=low, close=close, volume=volume, window=14).money_flow_index().tolist()
            )

    return result
