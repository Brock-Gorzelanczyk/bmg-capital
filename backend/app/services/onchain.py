from __future__ import annotations

"""
Free on-chain data proxies.

Sources (all free, no API key):
  - CoinMetrics Community API: MVRV, NUPL, realized price, SOPR proxy
  - CoinGecko /coins/markets?category=stablecoins: stablecoin SSR
  - Binance Futures /futures/data/openInterestHist: exchange netflow proxy via OI trend

1-hour TTL with threading.Lock. Falls back to stale data on error.
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_CACHE_TTL = 3600  # 1 hour

_lock = threading.Lock()

_btc_metrics_cache: Optional[dict] = None
_btc_metrics_ts: float = 0.0

_ssr_cache: Optional[dict] = None
_ssr_ts: float = 0.0

_netflow_cache: Optional[dict] = None
_netflow_ts: float = 0.0


def _stale(ts: float) -> bool:
    return time.time() - ts > _CACHE_TTL


def get_btc_onchain_metrics() -> dict:
    """
    Fetch BTC on-chain metrics from CoinMetrics Community API (free tier).

    Returns dict with keys:
      mvrv          float  — current MVRV ratio
      mvrv_zscore   float  — Z-score over up-to-365 day window
      nupl          float  — (mcap - realized_cap) / mcap
      realized_price float — realized cap / coin supply proxy
      sopr_proxy    float  — current_price / realized_price
      price         float  — latest BTC price (USD)
      ok            bool   — False if fetch failed and no stale data
    """
    global _btc_metrics_cache, _btc_metrics_ts
    with _lock:
        if _btc_metrics_cache is not None and not _stale(_btc_metrics_ts):
            return _btc_metrics_cache
        try:
            url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
            params = {
                "assets": "btc",
                "metrics": "CapMVRVCur,CapRealUSD,CapMktCurUSD,PriceUSD",
                "frequency": "1d",
                "page_size": 400,
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            rows = [
                r for r in resp.json().get("data", [])
                if r.get("CapMVRVCur") and r.get("CapRealUSD") and r.get("CapMktCurUSD")
            ]
            if len(rows) < 30:
                raise ValueError(f"Insufficient CoinMetrics data: {len(rows)} rows")

            latest   = rows[-1]
            mvrv     = float(latest["CapMVRVCur"])
            mcap     = float(latest["CapMktCurUSD"])
            real_cap = float(latest["CapRealUSD"])
            price    = float(latest.get("PriceUSD") or 0)

            nupl = (mcap - real_cap) / mcap if mcap > 0 else 0.0
            # realized price proxy: real_cap * price / mcap  (≈ price paid per coin on-chain)
            realized_price = (real_cap * price / mcap) if (mcap > 0 and price > 0) else 0.0
            sopr_proxy = price / realized_price if realized_price > 0 else 1.0

            import statistics
            mvrv_series = []
            for r in rows[-365:]:
                try:
                    mvrv_series.append(float(r["CapMVRVCur"]))
                except (ValueError, TypeError):
                    pass
            if len(mvrv_series) >= 30:
                mean = statistics.mean(mvrv_series)
                std  = statistics.stdev(mvrv_series)
                mvrv_zscore = (mvrv - mean) / std if std > 0 else 0.0
            else:
                mvrv_zscore = 0.0

            result = {
                "mvrv": mvrv,
                "mvrv_zscore": mvrv_zscore,
                "nupl": nupl,
                "realized_price": realized_price,
                "sopr_proxy": sopr_proxy,
                "price": price,
                "ok": True,
            }
            _btc_metrics_cache = result
            _btc_metrics_ts = time.time()
            logger.debug(f"CoinMetrics: mvrv={mvrv:.2f} zscore={mvrv_zscore:.2f} nupl={nupl:.2f} sopr={sopr_proxy:.3f}")
            return result
        except Exception as e:
            logger.warning(f"CoinMetrics fetch failed: {e}")
            if _btc_metrics_cache is not None:
                return _btc_metrics_cache
            return {
                "mvrv": 0.0, "mvrv_zscore": 0.0, "nupl": 0.0,
                "realized_price": 0.0, "sopr_proxy": 1.0, "price": 0.0,
                "ok": False,
            }


def get_stablecoin_supply_ratio() -> dict:
    """
    Compute SSR = BTC market cap / total stablecoin market cap.
    Uses CoinGecko free tier.

    Returns dict with keys:
      ssr        float  — BTC mcap / stablecoin mcap
      btc_mcap   float  — BTC market cap (USD)
      stable_mcap float — total stablecoin market cap (USD)
      signal     str    — "low" | "neutral" | "high"
      ok         bool
    """
    global _ssr_cache, _ssr_ts
    with _lock:
        if _ssr_cache is not None and not _stale(_ssr_ts):
            return _ssr_cache
        try:
            base = "https://api.coingecko.com/api/v3/coins/markets"

            btc_resp = requests.get(
                base,
                params={"vs_currency": "usd", "ids": "bitcoin"},
                timeout=10,
            )
            btc_resp.raise_for_status()
            btc_data = btc_resp.json()
            btc_mcap = float(btc_data[0]["market_cap"]) if btc_data else 0.0

            stable_resp = requests.get(
                base,
                params={
                    "vs_currency": "usd",
                    "category": "stablecoins",
                    "order": "market_cap_desc",
                    "per_page": 50,
                    "page": 1,
                },
                timeout=10,
            )
            stable_resp.raise_for_status()
            stable_mcap = sum(
                float(c.get("market_cap") or 0) for c in stable_resp.json()
            )

            ssr = btc_mcap / stable_mcap if stable_mcap > 0 else 0.0
            # SSR < 5: large dry-powder pool relative to BTC = bullish pressure building
            # SSR > 15: BTC dominates, little stablecoin buying power remaining
            signal = "low" if ssr < 5 else ("high" if ssr > 15 else "neutral")

            result = {
                "ssr": ssr,
                "btc_mcap": btc_mcap,
                "stable_mcap": stable_mcap,
                "signal": signal,
                "ok": True,
            }
            _ssr_cache = result
            _ssr_ts = time.time()
            logger.debug(f"SSR: {ssr:.2f} ({signal})")
            return result
        except Exception as e:
            logger.warning(f"SSR fetch failed: {e}")
            if _ssr_cache is not None:
                return _ssr_cache
            return {"ssr": 0.0, "signal": "neutral", "btc_mcap": 0.0, "stable_mcap": 0.0, "ok": False}


def get_exchange_netflow_proxy() -> dict:
    """
    Use Binance perpetual open interest history as an exchange netflow proxy.
    Declining OI + stable/rising price = long unwinding / spot accumulation.
    Rising OI + rising price = new longs entering (healthy bull).
    Declining OI + falling price = capitulation / short-covering bottom.

    Returns dict with keys:
      oi_change_7d_pct  float  — % change in OI over 7 days
      signal            str    — "outflow" | "neutral" | "inflow"
      recent_oi         float  — latest open interest (USD)
      ok                bool
    """
    global _netflow_cache, _netflow_ts
    with _lock:
        if _netflow_cache is not None and not _stale(_netflow_ts):
            return _netflow_cache
        try:
            resp = requests.get(
                "https://fapi.binance.com/futures/data/openInterestHist",
                params={"symbol": "BTCUSDT", "period": "1d", "limit": 30},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or len(data) < 8:
                raise ValueError(f"Insufficient OI data: {len(data) if isinstance(data, list) else 0} rows")

            recent_oi  = float(data[-1]["sumOpenInterestValue"])
            week_ago   = float(data[-8]["sumOpenInterestValue"])
            oi_change  = (recent_oi - week_ago) / week_ago * 100 if week_ago > 0 else 0.0

            # Declining OI = longs/shorts exiting = supply to exchanges drying up
            signal = "outflow" if oi_change < -5 else ("inflow" if oi_change > 5 else "neutral")

            result = {
                "oi_change_7d_pct": oi_change,
                "signal": signal,
                "recent_oi": recent_oi,
                "ok": True,
            }
            _netflow_cache = result
            _netflow_ts = time.time()
            logger.debug(f"OI netflow proxy: {oi_change:+.1f}% 7d ({signal})")
            return result
        except Exception as e:
            logger.warning(f"Binance OI netflow fetch failed: {e}")
            if _netflow_cache is not None:
                return _netflow_cache
            return {"oi_change_7d_pct": 0.0, "signal": "neutral", "recent_oi": 0.0, "ok": False}


def prefetch_all() -> None:
    """Pre-warm all three caches in a single executor call before the screen loop."""
    for fn in (get_btc_onchain_metrics, get_stablecoin_supply_ratio, get_exchange_netflow_proxy):
        try:
            fn()
        except Exception:
            pass
