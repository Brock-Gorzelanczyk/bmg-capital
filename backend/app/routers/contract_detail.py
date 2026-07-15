"""
Contract Detail — single-option live view backing /contract/{position_id}.

Two endpoints:
  GET /api/contract/positions/{position_id}
    Returns everything the Contract Detail page needs on load:
    bot ownership, parsed OCC fields, avg premium, quantity, current mark
    (from options quote), spot on the underlying, breakeven, DTE.

  GET /api/contract/bars/{occ_symbol}?window=1D|1W|1M|3M|YTD|ALL
    Returns time-series marks for the option so the chart can plot the
    contract's own history plus a live-append tail as new quotes arrive.

Both use the ALPACA_API_KEY/ALPACA_PAPER_KEY creds already wired into
the equities + options fetchers.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User
from app.db.models.bots import BotPosition, BotTrade, BotAllocation, BotProfile
from app.services.option_marks import fetch_option_marks_cents, occ_for_position

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contract", tags=["contract-detail"])


_ALPACA_BARS_URL = "https://data.alpaca.markets/v1beta1/options/bars"

_WINDOW_TO_TIMEFRAME_LIMIT = {
    "1D":  ("5Min",  78),      # 6.5h * 12
    "1W":  ("30Min", 65),      # 5d * 13
    "1M":  ("1Hour", 154),     # 22d * 7
    "3M":  ("1Day",  63),
    "YTD": ("1Day",  200),
    "ALL": ("1Day",  400),
}


def _alpaca_headers() -> dict[str, str]:
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError("Alpaca creds not configured")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}


def _fetch_option_bars(occ: str, window: str) -> list[dict]:
    """Return list of {ts, o, h, l, c} for the OCC contract over the window.
    Silent-empty on any error so the UI can degrade gracefully."""
    tf, limit = _WINDOW_TO_TIMEFRAME_LIMIT.get(window.upper(), _WINDOW_TO_TIMEFRAME_LIMIT["1D"])
    now = datetime.now(timezone.utc)
    # Rough back-look per window; Alpaca truncates to the actual bar count anyway.
    lookback = {
        "1D": timedelta(days=1), "1W": timedelta(days=8), "1M": timedelta(days=32),
        "3M": timedelta(days=95), "YTD": timedelta(days=365), "ALL": timedelta(days=730),
    }.get(window.upper(), timedelta(days=1))
    start = (now - lookback).isoformat()

    qs = urllib.parse.urlencode({
        "symbols": occ,
        "timeframe": tf,
        "start": start,
        "limit": limit,
        "sort": "asc",
    })
    url = f"{_ALPACA_BARS_URL}?{qs}"
    try:
        req = urllib.request.Request(url, headers=_alpaca_headers())
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("[contract/bars] Alpaca options/bars fetch failed for %s: %s", occ, exc)
        return []

    raw = (data.get("bars") or {}).get(occ) or []
    out: list[dict] = []
    for b in raw:
        try:
            out.append({
                "ts": b.get("t"),        # ISO string
                "o":  float(b.get("o") or 0),
                "h":  float(b.get("h") or 0),
                "l":  float(b.get("l") or 0),
                "c":  float(b.get("c") or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def _fetch_spot(underlying: str) -> Optional[float]:
    """Get the current spot price of the underlying via the same live-prices
    cache the rest of the app uses. Returns None on any error."""
    try:
        from app.services.live_prices import fetch_live_prices
        prices = fetch_live_prices([underlying]) or {}
        p = prices.get(underlying)
        return float(p) if p else None
    except Exception as exc:
        logger.debug("[contract] spot fetch failed for %s: %s", underlying, exc)
        return None


def _parse_occ(occ: str) -> Optional[dict]:
    """Return {root, expiry (ISO), type ('CALL'|'PUT'), strike} from an OCC symbol.
    Mirrors the frontend parseOCC() so backend and UI never disagree."""
    import re as _re
    m = _re.match(r"^([A-Z][A-Z0-9]*)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", (occ or "").upper())
    if not m:
        return None
    root, yy, mm, dd, cp, strike_raw = m.groups()
    return {
        "root": root,
        "expiry": f"20{yy}-{mm}-{dd}",
        "type": "CALL" if cp == "C" else "PUT",
        "strike": int(strike_raw) / 1000.0,
    }


def _dte(iso_date: str) -> Optional[int]:
    try:
        d = datetime.fromisoformat(iso_date).date()
        today = datetime.now(timezone.utc).date()
        return (d - today).days
    except Exception:
        return None


# ── GET /api/contract/positions/{position_id} ───────────────────────────────

@router.get("/positions/{position_id}")
def get_position_detail(
    position_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return everything Contract Detail needs on first load."""
    pos = db.query(BotPosition).filter(BotPosition.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail=f"position {position_id} not found")

    alloc = db.query(BotAllocation).filter(BotAllocation.id == pos.allocation_id).first()
    if not alloc or alloc.user_id != current_user.id:
        # Prevent cross-user peeking.
        raise HTTPException(status_code=404, detail="position not accessible")

    profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
    entry_trade = (
        db.query(BotTrade)
        .filter(BotTrade.position_id == pos.id)
        .order_by(BotTrade.ts.asc())
        .first()
    )

    is_option = bool(getattr(pos, "option_type", None))
    occ = pos.symbol if is_option else None
    parsed = _parse_occ(occ) if occ else None
    dte = _dte(parsed["expiry"]) if parsed else None

    contracts = int(pos.contract_count or pos.qty or 0)
    avg_premium = (pos.avg_cost_cents or 0) / 100.0
    contract_multiplier = 100 if is_option else 1

    # Live mark from the options quote endpoint (60s cached).
    mark: Optional[float] = None
    mark_source = "unavailable"
    if is_option and occ:
        marks = fetch_option_marks_cents([occ]) or {}
        cents = marks.get(occ)
        if cents is not None:
            mark = cents / 100.0
            mark_source = "alpaca_options_quote"

    # Spot on the underlying (informational — breakeven distance is derived from it).
    underlying = parsed["root"] if parsed else (pos.underlying_symbol or pos.symbol)
    spot = _fetch_spot(underlying) if underlying else None

    # P&L math — SAME formula as portfolio.py fix (×100 for options) with
    # a sign flip for short legs. For a short, premium received at entry is
    # the cost basis (credit) and current premium is the cost to close (debit):
    # short_pnl = premium_received - current_premium. Longs: value - cost.
    is_short = (getattr(pos, "side", "long") or "long").lower() == "short"
    cost_basis = avg_premium * contracts * contract_multiplier
    market_value = (mark * contracts * contract_multiplier) if (mark is not None) else None
    if market_value is None:
        open_pl = None
    elif is_short:
        open_pl = cost_basis - market_value
    else:
        open_pl = market_value - cost_basis
    open_pl_pct = ((open_pl / cost_basis) * 100.0) if (open_pl is not None and cost_basis > 0) else None

    # Breakeven — call: strike + avg; put: strike - avg.
    breakeven = None
    if parsed and avg_premium > 0:
        breakeven = parsed["strike"] + avg_premium if parsed["type"] == "CALL" else parsed["strike"] - avg_premium

    return {
        "position_id": pos.id,
        "bot": {
            "name": profile.name if profile else None,
            "asset_class": profile.asset_class if profile else None,
            "profile_id": profile.id if profile else None,
        },
        "occ_symbol": occ,
        "is_option": is_option,
        "parsed": parsed,
        "underlying": underlying,
        "spot": spot,
        "expiry_date": parsed["expiry"] if parsed else None,
        "dte": dte,
        "contracts": contracts,
        "side": getattr(pos, "side", "long"),
        "avg_premium": round(avg_premium, 4),
        "cost_basis": round(cost_basis, 2),
        "mark": mark,
        "market_value": round(market_value, 2) if market_value is not None else None,
        "open_pl": round(open_pl, 2) if open_pl is not None else None,
        # Cap display at ±999% so -1994% garbage never renders — same guard
        # the frontend parseOCC.optionPnL uses.
        "open_pl_pct": max(-999.0, min(999.0, round(open_pl_pct, 4))) if open_pl_pct is not None else None,
        "breakeven": round(breakeven, 2) if breakeven else None,
        "mark_source": mark_source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
        "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
        "entry_trade_id": entry_trade.id if entry_trade else None,
        "alpaca_order_id": entry_trade.alpaca_order_id if entry_trade else None,
    }


# ── GET /api/contract/bars/{occ_symbol} ─────────────────────────────────────

@router.get("/bars/{occ_symbol}")
def get_contract_bars(
    occ_symbol: str = Path(...),
    window: str = Query("1D", pattern="^(1D|1W|1M|3M|YTD|ALL)$"),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return time-series bars for an OCC contract over the requested window.

    Response shape:
      {"symbol": OCC, "window": "1D", "bars": [{ts, o, h, l, c}, ...],
       "fetched_at": ISO}

    Backing: Alpaca /v1beta1/options/bars. Returns an empty bars list on any
    upstream error so the chart can render a "no data" empty state without
    breaking the page.
    """
    bars = _fetch_option_bars(occ_symbol.upper(), window.upper())
    return {
        "symbol": occ_symbol.upper(),
        "window": window.upper(),
        "bars": bars,
        "count": len(bars),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /api/contract/quote/{occ_symbol} ────────────────────────────────────
# Lightweight endpoint the frontend can poll every 2-5s for the live mark.
# Bypasses the 60s cache in option_marks so streaming feels fresh.

@router.get("/quote/{occ_symbol}")
def get_contract_quote(
    occ_symbol: str = Path(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Single-symbol live quote (mid of NBBO)."""
    from app.services.option_marks import _fetch_alpaca_quotes  # bypass 60s cache
    quotes = _fetch_alpaca_quotes([occ_symbol.upper()])
    mid = quotes.get(occ_symbol.upper())
    return {
        "symbol": occ_symbol.upper(),
        "mark": mid,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
