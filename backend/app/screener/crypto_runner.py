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
    CRYPTO_PRESET_LABELS,
    CRYPTO_PRESET_SCREENS,
    CRYPTO_UNIVERSE,
)
from app.screener.crypto_triggers import (
    CRYPTO_CANDIDATE_MAX_DAYS,
    CRYPTO_CONVICTION,
    CRYPTO_R_MULTIPLE,
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

def _fetch_crypto_bars(symbols: List[str], timeframe: str = "1d", limit: int = 250) -> Dict[str, pd.DataFrame]:
    """
    Fetch daily OHLCV bars for each symbol from Binance via CCXT.
    Returns {symbol: DataFrame(open, high, low, close, volume)}.
    Falls back to yfinance on failure.
    """
    bars: Dict[str, pd.DataFrame] = {}
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        for sym in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
                if not ohlcv:
                    continue
                df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
                df["ts"] = pd.to_datetime(df["ts"], unit="ms")
                df.set_index("ts", inplace=True)
                bars[sym] = df
            except Exception as e:
                logger.debug(f"CCXT fetch failed for {sym}: {e}")
    except Exception as e:
        logger.warning(f"CCXT not available or exchange init failed: {e}")

    # yfinance fallback for any symbol not yet fetched
    missing = [s for s in symbols if s not in bars]
    if missing:
        import yfinance as yf
        for sym in missing:
            yf_sym = sym.replace("/", "-").replace("USDT", "USD")
            try:
                df = yf.download(yf_sym, period="1y", interval="1d", progress=False, auto_adjust=True)
                if df.empty:
                    continue
                df.columns = [c.lower() for c in df.columns]
                bars[sym] = df
            except Exception as e:
                logger.debug(f"yfinance fallback failed for {sym}: {e}")

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

def _apply_crypto_filters(df: pd.DataFrame, filter_specs: list[dict]) -> bool:
    """Return True if all filter specs match the given OHLCV DataFrame."""
    for spec in filter_specs:
        ftype = spec.get("type")
        op    = spec.get("operator", "gt")
        val   = spec.get("value", 0)

        try:
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
                vol_avg = float(df["volume"].iloc[-21:-1].mean())
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

        except Exception as e:
            logger.debug(f"Filter error ({ftype}): {e}")
            return False

    return True


def _collect_crypto_screen_results(
    regime: str, bars: Dict[str, pd.DataFrame]
) -> Dict[str, Set[str]]:
    results: Dict[str, Set[str]] = {}
    for preset_key, filter_specs in CRYPTO_PRESET_SCREENS.items():
        hits: Set[str] = set()
        for sym, df in bars.items():
            try:
                if _apply_crypto_filters(df, filter_specs):
                    hits.add(sym)
            except Exception as e:
                logger.debug(f"Screen error {preset_key}/{sym}: {e}")
        results[preset_key] = hits
        logger.debug(f"Crypto screen {preset_key}: {len(hits)} hits")
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
        stop = price - atr * 1.5
        target = price + atr * 1.5 * CRYPTO_R_MULTIPLE
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

async def run_crypto_automation(user_id: int) -> Dict[str, Any]:
    logger.info(f"[crypto] Starting automation for user {user_id}")
    loop = asyncio.get_running_loop()
    today = date.today()

    # Fetch bars for all coins in universe
    bars = await loop.run_in_executor(None, lambda: _fetch_crypto_bars(CRYPTO_UNIVERSE))
    if not bars:
        logger.warning("[crypto] No bars fetched — skipping run")
        return {"entries": 0, "new_candidates": 0, "exits": 0}

    prices = _get_crypto_prices(list(bars.keys()), bars)
    regime = _check_crypto_regime(bars)
    logger.info(f"[crypto] Regime: {regime}, coins with bars: {len(bars)}")

    screen_results = _collect_crypto_screen_results(regime, bars)

    db = SessionLocal()
    try:
        new_cands = _add_crypto_candidates(db, screen_results, today, user_id)
        db.commit()

        expired = _expire_stale_candidates(db, today, user_id)
        if expired:
            db.commit()

        entries = _check_entry_triggers(db, bars, prices, today, user_id)
        if entries:
            db.commit()

        exits = _settle_crypto_positions(db, bars, prices, today, user_id)
        if exits:
            db.commit()

        _snapshot_crypto_equity(db, prices, user_id)
        db.commit()

        logger.info(f"[crypto] Done: {new_cands} new candidates, {entries} entries, {exits} exits")
        return {
            "regime": regime,
            "coins_scanned": len(bars),
            "new_candidates": new_cands,
            "entries": entries,
            "exits": exits,
            "expired": expired,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"[crypto] Automation error for user {user_id}: {e}", exc_info=True)
        raise
    finally:
        db.close()
