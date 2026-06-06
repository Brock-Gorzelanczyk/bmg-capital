"""
On-chain data ingestion — fetches from Glassnode, Coinglass, LunarCrush
and upserts into onchain_metrics table. Runs on APScheduler.

Gracefully no-ops if API keys are not configured.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_SYMBOLS_GLASSNODE = ["BTC", "ETH"]
_SYMBOLS_COINGLASS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "ADA", "BNB", "MATIC", "ATOM",
                      "DOGE", "LTC", "XRP", "UNI", "AAVE", "SNX", "MKR", "CRV", "COMP", "YFI"]
_SYMBOLS_LUNARCRUSH = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "ADA", "BNB", "MATIC",
                       "DOGE", "XRP", "ATOM", "LTC", "UNI", "AAVE"]


def _upsert_metric(db, symbol: str, metric: str, source: str, value: float,
                   ts: datetime, raw: Optional[dict] = None) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from app.db.models.onchain import OnChainMetric

    existing = db.query(OnChainMetric).filter_by(
        symbol=symbol, metric=metric, source=source, ts=ts
    ).first()
    if existing:
        existing.value = value
        existing.raw_payload = raw
    else:
        db.add(OnChainMetric(
            symbol=symbol, metric=metric, source=source,
            value=value, ts=ts, raw_payload=raw,
        ))


# ── Glassnode ─────────────────────────────────────────────────────────────────

_GLASSNODE_METRICS = {
    "mvrv_z": "market/mvrv_z_score",
    "nupl":   "indicators/nupl",
    "sopr_sth": "indicators/sopr_adjusted",
    "exchange_net_flow": "transactions/transfers_volume_exchanges_net",
    "active_addresses": "addresses/active_count",
}


def _fetch_glassnode(metric_path: str, symbol: str, api_key: str) -> Optional[tuple[float, datetime]]:
    try:
        url = f"https://api.glassnode.com/v1/metrics/{metric_path}"
        resp = httpx.get(url, params={"a": symbol, "api_key": api_key, "i": "24h"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data:
            last = data[-1]
            ts = datetime.fromtimestamp(last["t"], tz=timezone.utc)
            val = float(last.get("v") or 0)
            return val, ts
    except Exception as exc:
        logger.debug("Glassnode %s/%s failed: %s", metric_path, symbol, exc)
    return None


def ingest_glassnode(db) -> int:
    from app.config import settings
    api_key = settings.glassnode_api_key
    if not api_key:
        return 0

    count = 0
    for symbol in _SYMBOLS_GLASSNODE:
        for metric_name, path in _GLASSNODE_METRICS.items():
            result = _fetch_glassnode(path, symbol, api_key)
            if result:
                val, ts = result
                _upsert_metric(db, symbol, metric_name, "glassnode", val, ts)
                count += 1
    db.commit()
    logger.info("Glassnode ingest: %d metrics upserted", count)
    return count


# ── Coinglass ─────────────────────────────────────────────────────────────────

def ingest_coinglass(db) -> int:
    from app.config import settings
    api_key = settings.coinglass_api_key
    if not api_key:
        return 0

    count = 0
    now = datetime.now(timezone.utc)

    # Funding rates
    try:
        resp = httpx.get(
            "https://open-api.coinglass.com/public/v2/funding",
            headers={"coinglassSecret": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        for item in data:
            sym = item.get("symbol", "")
            if sym in _SYMBOLS_COINGLASS:
                rate = float(item.get("fundingRate", 0) or 0)
                _upsert_metric(db, sym, "funding_rate", "coinglass", rate, now, {"raw": item})
                count += 1
    except Exception as exc:
        logger.debug("Coinglass funding rates failed: %s", exc)

    # Open interest
    try:
        resp = httpx.get(
            "https://open-api.coinglass.com/public/v2/open_interest",
            headers={"coinglassSecret": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        for item in data:
            sym = item.get("symbol", "")
            if sym in _SYMBOLS_COINGLASS:
                oi = float(item.get("openInterestUsd", 0) or 0)
                _upsert_metric(db, sym, "open_interest_usd", "coinglass", oi, now)
                count += 1
    except Exception as exc:
        logger.debug("Coinglass OI failed: %s", exc)

    # Long/short ratio
    try:
        resp = httpx.get(
            "https://open-api.coinglass.com/public/v2/long_short",
            headers={"coinglassSecret": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        for item in data:
            sym = item.get("symbol", "")
            if sym in _SYMBOLS_COINGLASS:
                ls = float(item.get("longShortRatio", 1) or 1)
                _upsert_metric(db, sym, "long_short_ratio", "coinglass", ls, now)
                count += 1
    except Exception as exc:
        logger.debug("Coinglass L/S ratio failed: %s", exc)

    db.commit()
    logger.info("Coinglass ingest: %d metrics upserted", count)
    return count


# ── LunarCrush ────────────────────────────────────────────────────────────────

def ingest_lunarcrush(db) -> int:
    from app.config import settings
    api_key = settings.lunarcrush_api_key
    if not api_key:
        return 0

    count = 0
    now = datetime.now(timezone.utc)

    try:
        resp = httpx.get(
            "https://lunarcrush.com/api4/public/coins/list/v2",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
        for item in items:
            sym = item.get("symbol", "").upper()
            if sym in _SYMBOLS_LUNARCRUSH:
                galaxy = float(item.get("galaxy_score") or 0)
                alt_rank = float(item.get("alt_rank") or 0)
                social_vol = float(item.get("social_volume_24h") or 0)
                _upsert_metric(db, sym, "galaxy_score",     "lunarcrush", galaxy,     now)
                _upsert_metric(db, sym, "alt_rank",         "lunarcrush", alt_rank,   now)
                _upsert_metric(db, sym, "social_volume_24h","lunarcrush", social_vol, now)
                count += 3
    except Exception as exc:
        logger.debug("LunarCrush ingest failed: %s", exc)

    db.commit()
    logger.info("LunarCrush ingest: %d metrics upserted", count)
    return count


# ── Scheduler registration ────────────────────────────────────────────────────

def setup_onchain_scheduler(scheduler) -> None:
    from app.db.session import SessionLocal

    def _run_glassnode():
        db = SessionLocal()
        try:
            ingest_glassnode(db)
        finally:
            db.close()

    def _run_coinglass():
        db = SessionLocal()
        try:
            ingest_coinglass(db)
        finally:
            db.close()

    def _run_lunarcrush():
        db = SessionLocal()
        try:
            ingest_lunarcrush(db)
        finally:
            db.close()

    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(_run_glassnode,   CronTrigger(hour="*/6", minute=15), id="onchain_glassnode",   replace_existing=True)
    scheduler.add_job(_run_coinglass,   CronTrigger(minute=30),             id="onchain_coinglass",   replace_existing=True)
    scheduler.add_job(_run_lunarcrush,  CronTrigger(minute=45),             id="onchain_lunarcrush",  replace_existing=True)
    logger.info("on-chain ingest schedulers registered (glassnode/6h, coinglass/1h, lunarcrush/1h)")


def get_latest_metric(db, symbol: str, metric: str, source: str) -> Optional[float]:
    """Convenience: get most recent value for a symbol+metric."""
    from app.db.models.onchain import OnChainMetric
    row = (
        db.query(OnChainMetric)
        .filter_by(symbol=symbol, metric=metric, source=source)
        .order_by(OnChainMetric.ts.desc())
        .first()
    )
    return row.value if row else None
