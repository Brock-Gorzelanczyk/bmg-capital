from __future__ import annotations

"""
Crypto automation engine.

Runs every 15 minutes, 24/7 (no market-hours gate):
  1. Fetch BTC regime (BTC vs 200-day SMA)
  2. Fetch OHLCV bars for all coins in CRYPTO_UNIVERSE via CCXT/Binance
  3. Apply CRYPTO_PRESET_SCREENS → add new candidates
  4. Check entry triggers on candidates → open positions
  5. Expire stale candidates (> CRYPTO_CANDIDATE_MAX_DAYS)
  6. Mark-to-market open positions, apply stop/target/time exits
  7. Write daily log entries
  8. Snapshot equity curve (no weekday restriction)
"""

import asyncio
import logging
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import ta

from app.db.models.strategy import DailyEquitySnapshot, DailyLog, StrategyTrade
from app.db.session import SessionLocal
from app.screener.crypto_filters import (
    CRYPTO_CROSS_SECTIONAL_KEYS,
    CRYPTO_PRESET_LABELS,
    CRYPTO_PRESET_SCREENS,
    CRYPTO_RESTRICTED_UNIVERSES,
    CRYPTO_UNIVERSE,
    NARRATIVE_UNIVERSE,
)
from app.screener.crypto_triggers import (
    CRYPTO_CANDIDATE_MAX_DAYS,
    CRYPTO_CONVICTION,
    CRYPTO_R_MULTIPLE,
    CRYPTO_R_MULTIPLES,
    CRYPTO_RISK_DOLLARS,
    CRYPTO_TRIGGER_MAP,
)

logger = logging.getLogger(__name__)

CRYPTO_PORTFOLIO   = 100_000.0
MAX_CRYPTO_POS_VALUE  = 3_000.0   # cap each crypto position at $3k
MAX_CRYPTO_OPEN       = 15        # max open crypto positions
MAX_CANDIDATES_PER_PRESET = 10
MAX_HOLD_DAYS         = 21        # crypto moves faster — shorter hold


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# OHLCV fetch via CCXT (Binance public)
# ---------------------------------------------------------------------------

def _ccxt_sym_to_yf(sym: str) -> str:
    """
    Convert a CCXT symbol to a yfinance ticker.

    Examples:
      BTC/USDT        → BTC-USD
      ETH/USDT        → ETH-USD
      BTC/USDT:USDT   → BTC-USD   (perp futures — strip the colon suffix first)
      SOL/BTC         → SOL-BTC
      MATIC/USDT      → MATIC-USD
    """
    # Strip perpetual futures suffix (e.g. BTC/USDT:USDT → BTC/USDT)
    if ":" in sym:
        sym = sym.split(":")[0]
    # Replace USDT quote → USD (yfinance uses USD not USDT)
    base, _, quote = sym.partition("/")
    if not quote:
        return sym  # unexpected format — return as-is
    yf_quote = "USD" if quote == "USDT" else quote
    return f"{base}-{yf_quote}"


def _fetch_crypto_bars(symbols: List[str], timeframe: str = "1h", limit: int = 500) -> Dict[str, pd.DataFrame]:
    """Fetch OHLCV bars. Source priority:
      1. Kraken public OHLC REST (no auth, not geo-blocked) — PRIMARY
      2. Binance via CCXT — fallback for any symbol Kraken misses
      3. yfinance — last resort

    Returns {symbol: DataFrame(open, high, low, close, volume)}.
    """
    bars: Dict[str, pd.DataFrame] = {}

    # ── 1. Kraken public OHLC ─────────────────────────────────────────────────
    # Proven to work from Railway. No auth required.
    # endpoint: /0/public/OHLC?pair=XBTUSD&interval=60
    # Response: {"result": {"XXBTZUSD": [[ts, o, h, l, c, vwap, vol, cnt], ...], "last": N}}
    _KRAKEN_INTERVAL: Dict[str, int] = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
    }
    kraken_interval = _KRAKEN_INTERVAL.get(timeframe, 60)

    # Reuse the pair map that live_prices.py already maintains
    from app.services.live_prices import _TO_KRAKEN_PAIR, _KRAKEN_RESPONSE_KEY

    import json as _json
    import urllib.request as _urllib_req

    for sym in symbols:
        pair = _TO_KRAKEN_PAIR.get(sym)
        if not pair:
            if "/" in sym:
                base = sym.split("/")[0]
                if base == "BTC":
                    base = "XBT"
                pair = f"{base}USD"
            else:
                continue

        url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={kraken_interval}"
        try:
            req = _urllib_req.Request(url, headers={"User-Agent": "bmg-capital/1.0"})
            with _urllib_req.urlopen(req, timeout=12) as resp:
                data = _json.loads(resp.read())

            if data.get("error"):
                logger.debug(f"[crypto] Kraken OHLC error for {sym}: {data['error']}")
                continue

            result = data.get("result", {})
            # Try normalised key first, then raw pair name, then any list value
            response_key = _KRAKEN_RESPONSE_KEY.get(pair, pair)
            ohlc = result.get(response_key) or result.get(pair)
            if not ohlc:
                for k, v in result.items():
                    if k != "last" and isinstance(v, list):
                        ohlc = v
                        break

            if not ohlc:
                logger.debug(f"[crypto] Kraken OHLC: no rows for {sym} (pair={pair})")
                continue

            # Each row: [time, open, high, low, close, vwap, volume, count]
            rows = ohlc[-limit:]
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vwap", "volume", "count"])
            df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s")
            df.set_index("ts", inplace=True)
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = df[col].astype(float)

            bars[sym] = df
            logger.info(f"[crypto] Kraken OHLC: {len(df)} bars for {sym}")

        except Exception as e:
            logger.debug(f"[crypto] Kraken OHLC failed for {sym}: {e}")

    # ── 2. Binance / CCXT fallback ────────────────────────────────────────────
    missing = [s for s in symbols if s not in bars]
    if missing:
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True, "timeout": 10000})
            ccxt_geo_blocked = False
            for sym in missing:
                if ccxt_geo_blocked:
                    break
                try:
                    ohlcv = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
                    if not ohlcv:
                        continue
                    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
                    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
                    df.set_index("ts", inplace=True)
                    bars[sym] = df
                    logger.debug(f"[crypto] CCXT Binance: {len(df)} bars for {sym}")
                except Exception as e:
                    err_str = str(e)
                    if "451" in err_str or "restricted location" in err_str.lower():
                        logger.debug(f"[crypto] Binance geo-blocked (451) — skipping remaining CCXT symbols")
                        ccxt_geo_blocked = True
                        break
                    logger.debug(f"[crypto] CCXT fetch failed for {sym}: {e}")
        except Exception as e:
            logger.debug(f"[crypto] CCXT unavailable: {e}")

    # ── 3. yfinance last resort ───────────────────────────────────────────────
    missing = [s for s in symbols if s not in bars]
    if missing:
        import yfinance as yf
        _YF_TF: Dict[str, tuple] = {
            "1m": ("1m", "7d"), "5m": ("5m", "60d"), "15m": ("15m", "60d"),
            "30m": ("30m", "60d"), "1h": ("1h", "730d"), "4h": ("1h", "730d"),
            "1d": ("1d", "2y"), "1w": ("1wk", "5y"),
        }
        yf_interval, yf_period = _YF_TF.get(timeframe, ("1d", "2y"))
        for sym in missing:
            yf_sym = _ccxt_sym_to_yf(sym)
            try:
                df = yf.download(yf_sym, period=yf_period, interval=yf_interval, progress=False, auto_adjust=True)
                if df.empty:
                    logger.warning("[crypto] yfinance empty for %s (as %s)", sym, yf_sym)
                    continue
                if hasattr(df.columns, "levels"):
                    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
                else:
                    df.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in df.columns]
                if "close" not in df.columns:
                    continue
                bars[sym] = df
                logger.warning("[crypto] yfinance: %d bars for %s", len(df), sym)
            except Exception as e:
                logger.warning("[crypto] yfinance failed for %s: %s", sym, e)

    logger.info(f"[crypto] _fetch_crypto_bars: {len(bars)}/{len(symbols)} symbols returned data")
    return bars


def _get_crypto_prices(symbols: List[str], bars: Dict[str, pd.DataFrame]) -> Dict[str, float]:
    """Extract latest close price for each symbol from already-fetched bars."""
    prices: Dict[str, float] = {}
    for sym in symbols:
        df = bars.get(sym)
        if df is not None and not df.empty:
            prices[sym] = float(df["close"].iloc[-1])
    return prices


# ---------------------------------------------------------------------------
# Regime check: BTC vs 200-day SMA
# ---------------------------------------------------------------------------

def _check_crypto_regime(bars: Dict[str, pd.DataFrame]) -> str:
    df = bars.get("BTC/USDT")
    if df is None or len(df) < 200:
        return "unknown"
    try:
        sma200 = df["close"].rolling(200).mean().iloc[-1]
        return "bull" if df["close"].iloc[-1] > sma200 else "risk_off"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Screening helpers
# ---------------------------------------------------------------------------

def _apply_crypto_filters(df: pd.DataFrame, filter_specs: list[dict], symbol: str = "") -> bool:
    """Return True if all filter specs match the given OHLCV DataFrame."""
    for spec in filter_specs:
        ftype = spec.get("type")
        op    = spec.get("operator", "gt")
        val   = spec.get("value", 0)

        try:
            # ── Original filter types ─────────────────────────────────────────
            if ftype == "RSI":
                if len(df) < 16:
                    return False
                rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
                last_rsi = float(rsi.iloc[-1])
                if pd.isna(last_rsi):
                    return False
                if op == "lt"  and not last_rsi < val: return False
                if op == "gt"  and not last_rsi > val: return False
                if op == "lte" and not last_rsi <= val: return False
                if op == "gte" and not last_rsi >= val: return False

            elif ftype == "MACross":
                if len(df) < 55:
                    return False
                ma50  = df["close"].rolling(50).mean().iloc[-1]
                ma200 = df["close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else None
                if val == "golden":
                    if ma200 is None or pd.isna(ma50) or pd.isna(ma200):
                        return False
                    if not (ma50 > ma200):
                        return False
                elif val == "death":
                    if ma200 is None or pd.isna(ma50) or pd.isna(ma200):
                        return False
                    if not (ma50 < ma200):
                        return False

            elif ftype == "PriceVsMA":
                window = 50 if "50" in spec.get("field", "") else 200
                if len(df) < window:
                    return False
                ma = df["close"].rolling(window).mean().iloc[-1]
                if pd.isna(ma):
                    return False
                diff = float(df["close"].iloc[-1]) - float(ma)
                if op == "gt"  and not diff > 0: return False
                if op == "lt"  and not diff < 0: return False
                if op == "gte" and not diff >= 0: return False
                if op == "lte" and not diff <= 0: return False

            elif ftype == "VolumeSurge":
                if len(df) < 21:
                    return False
                vol_avg  = float(df["volume"].iloc[-21:-1].mean())
                last_vol = float(df["volume"].iloc[-1])
                mult = last_vol / vol_avg if vol_avg > 0 else 0.0
                if op == "gte" and not mult >= val: return False
                if op == "gt"  and not mult > val: return False

            elif ftype == "Breakout":
                period = int(val) if val else 30
                if len(df) < period + 1:
                    return False
                high_n = float(df["close"].iloc[-(period + 1):-1].max())
                if not float(df["close"].iloc[-1]) > high_n:
                    return False

            # ── Phase 1 filter types ──────────────────────────────────────────

            elif ftype == "ZScore":
                period = int(spec.get("period", 20))
                if len(df) < period + 2:
                    return False
                window_data = df["close"].iloc[-period:]
                mean = float(window_data.mean())
                std  = float(window_data.std())
                if std <= 0:
                    return False
                zscore = (float(df["close"].iloc[-1]) - mean) / std
                if op == "lt"  and not zscore < val:  return False
                if op == "gt"  and not zscore > val:  return False
                if op == "lte" and not zscore <= val: return False
                if op == "gte" and not zscore >= val: return False

            elif ftype == "TSMOM":
                lookback = int(spec.get("lookback_days", 365))
                skip     = int(spec.get("skip_days", 30))
                needed   = lookback + skip + 5
                if len(df) < needed:
                    return False
                ret = float(df["close"].iloc[-skip]) / float(df["close"].iloc[-(lookback + skip)]) - 1
                if op == "gt"  and not ret > val:  return False
                if op == "lt"  and not ret < val:  return False
                if op == "gte" and not ret >= val: return False

            elif ftype == "PiCycle":
                if len(df) < 360:
                    return False
                ma111 = df["close"].rolling(111).mean().iloc[-1]
                ma350 = df["close"].rolling(350).mean().iloc[-1]
                if pd.isna(ma111) or pd.isna(ma350) or float(ma350) <= 0:
                    return False
                ratio = float(ma111) / (2.0 * float(ma350))
                if op == "lt"  and not ratio < val:  return False
                if op == "gt"  and not ratio > val:  return False
                if op == "lte" and not ratio <= val: return False
                if op == "gte" and not ratio >= val: return False

            elif ftype == "PriceNearMA":
                period        = int(spec.get("period", 200))
                max_pct_above = float(spec.get("max_pct_above", 0.10))
                max_pct_below = float(spec.get("max_pct_below", 0.20))
                if len(df) < period:
                    return False
                ma = df["close"].rolling(period).mean().iloc[-1]
                if pd.isna(ma) or float(ma) <= 0:
                    return False
                pct_diff = (float(df["close"].iloc[-1]) - float(ma)) / float(ma)
                if pct_diff > max_pct_above or pct_diff < -max_pct_below:
                    return False

            elif ftype == "HalvingPhase":
                from datetime import date as _date
                phases       = spec.get("phases", [])
                last_halving = _date(2024, 4, 20)
                next_halving = _date(2028, 4, 1)
                today        = _date.today()
                days_since   = (today - last_halving).days
                days_to      = (next_halving - today).days
                active = (
                    ("pre_halving"       in phases and days_to <= 365) or
                    ("post_halving_bull" in phases and 0 <= days_since <= 730)
                )
                if not active:
                    return False

            # ── Phase 2 on-chain filter types ─────────────────────────────────

            elif ftype == "OnChainNUPL":
                from app.services.onchain import get_btc_onchain_metrics
                metrics = get_btc_onchain_metrics()
                if not metrics.get("ok"):
                    return False
                nupl = metrics.get("nupl", 0.5)
                if op == "lt"  and not nupl < val:  return False
                if op == "gt"  and not nupl > val:  return False
                if op == "lte" and not nupl <= val: return False
                if op == "gte" and not nupl >= val: return False

            elif ftype == "OnChainMVRV":
                from app.services.onchain import get_btc_onchain_metrics
                metrics = get_btc_onchain_metrics()
                if not metrics.get("ok"):
                    return False
                z     = metrics.get("mvrv_zscore", 0.0)
                z_op  = spec.get("zscore_operator", "lt")
                z_val = float(spec.get("zscore_value", 2.0))
                if z_op == "lt"  and not z < z_val:  return False
                if z_op == "gt"  and not z > z_val:  return False
                if z_op == "lte" and not z <= z_val: return False
                if z_op == "gte" and not z >= z_val: return False

            elif ftype == "OnChainSOPR":
                from app.services.onchain import get_btc_onchain_metrics
                metrics  = get_btc_onchain_metrics()
                if not metrics.get("ok"):
                    return False
                sopr  = metrics.get("sopr_proxy", 1.0)
                min_v = float(spec.get("min_value", 0.0))
                max_v = float(spec.get("max_value", 2.0))
                if not (min_v <= sopr <= max_v):
                    return False

            elif ftype == "OnChainNetflow":
                from app.services.onchain import get_exchange_netflow_proxy
                data = get_exchange_netflow_proxy()
                if not data.get("ok"):
                    return False
                if data.get("signal") != spec.get("signal", "outflow"):
                    return False

            elif ftype == "OnChainSSR":
                from app.services.onchain import get_stablecoin_supply_ratio
                data = get_stablecoin_supply_ratio()
                if not data.get("ok"):
                    return False
                if data.get("signal") != spec.get("signal", "low"):
                    return False

            # ── Phase 3 derivatives filter types ──────────────────────────────

            elif ftype == "FundingRate":
                from app.services.derivatives import get_funding_rate, ccxt_to_futures
                fsym  = ccxt_to_futures(symbol) if symbol else ""
                if not fsym:
                    return False
                rates = get_funding_rate(fsym)
                if not rates.get("ok"):
                    return False
                latest    = rates.get("latest", 0.0)
                condition = spec.get("condition", "")
                threshold = float(spec.get("threshold", 0.0))
                if condition == "extreme_negative":
                    if not latest < threshold:
                        return False
                elif condition == "above":
                    if not latest > threshold:
                        return False
                elif condition == "persistently_positive":
                    min_bars = int(spec.get("min_bars", 3))
                    recent   = rates.get("recent", [])
                    if len(recent) < min_bars or not all(r > threshold for r in recent[:min_bars]):
                        return False

            elif ftype == "OIDivergence":
                from app.services.derivatives import get_oi_history, ccxt_to_futures
                fsym = ccxt_to_futures(symbol) if symbol else ""
                if not fsym:
                    return False
                oi = get_oi_history(fsym, period="1d", limit=14)
                if not oi.get("ok"):
                    return False
                # Price trend over the same 14-day window
                if len(df) < 15:
                    return False
                price_change = float(df["close"].iloc[-1]) / float(df["close"].iloc[-15]) - 1
                price_falling = price_change < -0.03   # >3% drop
                oi_falling    = oi.get("direction") == "falling"
                if spec.get("price_falling", True) and not price_falling:
                    return False
                if spec.get("oi_falling", True) and not oi_falling:
                    return False

            elif ftype == "WhaleAccumulation":
                from app.services.whale import get_large_holder_signal
                sig = get_large_holder_signal(symbol)
                if not sig.get("ok") or sig.get("signal") != spec.get("signal", "accumulating"):
                    return False

        except Exception as e:
            logger.debug(f"Filter error ({ftype}): {e}")
            return False

    return True


def _collect_crypto_screen_results(
    regime: str, bars: Dict[str, pd.DataFrame]
) -> Dict[str, Set[str]]:
    results: Dict[str, Set[str]] = {}
    for preset_key, filter_specs in CRYPTO_PRESET_SCREENS.items():
        # Cross-sectional strategies are handled separately
        if preset_key in CRYPTO_CROSS_SECTIONAL_KEYS:
            continue
        # Use restricted universe if defined, otherwise screen all bars
        universe = CRYPTO_RESTRICTED_UNIVERSES.get(preset_key, list(bars.keys()))
        hits: Set[str] = set()
        for sym in universe:
            df = bars.get(sym)
            if df is None or df.empty:
                continue
            try:
                if _apply_crypto_filters(df, filter_specs, symbol=sym):
                    hits.add(sym)
            except Exception as e:
                logger.debug(f"Screen error {preset_key}/{sym}: {e}")
        results[preset_key] = hits
        logger.debug(f"Crypto screen {preset_key}: {len(hits)} hits")
    return results


def _collect_cross_sectional_results(
    bars: Dict[str, pd.DataFrame],
    btc_sym: str = "BTC/USDT",
) -> Dict[str, Set[str]]:
    """
    Compute signals for strategies requiring cross-coin comparisons.
    Returns {preset_key: {symbols}} for candidate creation.
    """
    results: Dict[str, Set[str]] = {}

    # ── Cross-Sectional Momentum (top 25% by 90-day return) ──────────────────
    returns_90d: List[tuple] = []
    for sym, df in bars.items():
        if len(df) >= 91:
            try:
                ret = float(df["close"].iloc[-1]) / float(df["close"].iloc[-91]) - 1
                returns_90d.append((sym, ret))
            except (IndexError, ZeroDivisionError):
                pass
    if len(returns_90d) >= 4:
        returns_90d.sort(key=lambda x: x[1], reverse=True)
        top_n = max(1, len(returns_90d) // 4)
        results["cross_sectional_momentum"] = {sym for sym, _ in returns_90d[:top_n]}
        logger.debug(f"cross_sectional_momentum: top {top_n} of {len(returns_90d)} coins")

    # ── Altseason Index (≥75% of alts outperforming BTC over 90 days) ────────
    btc_df = bars.get(btc_sym)
    if btc_df is not None and len(btc_df) >= 91:
        try:
            btc_ret = float(btc_df["close"].iloc[-1]) / float(btc_df["close"].iloc[-91]) - 1
            alts = {sym: df for sym, df in bars.items() if sym != btc_sym}
            valid_alts = {sym: df for sym, df in alts.items() if len(df) >= 91}
            if valid_alts:
                outperformers = sum(
                    1 for sym, df in valid_alts.items()
                    if float(df["close"].iloc[-1]) / float(df["close"].iloc[-91]) - 1 > btc_ret
                )
                if outperformers / len(valid_alts) >= 0.75:
                    results["altseason_index"] = set(valid_alts.keys())
                    logger.debug(f"altseason_index: ACTIVE ({outperformers}/{len(valid_alts)} outperforming BTC)")
        except Exception as e:
            logger.debug(f"altseason_index error: {e}")

    # ── ETH/BTC Ratio above its 50-day MA ────────────────────────────────────
    eth_df = bars.get("ETH/USDT")
    if eth_df is not None and btc_df is not None and len(eth_df) >= 51 and len(btc_df) >= 51:
        try:
            eth_close = eth_df["close"]
            btc_close = btc_df["close"].reindex(eth_df.index, method="nearest")
            ratio = eth_close / btc_close
            ratio_ma50 = ratio.rolling(50).mean()
            if float(ratio.iloc[-1]) > float(ratio_ma50.iloc[-1]):
                results["eth_btc_ratio"] = {"ETH/USDT"}
                logger.debug("eth_btc_ratio: ACTIVE — ratio above 50MA")
        except Exception as e:
            logger.debug(f"eth_btc_ratio error: {e}")

    # ── Narrative Basket (top 3 by 30-day return in narrative universe) ───────
    try:
        returns_30d: List[tuple] = []
        for sym in NARRATIVE_UNIVERSE:
            df = bars.get(sym)
            if df is not None and len(df) >= 31:
                ret = float(df["close"].iloc[-1]) / float(df["close"].iloc[-31]) - 1
                returns_30d.append((sym, ret))
        if len(returns_30d) >= 3:
            returns_30d.sort(key=lambda x: x[1], reverse=True)
            results["narrative_basket"] = {sym for sym, _ in returns_30d[:3]}
            logger.debug(f"narrative_basket: top 3 → {[s for s, _ in returns_30d[:3]]}")
    except Exception as e:
        logger.debug(f"narrative_basket error: {e}")

    return results


# ---------------------------------------------------------------------------
# Candidate management
# ---------------------------------------------------------------------------

def _add_crypto_candidates(
    db, screen_results: Dict[str, Set[str]], today: date, user_id: int
) -> int:
    from sqlalchemy import select
    tracked = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status.in_(["open", "candidate"]),
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
        )
    ).scalars().all()
    existing_pairs: set = {(t.preset_key, t.symbol) for t in tracked}
    cands_per_preset: Dict[str, int] = {}
    for t in tracked:
        if t.status == "candidate":
            cands_per_preset[t.preset_key] = cands_per_preset.get(t.preset_key, 0) + 1

    added = 0
    for preset_key, symbols in screen_results.items():
        watching = cands_per_preset.get(preset_key, 0)
        trigger_fn = CRYPTO_TRIGGER_MAP.get(preset_key)
        trigger_name = trigger_fn.__name__ if trigger_fn else "crypto_auto"
        for sym in symbols:
            if (preset_key, sym) in existing_pairs:
                continue
            if watching >= MAX_CANDIDATES_PER_PRESET:
                break
            trade = StrategyTrade(
                preset_key=preset_key,
                symbol=sym,
                status="candidate",
                candidate_since=_now(),
                entry_trigger=trigger_name,
                entry_price=0.0,
                shares=0.0,
                stop_price=0.0,
                target_price=0.0,
                user_id=user_id,
                asset_class="crypto",
                exchange="binance",
            )
            db.add(trade)
            existing_pairs.add((preset_key, sym))
            watching += 1
            added += 1
            db.add(DailyLog(
                log_date=today,
                event_type="candidate_added",
                symbol=sym,
                preset_key=preset_key,
                preset_label=CRYPTO_PRESET_LABELS.get(preset_key, preset_key),
                notes=f"New crypto candidate: {sym} [{preset_key}]",
                user_id=user_id,
            ))
    return added


def _expire_stale_candidates(db, today: date, user_id: int) -> int:
    from sqlalchemy import select
    candidates = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status == "candidate",
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
        )
    ).scalars().all()
    expired = 0
    for t in candidates:
        if not t.candidate_since:
            continue
        days = (today - t.candidate_since.date()).days
        if days >= CRYPTO_CANDIDATE_MAX_DAYS:
            t.status = "closed"
            t.exit_reason = "expired"
            t.exit_date = _now()
            db.add(t)
            expired += 1
    return expired


# ---------------------------------------------------------------------------
# Entry trigger check → open positions
# ---------------------------------------------------------------------------

def _check_entry_triggers(
    db, bars: Dict[str, pd.DataFrame], prices: Dict[str, float], today: date, user_id: int
) -> int:
    from sqlalchemy import select
    candidates = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status == "candidate",
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
        )
    ).scalars().all()

    open_count = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status == "open",
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
        )
    ).scalars().all()

    if len(open_count) >= MAX_CRYPTO_OPEN:
        return 0

    entries = 0
    for cand in candidates:
        df = bars.get(cand.symbol)
        trigger_fn = CRYPTO_TRIGGER_MAP.get(cand.preset_key)
        if df is None or trigger_fn is None:
            continue
        try:
            if not trigger_fn(cand.symbol, df):
                continue
        except Exception:
            continue

        price = prices.get(cand.symbol)
        if not price or price <= 0:
            continue

        try:
            atr_series = ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            ).average_true_range()
            atr = float(atr_series.iloc[-1])
            if atr <= 0:
                atr = price * 0.03
        except Exception:
            atr = price * 0.03

        conviction = CRYPTO_CONVICTION.get(cand.preset_key, 1.0)
        r_mult     = CRYPTO_R_MULTIPLES.get(cand.preset_key, CRYPTO_R_MULTIPLE)
        stop = price - atr * 1.5
        target = price + atr * 1.5 * r_mult
        risk_per_share = price - stop
        if risk_per_share <= 0:
            continue
        shares = min(
            (CRYPTO_RISK_DOLLARS * conviction) / risk_per_share,
            MAX_CRYPTO_POS_VALUE / price,
        )
        if shares <= 0:
            continue

        cand.status = "open"
        cand.entry_price = round(price, 8)
        cand.shares = round(shares, 8)
        cand.stop_price = round(stop, 8)
        cand.target_price = round(target, 8)
        cand.entry_date = _now()
        cand.atr = round(atr, 8)
        cand.risk_dollars = round(CRYPTO_RISK_DOLLARS * conviction, 2)
        cand.last_known_price = round(price, 8)
        db.add(cand)
        db.add(DailyLog(
            log_date=today,
            event_type="entry",
            symbol=cand.symbol,
            preset_key=cand.preset_key,
            preset_label=CRYPTO_PRESET_LABELS.get(cand.preset_key, cand.preset_key),
            price=round(price, 8),
            notes=f"Crypto entry: {cand.symbol} @ {price:.4f} | stop {stop:.4f} | target {target:.4f}",
            trade_id=cand.id,
            user_id=user_id,
        ))
        entries += 1

    return entries


# ---------------------------------------------------------------------------
# Exit management
# ---------------------------------------------------------------------------

def _settle_crypto_positions(
    db, bars: Dict[str, pd.DataFrame], prices: Dict[str, float], today: date, user_id: int
) -> int:
    from sqlalchemy import select
    open_trades = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status == "open",
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
        )
    ).scalars().all()

    exits = 0
    for t in open_trades:
        price = prices.get(t.symbol)
        if not price or price <= 0:
            continue
        t.last_known_price = price
        days_held = (today - t.entry_date.date()).days if t.entry_date else 0
        reason: Optional[str] = None
        if price <= t.stop_price:
            reason = "stop_loss"
        elif price >= t.target_price:
            reason = "profit_target"
        elif days_held >= MAX_HOLD_DAYS:
            reason = "time_stop"
        if reason:
            pnl_pct = (price - t.entry_price) / t.entry_price * 100
            t.status = "closed"
            t.exit_price = round(price, 8)
            t.exit_date = _now()
            t.exit_reason = reason
            db.add(t)
            db.add(DailyLog(
                log_date=today,
                event_type="exit",
                symbol=t.symbol,
                preset_key=t.preset_key,
                preset_label=CRYPTO_PRESET_LABELS.get(t.preset_key or "", t.preset_key),
                price=round(price, 8),
                pnl_pct=round(pnl_pct, 2),
                notes=f"Crypto exit ({reason}): {t.symbol} @ {price:.4f} | P&L {pnl_pct:+.2f}%",
                trade_id=t.id,
                user_id=user_id,
            ))
            exits += 1
        else:
            db.add(t)

    return exits


# ---------------------------------------------------------------------------
# Equity snapshot
# ---------------------------------------------------------------------------

def _snapshot_crypto_equity(
    db, prices: Dict[str, float], user_id: int
) -> None:
    from sqlalchemy import select
    today = date.today()
    open_trades = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status == "open",
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
        )
    ).scalars().all()

    open_pnl = sum(
        ((prices.get(t.symbol) or t.last_known_price or t.entry_price) - t.entry_price) * t.shares
        for t in open_trades
        if t.entry_price and t.entry_price > 0 and t.shares
    )
    closed_today = db.execute(
        select(StrategyTrade).where(
            StrategyTrade.status == "closed",
            StrategyTrade.user_id == user_id,
            StrategyTrade.asset_class == "crypto",
            StrategyTrade.exit_date >= datetime.combine(today, datetime.min.time()),
        )
    ).scalars().all()
    realized_today = sum(
        (t.exit_price - t.entry_price) * t.shares
        for t in closed_today
        if t.exit_price and t.entry_price and t.entry_price > 0 and t.shares
    )
    portfolio_value = CRYPTO_PORTFOLIO + open_pnl + realized_today

    db.add(DailyEquitySnapshot(
        snapshot_date=today,
        portfolio_value=round(portfolio_value, 2),
        realized_pnl=round(realized_today, 2),
        open_pnl=round(open_pnl, 2),
        open_positions=len(open_trades),
        candidates=0,
        new_entries=0,
        exits_today=len(closed_today),
        user_id=user_id,
        asset_class="crypto",
    ))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _prefetch_onchain() -> None:
    """Warm on-chain and derivatives caches before the screening loop."""
    from app.services.onchain import prefetch_all as _oc_prefetch
    from app.services.derivatives import prefetch_derivatives
    _oc_prefetch()
    # Pre-warm funding + OI for the derivative strategy universes
    prefetch_derivatives([
        "BTC/USDT", "ETH/USDT", "SOL/USDT",
    ])
    from app.services.whale import prefetch_whale
    prefetch_whale(["BTC/USDT", "ETH/USDT"])


async def run_crypto_automation(user_id: int) -> Dict[str, Any]:
    logger.info(f"[crypto] Starting automation for user {user_id} — universe={len(CRYPTO_UNIVERSE)} coins")
    loop = asyncio.get_running_loop()
    today = date.today()
    fetch_errors: List[str] = []

    # Pre-warm on-chain caches (1-hour TTL; no-ops if cache is fresh)
    try:
        await loop.run_in_executor(None, _prefetch_onchain)
        logger.info("[crypto] On-chain/derivatives cache pre-warm complete")
    except Exception as e:
        logger.warning(f"[crypto] On-chain pre-warm failed (non-fatal): {e}")

    # Fetch bars for all coins in universe
    logger.info(f"[crypto] Fetching OHLCV bars for {len(CRYPTO_UNIVERSE)} coins…")
    bars = await loop.run_in_executor(None, lambda: _fetch_crypto_bars(CRYPTO_UNIVERSE))
    coins_attempted = len(CRYPTO_UNIVERSE)
    coins_fetched = len(bars)

    if not bars:
        # This should be very rare — log clearly but DON'T raise so the scan still completes
        msg = (
            f"[crypto] WARNING: 0/{coins_attempted} coins returned bars — "
            "both CCXT and yfinance failed. Returning empty result."
        )
        logger.error(msg)
        return {
            "regime": "unknown",
            "coins_attempted": coins_attempted,
            "coins_scanned": 0,
            "new_candidates": 0,
            "entries": 0,
            "exits": 0,
            "expired": 0,
            "error": msg,
            "fetch_errors": fetch_errors,
        }

    missing = [s for s in CRYPTO_UNIVERSE if s not in bars]
    if missing:
        logger.warning(f"[crypto] {len(missing)} coins returned no data: {missing}")

    prices = _get_crypto_prices(list(bars.keys()), bars)
    regime = _check_crypto_regime(bars)
    logger.info(
        f"[crypto] Regime={regime} | bars={coins_fetched}/{coins_attempted} | "
        f"price samples={len(prices)}"
    )

    screen_results = _collect_crypto_screen_results(regime, bars)
    cross_results  = _collect_cross_sectional_results(bars)
    # Merge: per-coin screens + cross-sectional screens
    all_results: Dict[str, Set[str]] = {**screen_results, **cross_results}

    total_hits = sum(len(s) for s in all_results.values())
    logger.info(
        f"[crypto] Screen complete: {total_hits} total hits across "
        f"{len([k for k, s in all_results.items() if s])} active strategies"
    )
    for key, syms in all_results.items():
        if syms:
            logger.info(f"[crypto]   {key}: {sorted(syms)}")

    db = SessionLocal()
    expired = 0
    try:
        new_cands = _add_crypto_candidates(db, all_results, today, user_id)
        db.commit()
        logger.info(f"[crypto] Added {new_cands} new candidates to DB")

        expired = _expire_stale_candidates(db, today, user_id)
        if expired:
            db.commit()
            logger.info(f"[crypto] Expired {expired} stale candidates")

        entries = _check_entry_triggers(db, bars, prices, today, user_id)
        if entries:
            db.commit()
            logger.info(f"[crypto] Opened {entries} new positions")

        exits = _settle_crypto_positions(db, bars, prices, today, user_id)
        if exits:
            db.commit()
            logger.info(f"[crypto] Closed {exits} positions")

        _snapshot_crypto_equity(db, prices, user_id)
        db.commit()

        logger.info(
            f"[crypto] Automation complete for user {user_id}: "
            f"coins={coins_fetched}/{coins_attempted} | cands={new_cands} | "
            f"entries={entries} | exits={exits} | expired={expired}"
        )
        return {
            "regime": regime,
            "coins_attempted": coins_attempted,
            "coins_scanned": coins_fetched,
            "new_candidates": new_cands,
            "entries": entries,
            "exits": exits,
            "expired": expired,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"[crypto] Automation DB error for user {user_id}: {e}", exc_info=True)
        raise
    finally:
        db.close()
