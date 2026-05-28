from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.db.models.users import User

router = APIRouter(prefix="/api/defi", tags=["defi"])


@router.get("/staking")
async def get_staking(current_user: User = Depends(get_current_user)):
    from app.services.defi_rates import get_staking_rates
    rates = await get_staking_rates()
    return {"rates": rates}


@router.get("/lending")
async def get_lending(
    assets: str = Query("USDC,USDT,ETH,WBTC,DAI"),
    current_user: User = Depends(get_current_user),
):
    from app.services.defi_rates import get_lending_rates
    asset_list = [a.strip().upper() for a in assets.split(",") if a.strip()]
    rates = await get_lending_rates(asset_list)
    return {"rates": rates}


@router.get("/yields")
async def get_yields(
    min_tvl: float = Query(1_000_000),
    limit: int = Query(30, le=100),
    current_user: User = Depends(get_current_user),
):
    from app.services.defi_rates import get_top_yield_opportunities
    yields = await get_top_yield_opportunities(min_tvl_usd=min_tvl, limit=limit)
    return {"yields": yields}
