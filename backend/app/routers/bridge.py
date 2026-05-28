from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.db.models.users import User

router = APIRouter(prefix="/api/bridge", tags=["bridge"])


@router.get("/quote")
async def bridge_quote(
    from_chain: str = Query(..., description="Source chain name"),
    to_chain: str = Query(..., description="Destination chain name"),
    token: str = Query("USDC", description="Token symbol"),
    amount_usd: float = Query(1000.0, description="Amount in USD"),
    current_user: User = Depends(get_current_user),
):
    from app.services.bridge import get_bridge_quote
    result = await get_bridge_quote(from_chain, to_chain, token, amount_usd)
    return result


@router.get("/chains")
async def supported_chains(current_user: User = Depends(get_current_user)):
    from app.services.bridge import get_supported_chains
    chains = await get_supported_chains()
    return {"chains": chains}


@router.get("/tokens/{chain_id}")
async def supported_tokens(
    chain_id: int,
    current_user: User = Depends(get_current_user),
):
    from app.services.bridge import get_supported_tokens
    tokens = await get_supported_tokens(chain_id)
    return {"tokens": tokens}
