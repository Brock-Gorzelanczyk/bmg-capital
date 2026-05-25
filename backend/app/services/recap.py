from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import yfinance as yf
from sqlalchemy.orm import Session

from app.db.models.recap import DailyRecap
from app.db.models.strategy import DailyEquitySnapshot, DailyLog, StrategyTrade
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_MARKET_TICKERS = {
    "spy": "SPY",
    "qqq": "QQQ",
    "iwm": "IWM",
    "vix": "^VIX",
}


def _fetch_market_summary() -> dict:
    """Fetch day-change % for SPY, QQQ, IWM, VIX via yfinance. Graceful on missing data."""
    result: dict = {"spy": None, "qqq": None, "iwm": None, "vix": None, "breadth": "unknown"}

    for key, ticker in _MARKET_TICKERS.items():
        try:
            data = yf.Ticker(ticker).fast_info
            # fast_info exposes last_price and previous_close directly
            last = getattr(data, "last_price", None)
            prev = getattr(data, "previous_close", None)
            if last is not None and prev and prev != 0:
                result[key] = round((last - prev) / prev * 100, 2)
            else:
                # Fallback: download 2-day bar and compute
                hist = yf.download(ticker, period="2d", progress=False, auto_adjust=True)
                if hist is not None and len(hist) >= 2:
                    closes = hist["Close"].dropna()
                    if len(closes) >= 2:
                        result[key] = round(
                            (float(closes.iloc[-1]) - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100,
                            2,
                        )
        except Exception as exc:
            logger.warning(f"yfinance fetch failed for {ticker}: {exc}")
            result[key] = None

    # Determine breadth
    spy = result.get("spy")
    qqq = result.get("qqq")
    if spy is not None and qqq is not None:
        if spy > 0 and qqq > 0:
            result["breadth"] = "advancing"
        elif spy < 0 and qqq < 0:
            result["breadth"] = "declining"
        else:
            result["breadth"] = "mixed"

    return result


def _fetch_strategy_summary(db: Session, user_id: int, target_date: date) -> dict:
    """Build strategy summary from DailyEquitySnapshot or raw trade queries."""
    snapshot = (
        db.query(DailyEquitySnapshot)
        .filter(
            DailyEquitySnapshot.user_id == user_id,
            DailyEquitySnapshot.snapshot_date == target_date,
        )
        .first()
    )

    if snapshot:
        # day_pnl = today's equity minus yesterday's equity
        from app.screener.daily_runner import PAPER_PORTFOLIO
        prev_snap = (
            db.query(DailyEquitySnapshot)
            .filter(
                DailyEquitySnapshot.user_id == user_id,
                DailyEquitySnapshot.snapshot_date < target_date,
            )
            .order_by(DailyEquitySnapshot.snapshot_date.desc())
            .first()
        )
        prev_value = prev_snap.portfolio_value if prev_snap else PAPER_PORTFOLIO
        day_pnl = round(snapshot.portfolio_value - prev_value, 2)
        day_pnl_pct = round(day_pnl / prev_value * 100, 2) if prev_value else 0.0

        # Grab today's trades from DailyLog for narrative detail
        from app.db.models.strategy import DailyLog
        today_logs = (
            db.query(DailyLog)
            .filter(
                DailyLog.user_id == user_id,
                DailyLog.log_date == target_date,
                DailyLog.event_type.in_(["entry", "exit", "auto_entry", "auto_exit"]),
            )
            .all()
        )
        trade_symbols = [lg.symbol for lg in today_logs if lg.symbol]

        return {
            "new_entries": snapshot.new_entries,
            "exits": snapshot.exits_today,
            "open_positions": snapshot.open_positions,
            "portfolio_value": round(snapshot.portfolio_value, 2),
            "day_pnl": day_pnl,
            "day_pnl_pct": day_pnl_pct,
            "trade_symbols": trade_symbols,
        }

    # No snapshot yet — compute from raw trades
    open_count = (
        db.query(StrategyTrade)
        .filter(StrategyTrade.user_id == user_id, StrategyTrade.status == "open")
        .count()
    )
    new_entries = (
        db.query(StrategyTrade)
        .filter(
            StrategyTrade.user_id == user_id,
            StrategyTrade.status.in_(["open", "closed"]),
        )
        .all()
    )
    entries_today = sum(
        1
        for t in new_entries
        if t.entry_date and t.entry_date.date() == target_date
    )
    exits_today = sum(
        1
        for t in new_entries
        if t.exit_date and t.exit_date.date() == target_date
    )

    return {
        "new_entries": entries_today,
        "exits": exits_today,
        "open_positions": open_count,
        "portfolio_value": None,
        "day_pnl": None,
        "day_pnl_pct": None,
    }


def _fetch_top_setups(db: Session, user_id: int) -> list:
    """Return top 10 candidate trades ordered by candidate_since desc."""
    candidates = (
        db.query(StrategyTrade)
        .filter(
            StrategyTrade.user_id == user_id,
            StrategyTrade.status == "candidate",
        )
        .order_by(StrategyTrade.candidate_since.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "symbol": t.symbol,
            "preset": t.preset_key,
            "trigger": t.entry_trigger or "breakout",
        }
        for t in candidates
    ]


def _build_narrative(
    market: dict,
    strategy: dict,
    top_setups: list,
) -> str:
    """Build a rule-based natural language summary."""
    # Market direction sentence
    breadth = market.get("breadth", "unknown")
    spy_pct = market.get("spy")

    if breadth == "advancing":
        market_phrase = "Markets advanced today"
    elif breadth == "declining":
        market_phrase = "Markets declined today"
    elif breadth == "mixed":
        market_phrase = "Markets were mixed today"
    else:
        market_phrase = "Market data was unavailable today"

    if spy_pct is not None:
        direction = "up" if spy_pct >= 0 else "down"
        spy_phrase = f" with the S&P 500 {direction} {abs(spy_pct):.1f}%"
    else:
        spy_phrase = ""

    market_sentence = f"{market_phrase}{spy_phrase}."

    # Strategy performance sentence
    new_entries = strategy.get("new_entries") or 0
    exits = strategy.get("exits") or 0
    open_pos = strategy.get("open_positions") or 0
    trade_symbols = strategy.get("trade_symbols") or []

    if new_entries == 0 and exits == 0:
        strategy_sentence = f"The strategy agent held steady — no new entries or exits. {open_pos} position{'s' if open_pos != 1 else ''} currently open."
    else:
        parts_s = []
        if new_entries:
            sym_str = f" ({', '.join(trade_symbols[:3])}{'…' if len(trade_symbols) > 3 else ''})" if trade_symbols else ""
            parts_s.append(f"opened {new_entries} new position{'s' if new_entries != 1 else ''}{sym_str}")
        if exits:
            parts_s.append(f"closed {exits} trade{'s' if exits != 1 else ''}")
        strategy_sentence = f"The strategy agent {' and '.join(parts_s)}. {open_pos} position{'s' if open_pos != 1 else ''} now open."

    # P&L sentence
    pnl_sentence = ""
    day_pnl = strategy.get("day_pnl")
    day_pnl_pct = strategy.get("day_pnl_pct")
    portfolio_value = strategy.get("portfolio_value")
    if day_pnl is not None:
        direction = "gained" if day_pnl >= 0 else "lost"
        pnl_str = f"${abs(day_pnl):,.2f}"
        pv_str = f" (portfolio at ${portfolio_value:,.2f})" if portfolio_value else ""
        if day_pnl_pct is not None:
            pnl_sentence = f"Paper portfolio {direction} {pnl_str} ({abs(day_pnl_pct):.2f}%){pv_str}."
        else:
            pnl_sentence = f"Paper portfolio {direction} {pnl_str}{pv_str}."

    # Candidates / watchlist sentence
    candidates_count = len(top_setups)
    candidates_sentence = (
        f"Watching {candidates_count} setup{'s' if candidates_count != 1 else ''} across 19 strategies."
        if candidates_count > 0
        else "No new setups are being monitored."
    )

    # Top setup
    top_setup_sentence = ""
    if top_setups:
        top = top_setups[0]
        top_setup_sentence = f"Highest-priority setup: {top['symbol']} on the {top['preset']} strategy."

    parts = [market_sentence, strategy_sentence]
    if pnl_sentence:
        parts.append(pnl_sentence)
    parts.append(candidates_sentence)
    if top_setup_sentence:
        parts.append(top_setup_sentence)

    return " ".join(parts)


async def generate_daily_recap(user_id: int, target_date: Optional[date] = None) -> DailyRecap:
    """
    Generate (or regenerate) the DailyRecap for user_id on target_date.
    Upserts on (user_id, recap_date). Returns the saved DailyRecap record.
    """
    if target_date is None:
        target_date = date.today()

    recap_date_str = target_date.isoformat()

    import asyncio

    loop = asyncio.get_running_loop()

    # Run yfinance fetch in executor so it doesn't block the event loop
    market_summary = await loop.run_in_executor(None, _fetch_market_summary)

    db: Session = SessionLocal()
    try:
        strategy_summary = _fetch_strategy_summary(db, user_id, target_date)
        top_setups = _fetch_top_setups(db, user_id)
        narrative = _build_narrative(market_summary, strategy_summary, top_setups)

        # Upsert
        existing = (
            db.query(DailyRecap)
            .filter(
                DailyRecap.user_id == user_id,
                DailyRecap.recap_date == recap_date_str,
            )
            .first()
        )

        if existing:
            existing.market_summary = market_summary
            existing.strategy_summary = strategy_summary
            existing.top_setups = top_setups
            existing.narrative = narrative
            db.commit()
            db.refresh(existing)
            return existing
        else:
            recap = DailyRecap(
                user_id=user_id,
                recap_date=recap_date_str,
                market_summary=market_summary,
                strategy_summary=strategy_summary,
                top_setups=top_setups,
                narrative=narrative,
                created_at=datetime.utcnow(),
            )
            db.add(recap)
            db.commit()
            db.refresh(recap)
            return recap
    finally:
        db.close()
