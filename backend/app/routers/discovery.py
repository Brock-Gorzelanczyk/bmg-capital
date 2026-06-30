from __future__ import annotations

import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_current_user
from app.db.models.users import User
from app.services.discovery import get_themes_with_performance, get_ipo_calendar, get_insider_trades

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/discovery", tags=["discovery"])


# ── Equity Discovery ─────────────────────────────────────────────────────────

@router.get("/themes")
async def themes():
    return {"themes": await get_themes_with_performance()}


# ── AI Theme Generator ───────────────────────────────────────────────────────

class GenerateThemeRequest(BaseModel):
    prompt: str


_THEME_SYSTEM = (
    "You are a financial analyst. Generate a thematic stock basket based on the user's description. "
    'Return JSON: { "name": str, "description": str (1 sentence), "emoji": str, "tickers": [str] (5-8 NYSE/NASDAQ symbols) } '
    "Only include real, well-known public companies. Return ONLY valid JSON."
)


@router.post("/themes/generate")
async def generate_theme(
    body: GenerateThemeRequest,
    _user: User = Depends(get_current_user),
):
    try:
        import asyncio
        from app.services.llm_client import call_llm_cached
        from fastapi import HTTPException
        raw_text = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: call_llm_cached(
                model="claude-haiku-4-5-20251001",
                prompt=body.prompt,
                system_prompt=_THEME_SYSTEM,
                max_tokens=512,
                ttl_seconds=3600,
                cache_key_extra=body.prompt,
                agent_name="discovery",
            ),
        )
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.warning(f"Theme generation JSON parse error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail="AI returned invalid JSON")
    except Exception as e:
        logger.warning(f"Theme generation failed: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=str(e))

    theme = {
        "id": f"custom-{uuid.uuid4().hex[:8]}",
        "name": parsed.get("name", "Custom Theme"),
        "description": parsed.get("description", ""),
        "emoji": parsed.get("emoji", "✨"),
        "tickers": parsed.get("tickers", []),
        "performance": [],
    }
    return {"theme": theme}


@router.get("/ipos")
async def ipos(days_ahead: int = Query(90, le=180)):
    return {"ipos": await get_ipo_calendar(days_ahead)}


@router.get("/insiders")
async def insiders(limit: int = Query(50, le=100)):
    return {"insiders": await get_insider_trades(limit)}


# ── Crypto Discovery ─────────────────────────────────────────────────────────

@router.get("/crypto/launches")
async def crypto_launches(
    min_liquidity: float = Query(25_000, description="Min liquidity in USD"),
    limit: int = Query(50, le=100),
    _user: User = Depends(get_current_user),
):
    from app.services.dexscreener import get_new_launches
    launches = await get_new_launches(min_liquidity_usd=min_liquidity, limit=limit)
    return {"launches": launches}


@router.get("/crypto/trending")
async def crypto_trending(
    chain: str = Query("ethereum"),
    limit: int = Query(20, le=50),
    _user: User = Depends(get_current_user),
):
    from app.services.dexscreener import get_trending_pairs
    pairs = await get_trending_pairs(chain=chain, limit=limit)
    return {"pairs": pairs}


@router.get("/crypto/memecoins")
async def memecoins(
    limit: int = Query(30, le=50),
    _user: User = Depends(get_current_user),
):
    from app.services.dexscreener import get_memecoin_candidates
    tokens = await get_memecoin_candidates(limit=limit)
    return {"tokens": tokens}


@router.get("/crypto/narratives")
async def narratives(_user: User = Depends(get_current_user)):
    """Return curated narrative baskets with live CoinGecko performance."""
    from app.services.coingecko import get_top_coins

    NARRATIVES = [
        {
            "id": "ai-agents",
            "name": "AI Agents",
            "emoji": "🤖",
            "coins": ["fetch-ai", "singularitynet", "ocean-protocol", "render-token", "worldcoin"],
            "symbols": ["FET", "AGIX", "OCEAN", "RENDER", "WLD"],
        },
        {
            "id": "rwa",
            "name": "Real World Assets",
            "emoji": "🏦",
            "coins": ["ondo-finance", "centrifuge", "goldfinch", "maple"],
            "symbols": ["ONDO", "CFG", "GFI", "MPL"],
        },
        {
            "id": "btc-l2",
            "name": "Bitcoin L2s",
            "emoji": "⚡",
            "coins": ["stacks", "rootstock-infrastructure-framework", "lightning-bitcoin"],
            "symbols": ["STX", "RIF", "LBTC"],
        },
        {
            "id": "depin",
            "name": "DePIN",
            "emoji": "📡",
            "coins": ["helium", "render-token", "hivemapper", "io-net"],
            "symbols": ["HNT", "RENDER", "HONEY", "IO"],
        },
        {
            "id": "zk",
            "name": "ZK & Modular",
            "emoji": "🔮",
            "coins": ["matic-network", "arbitrum", "optimism", "starknet", "polygon-ecosystem-token"],
            "symbols": ["MATIC", "ARB", "OP", "STRK", "POL"],
        },
        {
            "id": "defi-blue-chip",
            "name": "DeFi Blue Chips",
            "emoji": "💎",
            "coins": ["uniswap", "aave", "curve-dao-token", "maker", "lido-dao"],
            "symbols": ["UNI", "AAVE", "CRV", "MKR", "LDO"],
        },
    ]

    # Enrich with live prices from CoinGecko top coins
    try:
        coins_data = await get_top_coins(limit=250)
        price_map = {c["id"]: c for c in coins_data}

        for narrative in NARRATIVES:
            total_pct = 0.0
            count = 0
            enriched = []
            for coin_id in narrative["coins"]:
                coin = price_map.get(coin_id)
                if coin:
                    pct = coin.get("pct_24h") or 0.0
                    total_pct += pct
                    count += 1
                    enriched.append({
                        "id": coin_id,
                        "symbol": coin.get("symbol", "").upper(),
                        "name": coin.get("name", coin_id),
                        "price": coin.get("current_price"),
                        "pct_24h": pct,
                        "market_cap": coin.get("market_cap"),
                        "image": coin.get("image"),
                    })
                else:
                    enriched.append({"id": coin_id, "symbol": "", "name": coin_id, "price": None, "pct_24h": 0.0})
            narrative["avg_pct_24h"] = round(total_pct / count, 2) if count else 0.0
            narrative["coins_data"] = enriched
    except Exception as e:
        for narrative in NARRATIVES:
            narrative["avg_pct_24h"] = 0.0
            narrative["coins_data"] = [{"id": c, "symbol": "", "name": c, "price": None, "pct_24h": 0.0} for c in narrative["coins"]]

    return {"narratives": NARRATIVES}


@router.get("/crypto/ido-calendar")
async def ido_calendar(_user: User = Depends(get_current_user)):
    """Curated IDO/IEO/token-sale calendar."""
    from datetime import datetime, timedelta

    today = datetime.now(timezone.utc).date()

    # Manually curated list — kept fresh via code updates
    IDO_LIST = [
        {
            "project": "Monad",
            "token": "MON",
            "type": "Public Sale",
            "platform": "Multiple",
            "date": str(today + timedelta(days=14)),
            "status": "upcoming",
            "est_raise_usd": 100_000_000,
            "vesting": "6 months cliff, 18 months linear",
            "website": "https://monad.xyz",
            "description": "High-performance EVM-compatible L1 blockchain with parallel execution.",
            "tags": ["L1", "EVM"],
        },
        {
            "project": "Movement Labs",
            "token": "MOVE",
            "type": "Launchpad",
            "platform": "Binance Launchpad",
            "date": str(today + timedelta(days=7)),
            "status": "upcoming",
            "est_raise_usd": 50_000_000,
            "vesting": "TGE 10%, 12 months linear",
            "website": "https://movementlabs.xyz",
            "description": "Move-based L2 on Ethereum for fast, secure smart contracts.",
            "tags": ["L2", "Move"],
        },
        {
            "project": "Berachain",
            "token": "BERA",
            "type": "Public Distribution",
            "platform": "Direct",
            "date": str(today - timedelta(days=30)),
            "status": "priced",
            "price_usd": 8.00,
            "est_raise_usd": 200_000_000,
            "vesting": "TGE 20%, 24 months linear",
            "website": "https://berachain.com",
            "description": "Proof-of-Liquidity L1 — stake assets to earn block rewards.",
            "tags": ["L1", "PoL", "DeFi"],
        },
        {
            "project": "Story Protocol",
            "token": "IP",
            "type": "Exchange Listing",
            "platform": "Binance, Coinbase",
            "date": str(today - timedelta(days=15)),
            "status": "priced",
            "price_usd": 5.25,
            "est_raise_usd": 80_000_000,
            "vesting": "TGE 15%, 18 months",
            "website": "https://storyprotocol.xyz",
            "description": "IP ownership and licensing infrastructure on blockchain.",
            "tags": ["IP", "Creator Economy"],
        },
        {
            "project": "Sonic Labs",
            "token": "S",
            "type": "Airdrop + Sale",
            "platform": "Multiple",
            "date": str(today + timedelta(days=45)),
            "status": "upcoming",
            "est_raise_usd": 30_000_000,
            "vesting": "TGE 25%, 12 months",
            "website": "https://soniclabs.com",
            "description": "High-performance EVM chain, formerly Fantom.",
            "tags": ["L1", "EVM", "DeFi"],
        },
        {
            "project": "Initia",
            "token": "INIT",
            "type": "Launchpad",
            "platform": "OKX Jumpstart",
            "date": str(today + timedelta(days=21)),
            "status": "upcoming",
            "est_raise_usd": 25_000_000,
            "vesting": "TGE 10%, 24 months",
            "website": "https://initia.xyz",
            "description": "Omni-chain L1 with enshrined rollup architecture.",
            "tags": ["L1", "Modular"],
        },
    ]

    IDO_LIST.sort(key=lambda x: (x["status"] != "upcoming", x["date"]))
    return {"events": IDO_LIST}
