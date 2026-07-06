from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import timezone, datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.indicators.engine import compute_indicators
from app.services.bar_cache import get_cached, set_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bars", tags=["bars"])

# Module-level price cache: sym -> (price, timestamp)
_price_cache: dict[str, tuple[float, float]] = {}

# Known crypto base tickers → yfinance format (BASE → BASE-USD)
_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "DOT", "MATIC",
    "LINK", "UNI", "ATOM", "LTC", "ETC", "BCH", "NEAR", "APT", "OP", "ARB",
    "SUI", "SEI", "TIA", "INJ", "PYTH", "JUP", "BONK", "WIF", "PEPE",
    "FET", "RENDER", "IMX", "GRT", "SAND", "MANA", "AXS", "ENJ", "CHZ",
    "SHIB", "FLOKI", "VET", "ALGO", "XLM", "TRX", "FIL", "AAVE", "MKR",
    "SNX", "COMP", "CRV", "1INCH", "SUSHI", "YFI", "BAL", "LDO", "RPL",
    "CAKE", "RUNE", "LUNA", "USTC", "EOS", "ZEC", "DASH", "XMR", "QTUM",
    "WAVES", "ZIL", "NEO", "ONT", "ICX", "IOTA", "HBAR", "EGLD",
}

# Extended crypto identifiers people might type
_CRYPTO_ALIASES = {
    "BITCOIN": "BTC-USD",
    "ETHEREUM": "ETH-USD",
    "SOLANA": "SOL-USD",
    "RIPPLE": "XRP-USD",
    "CARDANO": "ADA-USD",
    "DOGECOIN": "DOGE-USD",
    "LITECOIN": "LTC-USD",
    "BINANCE": "BNB-USD",
    "POLYGON": "MATIC-USD",
    "CHAINLINK": "LINK-USD",
    "UNISWAP": "UNI-USD",
    "POLKADOT": "DOT-USD",
    "AVALANCHE": "AVAX-USD",
    "COSMOS": "ATOM-USD",
    "NEAR PROTOCOL": "NEAR-USD",
    "SHIBA INU": "SHIB-USD",
    # Also handle slash-pair formats: BTC/USD → BTC-USD
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "SOL/USD": "SOL-USD",
    "AVAX/USD": "AVAX-USD",
    "MATIC/USD": "MATIC-USD",
    "LINK/USD": "LINK-USD",
    "DOT/USD": "DOT-USD",
    "BNB/USD": "BNB-USD",
    "ADA/USD": "ADA-USD",
    "XRP/USD": "XRP-USD",
    "DOGE/USD": "DOGE-USD",
}


def _normalize_symbol(raw: str) -> str:
    """
    Convert user-entered symbol to yfinance format.
    BTC → BTC-USD  |  BTC/USD → BTC-USD  |  AAPL → AAPL (unchanged)
    """
    upper = raw.upper().strip()
    # Alias table first (catches BTC/USD, BITCOIN, etc.)
    if upper in _CRYPTO_ALIASES:
        return _CRYPTO_ALIASES[upper]
    # Slash → hyphen (BTC/USDT → BTC-USDT handled by _fetch_ccxt_ohlcv)
    if "/" in upper:
        base, quote = upper.split("/", 1)
        quote = "USD" if quote in ("USDT", "BUSD", "USDC") else quote
        return f"{base}-{quote}"
    # Plain base like BTC/ETH/SOL with no suffix → add -USD
    if upper in _CRYPTO_BASES:
        return f"{upper}-USD"
    return upper


YF_INTERVAL_MAP = {
    "1Min": "1m",
    "5Min": "5m",
    "15Min": "15m",
    "30Min": "30m",
    "1Hour": "1h",
    "4Hour": "1h",   # download 1h, resample to 4h
    "1Day": "1d",
    "1Week": "1wk",
    "1Month": "1mo",
}

# yfinance enforces max lookback per interval
YF_MAX_DAYS: dict[str, int] = {
    "1Min": 7,
    "5Min": 59,
    "15Min": 59,
    "30Min": 59,
    "1Hour": 729,
    "4Hour": 729,
}

# Timeframes that support indicator warm-up (daily and coarser only)
DAILY_TIMEFRAMES = {"1Day", "1Week", "1Month"}

# Calendar days per bar for each timeframe (with a ~10% buffer baked in)
_DAYS_PER_BAR: dict[str, float] = {
    "1Day":   1.5,   # ~1 trading day = 1.4 calendar days; +buffer
    "1Week":  7.5,   # 1 week = 7 calendar days; +buffer
    "1Month": 33.0,  # ~1 month = 30-31 calendar days; +buffer
}


def _max_indicator_lookback(indicators_str: Optional[str]) -> int:
    """Return the largest period in indicator keys (e.g. SMA_200 → 200, ICHIMOKU → 52)."""
    if not indicators_str:
        return 0
    max_p = 0
    for key in indicators_str.split(","):
        key = key.strip()
        parts = key.split("_")
        if len(parts) >= 2:
            try:
                max_p = max(max_p, int(parts[-1]))
            except ValueError:
                pass
        if key == "MACD":
            max_p = max(max_p, 26)
        if key == "ICHIMOKU":
            max_p = max(max_p, 52)
        if key in ("DONCHIAN", "KELTNER"):
            max_p = max(max_p, 20)
    return max_p


_CCXT_TF_MAP = {
    "1Min": "1m", "5Min": "5m", "15Min": "15m", "30Min": "30m",
    "1Hour": "1h", "4Hour": "4h", "1Day": "1d", "1Week": "1w", "1Month": "1M",
}


def _fetch_ccxt_ohlcv(symbol: str, timeframe: str, start_str: str) -> list[dict]:
    """CCXT/Binance fallback for crypto symbols like FET-USD → FET/USDT."""
    try:
        import ccxt
        base = symbol.upper().replace("-USD", "").replace("-USDT", "")
        ccxt_sym = f"{base}/USDT"
        ccxt_tf = _CCXT_TF_MAP.get(timeframe, "1d")
        since = int(datetime.fromisoformat(start_str).timestamp() * 1000)
        exchange = ccxt.binance({"enableRateLimit": True})
        ohlcv = exchange.fetch_ohlcv(ccxt_sym, timeframe=ccxt_tf, since=since, limit=1000)
        return [
            {
                "_t": datetime.utcfromtimestamp(r[0] / 1000).isoformat(),
                "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5],
            }
            for r in ohlcv if r[4] is not None
        ]
    except Exception:
        return []


def _apply_split_adjustment(hist: pd.DataFrame) -> pd.DataFrame:
    """Apply split-only backward adjustment — no dividend adjustment (matches TradingView default)."""
    if hist.empty or "Stock Splits" not in hist.columns:
        return hist
    splits = hist["Stock Splits"]
    splits = splits[splits > 0]
    if splits.empty:
        return hist
    result = hist.copy()
    idx = result.index
    # Normalize index to tz-naive for comparison
    idx_naive = idx.tz_localize(None) if getattr(idx, 'tz', None) else idx
    for split_date, split_ratio in splits.items():
        sd = pd.Timestamp(split_date)
        sd_naive = sd.tz_localize(None) if sd.tz else sd
        mask = idx_naive < sd_naive
        if not mask.any():
            continue
        factor = 1.0 / float(split_ratio)  # 1-for-10 reverse split: ratio=0.1, factor=10
        for col in ("Open", "High", "Low", "Close"):
            if col in result.columns:
                result.loc[mask, col] = result.loc[mask, col] * factor
        if "Volume" in result.columns:
            result.loc[mask, "Volume"] = result.loc[mask, "Volume"] / factor
    return result


def _fetch_yf_ohlcv(ticker: yf.Ticker, start_str: str, end_str: str, interval: str, timeframe: str, adjustment: str = "split") -> list[dict]:
    """Fetch OHLCV from yfinance and return as a list of dicts with open/high/low/close/volume."""
    if adjustment == "none":
        hist = ticker.history(start=start_str, end=end_str, interval=interval, auto_adjust=False)
    elif adjustment == "dividend":
        hist = ticker.history(start=start_str, end=end_str, interval=interval, auto_adjust=True)
    else:  # "split" — split-adjusted only, no dividend adjustment (matches TradingView)
        hist = ticker.history(start=start_str, end=end_str, interval=interval, auto_adjust=False, actions=True)
        hist = _apply_split_adjustment(hist)

    if hist.empty:
        return []

    if timeframe == "4Hour":
        hist = hist.resample("4h", closed="left", label="left").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna(subset=["Open", "Close"])

    rows = []
    for idx, row in hist.iterrows():
        o, h, l, c, v = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row["Volume"])
        if pd.isna(o) or pd.isna(c):
            continue
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v,
                     "_t": idx.isoformat() if hasattr(idx, "isoformat") else str(idx)})
    return rows


class BatchBarsRequest(BaseModel):
    symbols: list[str]
    start: Optional[str] = None
    end: Optional[str] = None
    timeframe: str = "1Day"


async def _fetch_bars_for_symbol(
    symbol: str,
    start: Optional[str],
    end: Optional[str],
    timeframe: str,
) -> dict:
    """Fetch OHLCV bars for a single symbol. Returns same shape as GET /{symbol} (without indicators)."""
    interval = YF_INTERVAL_MAP.get(timeframe, "1d")
    if end:
        end_dt = datetime.fromisoformat(end)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    else:
        end_dt = datetime.now(timezone.utc)

    if not start:
        if timeframe == "1Month":
            days_back = 9125
        elif timeframe == "1Week":
            days_back = 7300
        elif timeframe == "1Day":
            days_back = 5475
        elif timeframe in ("4Hour", "1Hour"):
            days_back = 729
        elif timeframe in ("30Min", "15Min", "5Min"):
            days_back = 59
        else:
            days_back = 7
        max_days = YF_MAX_DAYS.get(timeframe, 20000)
        days_back = min(days_back, max_days)
        start_dt = end_dt - timedelta(days=days_back)
    else:
        start_dt = datetime.fromisoformat(start)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        max_days = YF_MAX_DAYS.get(timeframe)
        if max_days:
            earliest = end_dt - timedelta(days=max_days)
            if start_dt < earliest:
                start_dt = earliest

    start_str = start_dt.date().isoformat()
    end_str = end_dt.date().isoformat()
    end_exclusive = (end_dt + timedelta(days=1)).date().isoformat()

    cached = get_cached(symbol, timeframe, start_str, end_str)
    if cached:
        bars_list = cached
    else:
        ticker = yf.Ticker(symbol.upper())
        rows = _fetch_yf_ohlcv(ticker, start_str, end_exclusive, interval, timeframe)
        if not rows:
            rows = _fetch_ccxt_ohlcv(symbol, timeframe, start_str)
        if not rows:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        bars_list = [
            {"t": r["_t"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]}
            for r in rows
        ]
        ttl = 3600 if timeframe in ("4Hour", "1Hour") else 300 if timeframe in ("30Min", "15Min", "5Min", "1Min") else 86400
        set_cache(symbol, timeframe, start_str, end_str, bars_list, ttl)

    return {"bars": bars_list}


@router.get("/latest")
async def get_latest_prices(
    symbols: str = Query(..., description="Comma-separated symbols e.g. NVDA,AAPL,BTC/USD"),
):
    """Return live prices for up to 30 symbols via exchange-native feeds.

    Crypto → Kraken, Stocks → Alpaca IEX. Falls back to module-level cache
    (max 24h stale) if the exchange feed is unavailable.
    """
    # Normalize: BTC-USD → BTC/USD so live_prices routes correctly
    raw_syms = [s.strip() for s in symbols.split(",") if s.strip()][:30]
    sym_list = [s.replace("-USD", "/USD").upper() if s.upper().endswith("-USD") else _normalize_symbol(s)
                for s in raw_syms]

    now = time.time()

    def _fetch():
        try:
            from app.services.live_prices import fetch_live_prices
            return fetch_live_prices(sym_list)
        except Exception as exc:
            logger.warning("[bars/latest] live_prices fetch failed: %s", exc)
            return {}

    live = await asyncio.to_thread(_fetch)

    prices: dict[str, float | None] = {}
    stale_symbols: list[str] = []

    for sym in sym_list:
        if sym in live and live[sym]:
            price = round(float(live[sym]), 4)
            prices[sym] = price
            _price_cache[sym] = (price, now)
        else:
            cached = _price_cache.get(sym)
            if cached is not None and (now - cached[1]) < 86400:
                prices[sym] = cached[0]
                stale_symbols.append(sym)
            else:
                prices[sym] = None

    return {"prices": prices, "stale_symbols": stale_symbols}


@router.post("/batch")
async def get_bars_batch(body: BatchBarsRequest):
    """Fetch OHLCV bars for multiple symbols in a single request (capped at 20 symbols)."""
    results = {}
    for symbol in body.symbols[:20]:
        try:
            bars_data = await _fetch_bars_for_symbol(symbol, body.start, body.end, body.timeframe)
            results[symbol] = bars_data
        except Exception as e:
            results[symbol] = {"bars": [], "error": str(e)}
    return {"results": results}


@router.get("/{symbol}")
async def get_bars(
    symbol: str,
    response: Response,
    timeframe: str = Query("1Day"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    indicators: Optional[str] = Query(
        None, description="Comma-separated indicator keys, e.g. SMA_20,RSI_14,MACD"
    ),
    adjustment: str = Query("split", description="Price adjustment: split|dividend|none"),
    from_ts: Optional[int] = Query(None, alias="from"),
    to_ts: Optional[int] = Query(None, alias="to"),
    limit: Optional[int] = Query(None),
):
    """Fetch OHLCV bars for a symbol with optional technical indicators."""
    symbol = _normalize_symbol(symbol)
    interval = YF_INTERVAL_MAP.get(timeframe, "1d")

    # Accept Unix timestamps from TradingView datafeed (alias: from/to)
    if from_ts is not None and start is None:
        start = datetime.utcfromtimestamp(from_ts).strftime("%Y-%m-%d")
    if to_ts is not None and end is None:
        end = datetime.utcfromtimestamp(to_ts + 86400).strftime("%Y-%m-%d")  # inclusive

    if end:
        end_dt = datetime.fromisoformat(end)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    else:
        end_dt = datetime.now(timezone.utc)

    if not start:
        if timeframe == "1Month":
            days_back = 9125
        elif timeframe == "1Week":
            days_back = 7300
        elif timeframe == "1Day":
            days_back = 5475
        elif timeframe in ("4Hour", "1Hour"):
            days_back = 729
        elif timeframe in ("30Min", "15Min", "5Min"):
            days_back = 59
        else:
            days_back = 7
        max_days = YF_MAX_DAYS.get(timeframe, 20000)
        days_back = min(days_back, max_days)
        start_dt = end_dt - timedelta(days=days_back)
    else:
        start_dt = datetime.fromisoformat(start)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        max_days = YF_MAX_DAYS.get(timeframe)
        if max_days:
            earliest = end_dt - timedelta(days=max_days)
            if start_dt < earliest:
                start_dt = earliest

    start_str = start_dt.date().isoformat()
    end_str = end_dt.date().isoformat()
    end_exclusive = (end_dt + timedelta(days=1)).date().isoformat()

    # Use adjustment-aware symbol key for cache to prevent cross-contamination
    cache_sym = f"{symbol}_{adjustment}"

    # ── Main bars ──────────────────────────────────────────────────────────────
    cached = get_cached(cache_sym, timeframe, start_str, end_str)
    if cached:
        bars_list = cached
        main_ohlcv = [{"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"]} for b in bars_list]
    else:
        # 2026-07-05 resilience fix: yfinance sync calls used to block the
        # async loop with no timeout. When yfinance hung (rate-limit,
        # transient upstream error, DNS blip), the request would hang past
        # Railway's 30s ingress limit and return a 502 Bad Gateway with no
        # useful error message. Now we run the fetch in a worker thread with
        # a 15s wall-clock cap; on timeout or unhandled provider error we
        # return 503 with a specific message so the client can retry with
        # backoff instead of parsing an opaque gateway error.
        import asyncio as _asyncio

        def _sync_fetch() -> list[dict]:
            ticker = yf.Ticker(symbol.upper())
            _rows = _fetch_yf_ohlcv(ticker, start_str, end_exclusive, interval, timeframe, adjustment)
            if not _rows:
                # CCXT fallback for crypto symbols (e.g. FET-USD → FET/USDT on Binance)
                _rows = _fetch_ccxt_ohlcv(symbol, timeframe, start_str)
            return _rows

        try:
            rows = await _asyncio.wait_for(_asyncio.to_thread(_sync_fetch), timeout=15.0)
            if not rows:
                raise HTTPException(status_code=404, detail=f"No data for {symbol}")

            bars_list = [{"t": r["_t"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]} for r in rows]
            main_ohlcv = [{"open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in rows]

            ttl = 3600 if timeframe in ("4Hour", "1Hour") else 300 if timeframe in ("30Min", "15Min", "5Min", "1Min") else 86400
            set_cache(cache_sym, timeframe, start_str, end_str, bars_list, ttl)
        except _asyncio.TimeoutError:
            raise HTTPException(
                status_code=503,
                detail=f"yfinance timeout for {symbol} after 15s; retry with backoff",
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"bars provider error for {symbol}: {e}")

    if not bars_list:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")

    # ── Indicator computation with warm-up ─────────────────────────────────────
    indicator_data: dict = {}
    if indicators and main_ohlcv:
        requested = [i.strip() for i in indicators.split(",")]

        # For daily+ timeframes with long-period indicators, prepend warm-up bars
        # so the full indicator series is valid for every visible bar. The
        # warm-up window is derived from the largest indicator period in the
        # request — frontend never has to pass an explicit buffer.
        warmup_ohlcv: list[dict] = []
        if start and timeframe in DAILY_TIMEFRAMES:
            lookback = _max_indicator_lookback(indicators)
            if lookback > 0:
                # Add a safety margin so holidays / weekends / data gaps can't
                # eat into the lookback window. +15 bars or +25%, whichever is
                # larger, comfortably covers a year of market closures.
                margin_bars = max(15, math.ceil(lookback * 0.25))
                days_per_bar = _DAYS_PER_BAR.get(timeframe, 1.5)
                extra_days = math.ceil((lookback + margin_bars) * days_per_bar)
                warmup_start = start_dt - timedelta(days=extra_days)
                warmup_key = f"__warmup_{symbol}_{timeframe}_{warmup_start.date().isoformat()}_{start_str}"
                warmup_cached = get_cached(cache_sym, f"{timeframe}_warmup", warmup_start.date().isoformat(), start_str)
                if warmup_cached:
                    warmup_ohlcv = warmup_cached
                else:
                    try:
                        wt = yf.Ticker(symbol.upper())
                        wrows = _fetch_yf_ohlcv(wt, warmup_start.date().isoformat(), start_str, interval, timeframe, adjustment)
                        warmup_ohlcv = [{"open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in wrows]
                        set_cache(cache_sym, f"{timeframe}_warmup", warmup_start.date().isoformat(), start_str, warmup_ohlcv, 86400)
                    except Exception as warmup_exc:
                        # Surface the failure — silently swallowing meant Donchian(55)
                        # and other long-period indicators rendered with a left-side
                        # gap and we had no signal that warm-up was broken.
                        logger.warning(
                            "[bars] warm-up fetch failed for %s %s lookback=%d window=%s..%s: %s",
                            symbol, timeframe, lookback, warmup_start.date().isoformat(), start_str, warmup_exc,
                        )
                        warmup_ohlcv = []  # fall back to no warm-up — indicators may start late

        full_ohlcv = warmup_ohlcv + main_ohlcv
        full_df = pd.DataFrame(full_ohlcv)
        n_warmup = len(warmup_ohlcv)

        try:
            all_indicators = compute_indicators(full_df, requested)
            # Strip the warm-up prefix so indicator arrays align 1:1 with returned bars
            indicator_data = {k: v[n_warmup:] for k, v in all_indicators.items()}
        except Exception:
            indicator_data = {}

    # Cache-Control: 5 min client / 10 min shared; ETag based on last bar timestamp
    last_t = bars_list[-1]["t"] if bars_list else ""
    etag = f'"{symbol}:{timeframe}:{last_t}"'
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=600"
    response.headers["ETag"] = etag

    return {"symbol": symbol.upper(), "bars": bars_list, "indicators": indicator_data}
