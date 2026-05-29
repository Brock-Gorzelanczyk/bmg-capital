from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np
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
    n = len(close)

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
                result["PSAR"] = [None] * n

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

        # ── NEW: Moving Averages ────────────────────────────────────────────────

        elif key.startswith("WMA_"):
            try:
                period = int(key.split("_")[1])
                result[key] = _clean(
                    ta.trend.WMAIndicator(close=close, window=period).wma().tolist()
                )
            except Exception:
                result[key] = [None] * n

        elif key.startswith("KAMA_"):
            try:
                period = int(key.split("_")[1])
                result[key] = _clean(
                    ta.momentum.KAMAIndicator(close=close, window=period).kama().tolist()
                )
            except Exception:
                result[key] = [None] * n

        elif key.startswith("TEMA_"):
            try:
                period = int(key.split("_")[1])
                ema1 = ta.trend.ema_indicator(close, window=period)
                ema2 = ta.trend.ema_indicator(ema1, window=period)
                ema3 = ta.trend.ema_indicator(ema2, window=period)
                tema = 3 * ema1 - 3 * ema2 + ema3
                result[key] = _clean(tema.tolist())
            except Exception:
                result[key] = [None] * n

        elif key.startswith("TRIX_"):
            try:
                period = int(key.split("_")[1])
                result[key] = _clean(
                    ta.trend.TRIXIndicator(close=close, window=period).trix().tolist()
                )
            except Exception:
                result[key] = [None] * n

        elif key.startswith("HMA_"):
            try:
                period = int(key.split("_")[1])
                half = max(2, period // 2)
                sqrt_p = max(2, int(round(math.sqrt(period))))
                wma_half = ta.trend.WMAIndicator(close=close, window=half).wma()
                wma_full = ta.trend.WMAIndicator(close=close, window=period).wma()
                raw = 2 * wma_half - wma_full
                raw_series = pd.Series(raw.values, index=close.index)
                result[key] = _clean(
                    ta.trend.WMAIndicator(close=raw_series, window=sqrt_p).wma().tolist()
                )
            except Exception:
                result[key] = [None] * n

        # ── NEW: Trend ──────────────────────────────────────────────────────────

        elif key == "AROON":
            try:
                aroon = ta.trend.AroonIndicator(high=high, low=low, window=25)
                result["AROON_up"] = _clean(aroon.aroon_up().tolist())
                result["AROON_down"] = _clean(aroon.aroon_down().tolist())
            except Exception:
                result["AROON_up"] = [None] * n
                result["AROON_down"] = [None] * n

        elif key == "DPO":
            try:
                result["DPO"] = _clean(
                    ta.trend.DPOIndicator(close=close, window=20).dpo().tolist()
                )
            except Exception:
                result["DPO"] = [None] * n

        elif key == "MASS":
            try:
                result["MASS"] = _clean(
                    ta.trend.MassIndex(high=high, low=low, window_fast=9, window_slow=25).mass_index().tolist()
                )
            except Exception:
                result["MASS"] = [None] * n

        elif key == "KST":
            try:
                kst = ta.trend.KSTIndicator(close=close)
                result["KST_line"] = _clean(kst.kst().tolist())
                result["KST_signal"] = _clean(kst.kst_sig().tolist())
            except Exception:
                result["KST_line"] = [None] * n
                result["KST_signal"] = [None] * n

        elif key == "VORTEX":
            try:
                vortex = ta.trend.VortexIndicator(high=high, low=low, close=close, window=14)
                result["VORTEX_pos"] = _clean(vortex.vortex_indicator_pos().tolist())
                result["VORTEX_neg"] = _clean(vortex.vortex_indicator_neg().tolist())
            except Exception:
                result["VORTEX_pos"] = [None] * n
                result["VORTEX_neg"] = [None] * n

        elif key == "STC":
            try:
                result["STC"] = _clean(
                    ta.trend.STCIndicator(close=close).stc().tolist()
                )
            except Exception:
                result["STC"] = [None] * n

        # ── NEW: Oscillators ────────────────────────────────────────────────────

        elif key == "AO":
            try:
                result["AO"] = _clean(
                    ta.momentum.AwesomeOscillatorIndicator(high=high, low=low).awesome_oscillator().tolist()
                )
            except Exception:
                result["AO"] = [None] * n

        elif key == "UO":
            try:
                result["UO"] = _clean(
                    ta.momentum.UltimateOscillator(high=high, low=low, close=close).ultimate_oscillator().tolist()
                )
            except Exception:
                result["UO"] = [None] * n

        elif key == "PPO":
            try:
                ppo = ta.momentum.PercentagePriceOscillator(close=close)
                result["PPO_line"] = _clean(ppo.ppo().tolist())
                result["PPO_signal"] = _clean(ppo.ppo_signal().tolist())
                result["PPO_hist"] = _clean(ppo.ppo_hist().tolist())
            except Exception:
                result["PPO_line"] = [None] * n
                result["PPO_signal"] = [None] * n
                result["PPO_hist"] = [None] * n

        elif key == "TSI":
            try:
                result["TSI"] = _clean(
                    ta.momentum.TSIIndicator(close=close).tsi().tolist()
                )
            except Exception:
                result["TSI"] = [None] * n

        elif key == "CMO":
            try:
                period = 14
                delta = close.diff()
                ups = delta.clip(lower=0).rolling(period).sum()
                downs = (-delta.clip(upper=0)).rolling(period).sum()
                cmo = ((ups - downs) / (ups + downs).replace(0, float("nan"))) * 100
                result["CMO"] = _clean(cmo.tolist())
            except Exception:
                result["CMO"] = [None] * n

        elif key == "FISHER":
            try:
                fisher = ta.momentum.FisherTransform(high=high, low=low, window=9)
                result["FISHER_line"] = _clean(fisher.fisher_transform().tolist())
                result["FISHER_signal"] = _clean(fisher.fisher_transform_signal().tolist())
            except Exception:
                result["FISHER_line"] = [None] * n
                result["FISHER_signal"] = [None] * n

        elif key == "COPPOCK":
            try:
                result["COPPOCK"] = _clean(
                    ta.momentum.CoppockCurve(close=close).coppock_curve().tolist()
                )
            except Exception:
                result["COPPOCK"] = [None] * n

        # ── NEW: Volatility ─────────────────────────────────────────────────────

        elif key == "UI":
            try:
                result["UI"] = _clean(
                    ta.volatility.UlcerIndex(close=close, window=14).ulcer_index().tolist()
                )
            except Exception:
                result["UI"] = [None] * n

        elif key == "BBWIDTH":
            try:
                bb = ta.volatility.BollingerBands(close=close, window=20)
                bbw = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()
                result["BBWIDTH"] = _clean(bbw.tolist())
            except Exception:
                result["BBWIDTH"] = [None] * n

        elif key == "BBP":
            try:
                result["BBP"] = _clean(
                    ta.volatility.BollingerBands(close=close, window=20).bollinger_pband().tolist()
                )
            except Exception:
                result["BBP"] = [None] * n

        elif key == "NATR":
            try:
                atr = ta.volatility.AverageTrueRange(high=high, low=low, close=close).average_true_range()
                natr = (atr / close) * 100
                result["NATR"] = _clean(natr.tolist())
            except Exception:
                result["NATR"] = [None] * n

        elif key == "HV":
            try:
                log_ret = np.log(close / close.shift(1))
                hv = log_ret.rolling(20).std() * math.sqrt(252) * 100
                result["HV"] = _clean(hv.tolist())
            except Exception:
                result["HV"] = [None] * n

        elif key == "RVI_VOL":
            try:
                period = 14
                std = close.rolling(10).std()
                up_std = std.where(close > close.shift(1), 0.0)
                down_std = std.where(close <= close.shift(1), 0.0)
                ema_up = up_std.ewm(span=period, adjust=False).mean()
                ema_down = down_std.ewm(span=period, adjust=False).mean()
                rvi = 100 * ema_up / (ema_up + ema_down + 1e-10)
                result["RVI_VOL"] = _clean(rvi.tolist())
            except Exception:
                result["RVI_VOL"] = [None] * n

        # ── NEW: Volume ─────────────────────────────────────────────────────────

        elif key == "ADI":
            try:
                result["ADI"] = _clean(
                    ta.volume.AccDistIndexIndicator(high=high, low=low, close=close, volume=volume).acc_dist_index().tolist()
                )
            except Exception:
                result["ADI"] = [None] * n

        elif key == "EOM":
            try:
                result["EOM"] = _clean(
                    ta.volume.EaseOfMovementIndicator(high=high, low=low, volume=volume).ease_of_movement().tolist()
                )
            except Exception:
                result["EOM"] = [None] * n

        elif key == "FI":
            try:
                result["FI"] = _clean(
                    ta.volume.ForceIndexIndicator(close=close, volume=volume, window=13).force_index().tolist()
                )
            except Exception:
                result["FI"] = [None] * n

        elif key == "NVI":
            try:
                result["NVI"] = _clean(
                    ta.volume.NegativeVolumeIndexIndicator(close=close, volume=volume).negative_volume_index().tolist()
                )
            except Exception:
                result["NVI"] = [None] * n

        elif key == "PVI":
            try:
                result["PVI"] = _clean(
                    ta.volume.PositiveVolumeIndexIndicator(close=close, volume=volume).positive_volume_index().tolist()
                )
            except Exception:
                result["PVI"] = [None] * n

        elif key == "VWAP_BANDS":
            try:
                vwap_ind = ta.volume.VolumeWeightedAveragePrice(
                    high=high, low=low, close=close, volume=volume
                )
                vwap_line = vwap_ind.volume_weighted_average_price()
                tp = (high + low + close) / 3
                std = tp.rolling(20).std()
                result["VWAP_UPPER"] = _clean((vwap_line + std).tolist())
                result["VWAP_LOWER"] = _clean((vwap_line - std).tolist())
            except Exception:
                result["VWAP_UPPER"] = [None] * n
                result["VWAP_LOWER"] = [None] * n

        # ── NEW: Statistics / Other ─────────────────────────────────────────────

        elif key == "ZSCORE":
            try:
                period = 20
                mu = close.rolling(period).mean()
                sigma = close.rolling(period).std()
                zscore = (close - mu) / sigma.replace(0, float("nan"))
                result["ZSCORE"] = _clean(zscore.tolist())
            except Exception:
                result["ZSCORE"] = [None] * n

        elif key == "LINREG":
            try:
                period = 14
                vals = [None] * n
                arr = close.values
                for i in range(period - 1, n):
                    y = arr[i - period + 1: i + 1].astype(float)
                    x = np.arange(period, dtype=float)
                    slope, intercept = np.polyfit(x, y, 1)
                    vals[i] = float(slope * (period - 1) + intercept)
                result["LINREG"] = _clean(vals)
            except Exception:
                result["LINREG"] = [None] * n

        elif key == "LINREG_SLOPE":
            try:
                period = 14
                vals = [None] * n
                arr = close.values
                x = np.arange(period, dtype=float)
                for i in range(period - 1, n):
                    y = arr[i - period + 1: i + 1].astype(float)
                    slope = float(np.polyfit(x, y, 1)[0])
                    vals[i] = slope
                result["LINREG_SLOPE"] = _clean(vals)
            except Exception:
                result["LINREG_SLOPE"] = [None] * n

        elif key.startswith("MOMENTUM_"):
            try:
                period = int(key.split("_")[1])
                result[key] = _clean((close - close.shift(period)).tolist())
            except Exception:
                result[key] = [None] * n

    return result
