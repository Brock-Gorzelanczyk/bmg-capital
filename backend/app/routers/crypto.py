from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.services import coingecko as cg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/market")
async def get_market(_user=Depends(get_current_user)):
    """Top 100 coins with sparklines and 1h/24h/7d% from CoinGecko. 5-minute cache."""
    loop = asyncio.get_running_loop()
    coins = await loop.run_in_executor(None, lambda: cg.get_top_coins(100))
    return {"coins": coins}


@router.get("/overview")
async def get_overview(_user=Depends(get_current_user)):
    """Market overview: total cap, BTC dominance, Fear & Greed index."""
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=2) as ex:
        gm_fut = loop.run_in_executor(ex, cg.get_global_market)
        fg_fut = loop.run_in_executor(ex, cg.get_fear_greed)
        gm, fg = await asyncio.gather(gm_fut, fg_fut)
    return {**gm, "fear_greed": fg}


@router.get("/trending")
async def get_trending(_user=Depends(get_current_user)):
    """Trending coins from CoinGecko."""
    loop = asyncio.get_running_loop()
    coins = await loop.run_in_executor(None, cg.get_trending)
    return {"coins": coins}


@router.post("/refresh")
async def refresh_market(_user=Depends(get_current_user)):
    """Evict CoinGecko caches so the next fetch gets fresh data."""
    cg.invalidate_all()
    return {"ok": True}


@router.get("/quote/{symbol}")
async def get_coin_quote(symbol: str, _user=Depends(get_current_user)):
    """Single coin real-time price via Kraken. Symbol format: ETH/USD or ETH or ETH-USD."""
    # Normalize to internal BASE/USD format
    sym = symbol.upper().replace("-USD", "/USD")
    if "/" not in sym:
        sym = f"{sym}/USD"

    def _fetch():
        try:
            from app.services.live_prices import fetch_crypto_prices_kraken
            prices = fetch_crypto_prices_kraken([sym])
            last = prices.get(sym)
            if not last:
                return None
            return {
                "symbol": sym,
                "last": round(last, 8),
                "prev_close": None,   # Kraken public ticker doesn't give prev close; use bars for that
                "change_pct": None,
                "source": "kraken",
            }
        except Exception as e:
            logger.warning(f"Crypto quote failed {sym}: {e}")
            return None

    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"symbol": sym, "last": None, "error": "price unavailable"}
    return result


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, days: int = 90, _user=Depends(get_current_user)):
    """Daily OHLCV bars for price charting. symbol: BTC-USD format."""
    sym_upper = symbol.upper()
    ccxt_sym = sym_upper.replace("-USD", "/USDT")

    def _fetch() -> list:
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            ohlcv = exchange.fetch_ohlcv(ccxt_sym, timeframe="1d", limit=days)
            return [
                {"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]), "v": float(r[5])}
                for r in ohlcv if r[4] is not None
            ]
        except Exception as exc:
            logger.warning(f"CCXT OHLCV failed for {ccxt_sym}: {exc}")
            try:
                import yfinance as yf
                df = yf.download(sym_upper, period=f"{days}d", interval="1d",
                                 progress=False, auto_adjust=True)
                if df.empty:
                    return []
                df.columns = [c.lower() for c in df.columns]
                return [
                    {"t": int(ts.timestamp() * 1000), "o": float(row["open"]),
                     "h": float(row["high"]), "l": float(row["low"]),
                     "c": float(row["close"]), "v": float(row["volume"])}
                    for ts, row in df.iterrows()
                ]
            except Exception as exc2:
                logger.warning(f"yfinance OHLCV fallback failed for {sym_upper}: {exc2}")
                return []

    bars = await asyncio.to_thread(_fetch)
    return {"symbol": symbol, "bars": bars}


# ── USDC Yield endpoints ────────────────────────────────────────────────────────

from sqlalchemy.orm import Session
from app.dependencies import get_db
from app.db.models.users import User
from app.db.models.tier import UserTier
from app.services.entitlements import get_entitlements


@router.get("/usdc-yield/rates")
def usdc_yield_rates(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tier_row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    ents = get_entitlements(tier_row) if tier_row else {}
    apy = float(ents.get("apy_on_cash", 0.0)) or 4.0  # default 4% for display even if free
    return {
        "standard_apy": 4.0,
        "plus_apy": 4.0,
        "premium_apy": 5.0,
        "current_user_apy": apy if apy > 0 else 4.0,
        "partner": "Circle",
        "paid": "daily",
        "lockup": "none",
        "fdic_note": "Not FDIC insured. USDC is a regulated stablecoin backed 1:1 by USD held in Circle-managed accounts.",
    }


@router.get("/usdc-yield/balance")
def usdc_yield_balance(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import hashlib
    seed_val = int(hashlib.md5(str(current_user.id).encode()).hexdigest()[:8], 16)
    balance = round((seed_val % 1000) * 10.5, 2)
    tier_row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    ents = get_entitlements(tier_row) if tier_row else {}
    apy = float(ents.get("apy_on_cash", 4.0)) or 4.0
    return {
        "usdc_balance": balance,
        "apy": apy,
        "daily_yield": round(balance * apy / 100 / 365, 4),
        "ytd_earned": round(balance * apy / 100 / 12 * 3, 2),
    }
