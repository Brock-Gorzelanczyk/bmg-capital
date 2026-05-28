from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.dependencies import get_current_user
from app.db.models.users import User

router = APIRouter(prefix="/api/security", tags=["security"])

_CHAIN_MAP = {
    "ethereum": "1",
    "bsc": "56",
    "polygon": "137",
    "arbitrum": "42161",
    "base": "8453",
    "optimism": "10",
    "solana": "solana",
}


@router.get("/token/{chain}/{address}")
async def check_token(
    chain: str = Path(..., description="Chain name or ID"),
    address: str = Path(..., description="Token contract address"),
    current_user: User = Depends(get_current_user),
):
    from app.services.token_security import check_token as _check
    chain_id = _CHAIN_MAP.get(chain.lower(), chain)
    result = await _check(address, chain_id)
    return result


@router.get("/approvals/{chain}/{wallet}")
async def check_approvals(
    chain: str = Path(..., description="Chain name or ID"),
    wallet: str = Path(..., description="Wallet address"),
    current_user: User = Depends(get_current_user),
):
    from app.services.token_security import check_wallet_approvals
    chain_id = _CHAIN_MAP.get(chain.lower(), chain)
    result = await check_wallet_approvals(wallet, chain_id)
    return result


@router.get("/batch")
async def batch_check(
    addresses: str = Query(..., description="Comma-separated: chain:address pairs"),
    current_user: User = Depends(get_current_user),
):
    from app.services.token_security import batch_check_tokens
    by_chain: dict[str, list[str]] = {}
    for pair in addresses.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        chain, addr = pair.split(":", 1)
        chain_id = _CHAIN_MAP.get(chain.lower(), chain)
        by_chain.setdefault(chain_id, []).append(addr.strip())
    results = await batch_check_tokens(by_chain)
    return {"results": results}
