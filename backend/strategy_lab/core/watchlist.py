"""
Watchlist engine — builds and scores per-bot symbol universes.
Scores are composite: momentum + volume (+ BTC-relative for crypto).
Results are upserted to the BotWatchlist table.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Universe definitions (can be overridden per profile via config_json) ──────

_DEFAULT_UNIVERSES: dict[str, list[str]] = {
    "stock": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM",
        "V", "UNH", "XOM", "LLY", "AVGO", "HD", "PG", "MA", "COST",
        "MRK", "ABBV", "CVX", "AMD", "NFLX", "PEP", "BAC", "KO",
        "TMO", "WMT", "DIS", "INTC", "CRM", "QCOM", "ADBE", "ORCL",
        "TXN", "ACN", "NEE", "MDT", "HON", "INTU", "AMGN",
    ],
    "crypto": [
        "BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "MATICUSD",
        "DOTUSD", "LINKUSD", "UNIUSD", "AAVEUSD", "NEARUSD",
    ],
}

_STALE_HOURS = 48


def _fetch_bars(symbol: str, limit: int = 30, asset_class: str = "stock") -> list[dict]:
    """Fetch recent daily bars for a symbol via Alpaca."""
    api_key = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_SECRET_KEY", "")
    base_url = os.getenv("ALPACA_BASE_URL", "https://data.alpaca.markets")

    if not api_key:
        return []

    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    if asset_class == "crypto":
        # Alpaca crypto endpoint
        url = f"{base_url}/v1beta3/crypto/us/bars"
        params = {"symbols": symbol, "timeframe": "1Day", "limit": limit}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []
            bars_map = resp.json().get("bars", {})
            return bars_map.get(symbol, [])
        except Exception as exc:
            logger.debug("Crypto bars fetch failed for %s: %s", symbol, exc)
            return []
    else:
        url = f"{base_url}/v2/stocks/{symbol}/bars"
        params = {"timeframe": "1Day", "limit": limit, "adjustment": "raw", "feed": "iex"}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []
            return resp.json().get("bars", [])
        except Exception as exc:
            logger.debug("Stock bars fetch failed for %s: %s", symbol, exc)
            return []


def _momentum_score(closes: list[float], period: int = 20) -> float:
    """20-day price return normalized to 0-1 (capped at ±30%)."""
    if len(closes) < period + 1:
        return 0.5
    ret = (closes[-1] - closes[-period]) / closes[-period]
    # Cap at ±30% and normalize to 0-1
    capped = max(-0.30, min(0.30, ret))
    return round((capped + 0.30) / 0.60, 4)


def _volume_score(volumes: list[float], recent_n: int = 5) -> float:
    """Recent volume vs 30d average, normalized to 0-1 (capped at 3x)."""
    if len(volumes) < recent_n + 1:
        return 0.5
    avg_vol = sum(volumes[:-recent_n]) / len(volumes[:-recent_n])
    if avg_vol == 0:
        return 0.5
    recent_avg = sum(volumes[-recent_n:]) / recent_n
    ratio = recent_avg / avg_vol
    capped = min(3.0, ratio)
    return round(capped / 3.0, 4)


def _btc_relative_strength(closes: list[float], btc_closes: list[float], period: int = 20) -> float:
    """Crypto symbol return relative to BTC over `period` days, normalized 0-1."""
    if len(closes) < period + 1 or len(btc_closes) < period + 1:
        return 0.5
    sym_ret = (closes[-1] - closes[-period]) / closes[-period]
    btc_ret = (btc_closes[-1] - btc_closes[-period]) / btc_closes[-period]
    rel = sym_ret - btc_ret
    capped = max(-0.30, min(0.30, rel))
    return round((capped + 0.30) / 0.60, 4)


def score_symbol(
    symbol: str,
    asset_class: str,
    profile_config: dict,
    btc_closes: Optional[list[float]] = None,
) -> tuple[float, dict]:
    """
    Compute composite score for a symbol. Returns (score, reasons_dict).
    Weights: configurable from profile_config.watchlist_weights or defaults.
    """
    weights = profile_config.get("watchlist_weights", {})
    w_momentum = weights.get("momentum", 0.5)
    w_volume = weights.get("volume", 0.3)
    w_btc_rel = weights.get("btc_relative", 0.2)

    bars = _fetch_bars(symbol, limit=35, asset_class=asset_class)
    if not bars:
        return 0.0, {"error": "no_data"}

    closes = [b["c"] for b in bars]
    volumes = [b.get("v", 0.0) for b in bars]

    mom = _momentum_score(closes)
    vol = _volume_score(volumes)
    reasons: dict = {"momentum": mom, "volume": vol}

    if asset_class == "crypto" and btc_closes:
        btc_rel = _btc_relative_strength(closes, btc_closes)
        reasons["btc_relative"] = btc_rel
        total = mom * w_momentum + vol * w_volume + btc_rel * w_btc_rel
    else:
        # Redistribute BTC weight to momentum for stocks
        total = mom * (w_momentum + w_btc_rel * 0.5) + vol * (w_volume + w_btc_rel * 0.5)

    return round(total, 4), reasons


# ── WatchlistEngine ───────────────────────────────────────────────────────────

class WatchlistEngine:
    """Manages per-bot-profile symbol watchlists with scoring and persistence."""

    def rebuild(self, profile_name: str, db: Session) -> list[dict]:
        """
        Fetch universe, score each symbol, upsert to BotWatchlist.
        Returns the new watchlist as list of dicts, sorted by score desc.
        """
        from app.db.models.bots import BotProfile, BotWatchlist

        profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
        if not profile:
            logger.warning("WatchlistEngine.rebuild: profile %s not found", profile_name)
            return []

        config = profile.config_json or {}
        asset_class = profile.asset_class
        universe: list[str] = config.get("universe", _DEFAULT_UNIVERSES.get(asset_class, []))

        # Fetch BTC bars once for crypto relative-strength
        btc_closes: Optional[list[float]] = None
        if asset_class == "crypto":
            btc_bars = _fetch_bars("BTCUSD", limit=35, asset_class="crypto")
            if btc_bars:
                btc_closes = [b["c"] for b in btc_bars]

        now = datetime.now(timezone.utc)
        scored: list[tuple[float, str, dict]] = []

        for sym in universe:
            try:
                score, reasons = score_symbol(sym, asset_class, config, btc_closes)
                scored.append((score, sym, reasons))
            except Exception as exc:
                logger.warning("Score failed for %s: %s", sym, exc)

        # Sort by score desc and assign rank
        scored.sort(key=lambda x: x[0], reverse=True)

        result: list[dict] = []
        for rank, (score, sym, reasons) in enumerate(scored, start=1):
            # Upsert
            existing = (
                db.query(BotWatchlist)
                .filter(
                    BotWatchlist.profile_id == profile.id,
                    BotWatchlist.symbol == sym,
                )
                .first()
            )
            if existing:
                existing.score = score
                existing.rank = rank
                existing.reasons = reasons
                existing.status = "active"
                existing.last_evaluated_at = now
            else:
                existing = BotWatchlist(
                    profile_id=profile.id,
                    symbol=sym,
                    score=score,
                    rank=rank,
                    reasons=reasons,
                    status="active",
                    added_at=now,
                    last_evaluated_at=now,
                )
                db.add(existing)

            result.append({
                "symbol": sym,
                "score": score,
                "rank": rank,
                "reasons": reasons,
                "status": "active",
            })

        # Mark stale symbols inactive (evaluated > 48h ago and not in current universe)
        universe_set = set(universe)
        stale_cutoff = now - timedelta(hours=_STALE_HOURS)
        stale = (
            db.query(BotWatchlist)
            .filter(
                BotWatchlist.profile_id == profile.id,
                BotWatchlist.status == "active",
            )
            .all()
        )
        for row in stale:
            if row.symbol not in universe_set:
                if row.last_evaluated_at and row.last_evaluated_at < stale_cutoff:
                    row.status = "inactive"

        db.commit()
        logger.info(
            "WatchlistEngine.rebuild: %s — %d symbols scored for %s",
            profile_name,
            len(result),
            asset_class,
        )
        return result

    def get_watchlist(
        self, profile_id: int, db: Session, limit: int = 100
    ) -> list[dict]:
        """Return active watchlist entries sorted by score desc."""
        from app.db.models.bots import BotWatchlist

        rows = (
            db.query(BotWatchlist)
            .filter(
                BotWatchlist.profile_id == profile_id,
                BotWatchlist.status == "active",
            )
            .order_by(BotWatchlist.score.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "score": r.score,
                "rank": r.rank,
                "reasons": r.reasons,
                "status": r.status,
                "added_at": r.added_at.isoformat() if r.added_at else None,
                "last_evaluated_at": (
                    r.last_evaluated_at.isoformat() if r.last_evaluated_at else None
                ),
            }
            for r in rows
        ]
