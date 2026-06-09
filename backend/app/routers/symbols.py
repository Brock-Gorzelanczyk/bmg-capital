"""Symbol search, metadata, and bot trade/signal endpoints for TradingView datafeed."""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["symbols"])


# ── Static symbol index (built once at import time) ──────────────────────────

# Top 200 Russell 1000 stocks (representative subset for search)
_STOCK_INDEX = [
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "GOOGL", "name": "Alphabet Inc. Class A", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "GOOG", "name": "Alphabet Inc. Class C", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "META", "name": "Meta Platforms Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "TSLA", "name": "Tesla Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "BRK.B", "name": "Berkshire Hathaway Inc. Class B", "exchange": "NYSE", "type": "stock"},
    {"symbol": "LLY", "name": "Eli Lilly and Company", "exchange": "NYSE", "type": "stock"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "V", "name": "Visa Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "MA", "name": "Mastercard Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "XOM", "name": "Exxon Mobil Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "exchange": "NYSE", "type": "stock"},
    {"symbol": "PG", "name": "Procter & Gamble Co.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "HD", "name": "Home Depot Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "MRK", "name": "Merck & Co. Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "ABBV", "name": "AbbVie Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "CVX", "name": "Chevron Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "COST", "name": "Costco Wholesale Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "PEP", "name": "PepsiCo Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "AMD", "name": "Advanced Micro Devices Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "ORCL", "name": "Oracle Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "NFLX", "name": "Netflix Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "KO", "name": "The Coca-Cola Company", "exchange": "NYSE", "type": "stock"},
    {"symbol": "WMT", "name": "Walmart Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "CRM", "name": "Salesforce Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "BAC", "name": "Bank of America Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "TMO", "name": "Thermo Fisher Scientific Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "MCD", "name": "McDonald's Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "ACN", "name": "Accenture plc Class A", "exchange": "NYSE", "type": "stock"},
    {"symbol": "IBM", "name": "IBM Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "LIN", "name": "Linde plc", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "TXN", "name": "Texas Instruments Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "INTU", "name": "Intuit Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "AMGN", "name": "Amgen Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "PM", "name": "Philip Morris International Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "GE", "name": "GE Aerospace", "exchange": "NYSE", "type": "stock"},
    {"symbol": "RTX", "name": "RTX Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "QCOM", "name": "Qualcomm Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "ISRG", "name": "Intuitive Surgical Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "CAT", "name": "Caterpillar Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "SPGI", "name": "S&P Global Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "NOW", "name": "ServiceNow Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "BKNG", "name": "Booking Holdings Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "PFE", "name": "Pfizer Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "UNP", "name": "Union Pacific Corporation", "exchange": "NYSE", "type": "stock"},
    {"symbol": "AXP", "name": "American Express Company", "exchange": "NYSE", "type": "stock"},
    {"symbol": "T", "name": "AT&T Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "NEE", "name": "NextEra Energy Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "HON", "name": "Honeywell International Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "LOW", "name": "Lowe's Companies Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "MS", "name": "Morgan Stanley", "exchange": "NYSE", "type": "stock"},
    {"symbol": "GS", "name": "Goldman Sachs Group Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "DE", "name": "Deere & Company", "exchange": "NYSE", "type": "stock"},
    {"symbol": "AMAT", "name": "Applied Materials Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "SBUX", "name": "Starbucks Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "MDLZ", "name": "Mondelez International Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "CI", "name": "Cigna Group", "exchange": "NYSE", "type": "stock"},
    {"symbol": "ADI", "name": "Analog Devices Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "PANW", "name": "Palo Alto Networks Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "KLAC", "name": "KLA Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "LRCX", "name": "Lam Research Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "SNPS", "name": "Synopsys Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "CDNS", "name": "Cadence Design Systems Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "CME", "name": "CME Group Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "BLK", "name": "BlackRock Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "INTC", "name": "Intel Corporation", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "C", "name": "Citigroup Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "WFC", "name": "Wells Fargo & Company", "exchange": "NYSE", "type": "stock"},
    {"symbol": "USB", "name": "U.S. Bancorp", "exchange": "NYSE", "type": "stock"},
    {"symbol": "PYPL", "name": "PayPal Holdings Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "UBER", "name": "Uber Technologies Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "SNOW", "name": "Snowflake Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "PLTR", "name": "Palantir Technologies Inc.", "exchange": "NYSE", "type": "stock"},
    {"symbol": "HOOD", "name": "Robinhood Markets Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "COIN", "name": "Coinbase Global Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "MSTR", "name": "MicroStrategy Inc.", "exchange": "NASDAQ", "type": "stock"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE", "type": "etf"},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "exchange": "NASDAQ", "type": "etf"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "exchange": "NYSE", "type": "etf"},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "exchange": "NYSE", "type": "etf"},
    {"symbol": "SLV", "name": "iShares Silver Trust", "exchange": "NYSE", "type": "etf"},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "exchange": "NASDAQ", "type": "etf"},
    {"symbol": "VXX", "name": "iPath Series B S&P 500 VIX Short-Term Futures ETN", "exchange": "NYSE", "type": "etf"},
    {"symbol": "ARKK", "name": "ARK Innovation ETF", "exchange": "NYSE", "type": "etf"},
]

_CRYPTO_INDEX = [
    {"symbol": "BTC-USD", "name": "Bitcoin", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "ETH-USD", "name": "Ethereum", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "SOL-USD", "name": "Solana", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "BNB-USD", "name": "BNB", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "XRP-USD", "name": "XRP", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "ADA-USD", "name": "Cardano", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "AVAX-USD", "name": "Avalanche", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "DOGE-USD", "name": "Dogecoin", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "DOT-USD", "name": "Polkadot", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "MATIC-USD", "name": "Polygon", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "LINK-USD", "name": "Chainlink", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "UNI-USD", "name": "Uniswap", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "ATOM-USD", "name": "Cosmos", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "LTC-USD", "name": "Litecoin", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "NEAR-USD", "name": "NEAR Protocol", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "ARB-USD", "name": "Arbitrum", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "OP-USD", "name": "Optimism", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "APT-USD", "name": "Aptos", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "SUI-USD", "name": "Sui", "exchange": "CRYPTO", "type": "crypto"},
    {"symbol": "SHIB-USD", "name": "Shiba Inu", "exchange": "CRYPTO", "type": "crypto"},
]

_ALL_SYMBOLS = _STOCK_INDEX + _CRYPTO_INDEX


def _search_symbols(q: str, exchange: str = "", sym_type: str = "", limit: int = 30) -> list[dict]:
    q_lower = q.lower()
    results = []
    for s in _ALL_SYMBOLS:
        if exchange and s["exchange"].upper() != exchange.upper():
            continue
        if sym_type and s["type"] != sym_type:
            continue
        if q_lower in s["symbol"].lower() or q_lower in s["name"].lower():
            results.append(s)
        if len(results) >= limit:
            break
    return results


@router.get("/symbols/search")
async def search_symbols(
    q: str = Query("", description="Search query"),
    exchange: str = Query("", description="Exchange filter"),
    type: str = Query("", alias="type", description="Type filter: stock|crypto|etf"),
):
    results = _search_symbols(q, exchange, type)
    return {"results": results}


@router.get("/symbols/{ticker}/info")
async def get_symbol_info(ticker: str):
    """Light metadata for TradingView symbol resolution."""
    ticker_upper = ticker.upper()
    is_crypto = ticker_upper.endswith("-USD") or ticker_upper.endswith("-USDT")

    # Find in index
    match = next((s for s in _ALL_SYMBOLS if s["symbol"].upper() == ticker_upper), None)

    if match:
        sym_type = match["type"]
        exchange = match["exchange"]
        name = match["name"]
    else:
        sym_type = "crypto" if is_crypto else "stock"
        exchange = "CRYPTO" if is_crypto else "NYSE"
        name = ticker_upper

    return {
        "symbol": ticker_upper,
        "name": name,
        "exchange": exchange,
        "type": sym_type,
        "sector": None,
        "industry": None,
        "currency": "USD",
        "pricescale": 100000 if is_crypto else 100,
        "has_intraday": True,
    }


@router.get("/symbols/{ticker}/full")
async def get_symbol_full(
    ticker: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full symbol info for right-side panel."""
    ticker_upper = ticker.upper()
    is_crypto = ticker_upper.endswith("-USD") or ticker_upper.endswith("-USDT")

    match = next((s for s in _ALL_SYMBOLS if s["symbol"].upper() == ticker_upper), None)
    sym_type = match["type"] if match else ("crypto" if is_crypto else "stock")
    exchange = match["exchange"] if match else ("CRYPTO" if is_crypto else "NYSE")
    name = match["name"] if match else ticker_upper

    # Try to get current price from bars endpoint logic
    current_price = None
    change = None
    change_pct = None
    stats = {}

    try:
        import yfinance as yf
        t = yf.Ticker(ticker_upper)
        info = t.fast_info
        current_price = float(getattr(info, "last_price", None) or 0) or None
        prev_close = float(getattr(info, "previous_close", None) or 0) or None
        if current_price and prev_close:
            change = round(current_price - prev_close, 4)
            change_pct = round((change / prev_close) * 100, 2)
        fifty_two_week_high = float(getattr(info, "year_high", None) or 0) or None
        fifty_two_week_low = float(getattr(info, "year_low", None) or 0) or None
        market_cap = float(getattr(info, "market_cap", None) or 0) or None
        avg_volume = float(getattr(info, "three_month_average_volume", None) or 0) or None
        stats = {
            "market_cap": market_cap,
            "pe_ratio": None,
            "eps": None,
            "dividend_yield": None,
            "52w_high": fifty_two_week_high,
            "52w_low": fifty_two_week_low,
            "avg_volume": avg_volume,
            "beta": None,
        }
    except Exception:
        pass

    # Market status
    from datetime import time as dtime
    now_utc = datetime.now(timezone.utc)
    # NYSE hours 9:30-16:00 ET = 13:30-20:00 UTC (rough)
    if is_crypto:
        market_status = "open"  # 24/7
    else:
        h = now_utc.hour
        m = now_utc.minute
        total_min = h * 60 + m
        if 810 <= total_min <= 1200:  # 13:30-20:00 UTC
            market_status = "open"
        elif 780 <= total_min < 810:
            market_status = "pre"
        elif 1200 <= total_min <= 1440:
            market_status = "after"
        else:
            market_status = "closed"

    return {
        "symbol": ticker_upper,
        "name": name,
        "exchange": exchange,
        "type": sym_type,
        "sector": None,
        "industry": None,
        "logo_url": None,
        "current_price": current_price,
        "change": change,
        "change_pct": change_pct,
        "market_status": market_status,
        "last_update_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "ai_summary": None,
        "ai_summary_at": None,
        "latest_news": [],
    }


@router.get("/bot-trades")
async def get_bot_trades_for_chart(
    symbol: str = Query(...),
    from_ts: Optional[int] = Query(None, alias="from"),
    to_ts: Optional[int] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Non-quarantined bot trades for a symbol in a time range (TradingView marks)."""
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile

    q = (
        db.query(
            BotTrade.id,
            BotTrade.ts,
            BotTrade.side,
            BotTrade.qty,
            BotTrade.fill_price_cents,
            BotProfile.name.label("bot_name"),
        )
        .join(BotAllocation, BotTrade.allocation_id == BotAllocation.id)
        .join(BotProfile, BotAllocation.profile_id == BotProfile.id)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotTrade.symbol == symbol.upper(),
            BotTrade.quarantined_at.is_(None),
        )
    )

    if from_ts is not None:
        from_dt = datetime.utcfromtimestamp(from_ts)
        q = q.filter(BotTrade.ts >= from_dt)
    if to_ts is not None:
        to_dt = datetime.utcfromtimestamp(to_ts)
        q = q.filter(BotTrade.ts <= to_dt)

    rows = q.order_by(BotTrade.ts.asc()).limit(500).all()

    trades = [
        {
            "id": r.id,
            "ts": r.ts.isoformat() if r.ts else None,
            "bot_name": r.bot_name,
            "side": r.side,
            "qty": r.qty,
            "price": round(r.fill_price_cents / 100, 4) if r.fill_price_cents else None,
        }
        for r in rows
    ]
    return {"trades": trades}


@router.get("/bot-signals")
async def get_bot_signals_for_chart(
    symbol: str = Query(...),
    from_ts: Optional[int] = Query(None, alias="from"),
    to_ts: Optional[int] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bot signals for a symbol in a time range (TradingView timescale marks)."""
    from app.db.models.bots import BotSignal, BotAllocation, BotProfile

    q = (
        db.query(
            BotSignal.id,
            BotSignal.ts,
            BotSignal.side,
            BotSignal.confidence,
            BotSignal.entry_price,
            BotSignal.stop_price,
            BotSignal.target_price,
            BotSignal.strategy,
            BotProfile.name.label("bot_name"),
        )
        .join(BotAllocation, BotSignal.allocation_id == BotAllocation.id)
        .join(BotProfile, BotAllocation.profile_id == BotProfile.id)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotSignal.symbol == symbol.upper(),
        )
    )

    if from_ts is not None:
        from_dt = datetime.utcfromtimestamp(from_ts)
        q = q.filter(BotSignal.ts >= from_dt)
    if to_ts is not None:
        to_dt = datetime.utcfromtimestamp(to_ts)
        q = q.filter(BotSignal.ts <= to_dt)

    rows = q.order_by(BotSignal.ts.asc()).limit(500).all()

    signals = [
        {
            "id": r.id,
            "ts": r.ts.isoformat() if r.ts else None,
            "bot_name": r.bot_name,
            "strategy": r.strategy or "signal",
            "side": r.side,
            "confidence": r.confidence,
            "entry_price": r.entry_price,
            "stop_price": r.stop_price,
            "target_price": r.target_price,
        }
        for r in rows
    ]
    return {"signals": signals}
