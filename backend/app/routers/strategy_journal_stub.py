"""Explicit disabled-stub for the strategy-journal endpoints.

Ledger 2026-08-13: the real router (app/routers/strategy_journal.py) was
commented out in main.py on 2026-07-16. Callers hitting those paths were
falling through to the SPA catchall (main.py:1934) and getting HTML back
— confusing to any frontend/agent that expected JSON.

This stub registers the same prefix and returns a clear machine-readable
"disabled" payload so callers can degrade gracefully. Also serves as a
tombstone so nobody wonders why the URL exists but returns HTML.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(
    prefix="/api/admin/strategy-journal",
    tags=["strategy-journal-stub"],
)

_DISABLED_PAYLOAD = {
    "disabled": True,
    "reason": "strategy-journal endpoints disabled 2026-07-16 (never re-enabled).",
    "shipped_on": "2026-07-15",
    "disabled_on": "2026-07-16",
    "hint": "If you need per-bot daily analytics, use /api/leaderboard.",
}


@router.get("/{bot_id}")
async def stub_get_journal(bot_id: str):
    return _DISABLED_PAYLOAD


@router.get("/{bot_id}/rolling/30d")
async def stub_get_rolling(bot_id: str):
    return _DISABLED_PAYLOAD


@router.get("/{bot_id}/history")
async def stub_get_history(bot_id: str):
    return _DISABLED_PAYLOAD


@router.get("/")
async def stub_index():
    return _DISABLED_PAYLOAD
