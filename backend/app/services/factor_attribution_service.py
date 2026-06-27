"""Portfolio factor attribution service (Phase 6).

Decomposes a user's portfolio P&L over a window into:
  - beta_pnl   = portfolio_beta x spy_return x gross_exposure
  - alpha_pnl  = total_pnl - beta_pnl

Plus exposure breakdowns (sector / strategy / asset class) and
top contributors / detractors by symbol.

Reuses ``BotPosition`` + ``BotTrade`` for open + realized and filters
allocations by ``user_id`` via ``BotAllocation``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.bots import (
    BotAllocation,
    BotProfile,
    BotPosition,
    BotTrade,
    BotSignal,
)
from strategy_lab.core.beta_map import get_beta
from strategy_lab.core.sector_map import get_sector

logger = logging.getLogger(__name__)


# ── Window parsing ────────────────────────────────────────────────────────────

def parse_window(window: str) -> Tuple[datetime, str]:
    """Return (since_utc, normalized_window_label).

    ``ytd``  -> from Jan 1 of current year
    ``Nd``   -> N days back from now
    """
    now = datetime.now(timezone.utc)
    w = (window or "").strip().lower()
    if w == "ytd":
        since = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        return since, "ytd"
    days = {"7d": 7, "30d": 30, "90d": 90}.get(w, 30)
    label = w if w in ("7d", "30d", "90d") else "30d"
    return now - timedelta(days=days), label


# ── SPY return ────────────────────────────────────────────────────────────────

def fetch_spy_return(since: datetime) -> float:
    """Return SPY's total return from ``since`` to "now" as a decimal.

    Strategy:
      1. Try ``app.services.live_prices.fetch_live_prices`` for SPY "now".
      2. Pull a daily history via yfinance for the start price.
      3. On any failure, return 0.0 so attribution degrades to alpha-only.
    """
    spy_now: Optional[float] = None
    spy_start: Optional[float] = None

    try:
        from app.services.live_prices import fetch_live_prices
        prices = fetch_live_prices(["SPY"])
        if prices.get("SPY"):
            spy_now = float(prices["SPY"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_spy_return: live SPY fetch failed: %s", exc)

    try:
        import yfinance as yf
        start_str = (since - timedelta(days=2)).date().isoformat()
        end_str = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        hist = yf.Ticker("SPY").history(start=start_str, end=end_str, interval="1d", auto_adjust=True)
        if hist is not None and not hist.empty:
            target_d = since.date()
            close_series = hist["Close"]
            for ts, val in close_series.items():
                if ts.date() >= target_d:
                    spy_start = float(val)
                    break
            if spy_start is None:
                spy_start = float(close_series.iloc[0])
            if spy_now is None:
                spy_now = float(close_series.iloc[-1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_spy_return: yfinance history failed: %s", exc)

    if not spy_now or not spy_start or spy_start <= 0:
        return 0.0
    return (spy_now / spy_start) - 1.0


# ── Symbol classification ─────────────────────────────────────────────────────

def _asset_class_for_symbol(sym: str, profile_asset_class: Optional[str]) -> str:
    """Best-effort asset class bucket: stock / crypto / options."""
    if not sym:
        return profile_asset_class or "stock"
    s = sym.upper()
    if "/" in s or s.endswith("-USD"):
        return "crypto"
    if profile_asset_class:
        pc = profile_asset_class.lower()
        if pc.startswith("crypto"):
            return "crypto"
        if pc.startswith("option"):
            return "options"
        if pc.startswith("stock") or pc.startswith("equity"):
            return "stock"
    return "stock"


# ── Per-position window P&L ───────────────────────────────────────────────────

def _position_pnl_cents_for_window(
    db: Session,
    position: BotPosition,
    since: datetime,
) -> float:
    """Return P&L cents attributable to this position within the window."""
    if position.closed_at is not None:
        closed_at = position.closed_at
        cutoff = since.replace(tzinfo=None) if closed_at.tzinfo is None else since
        if closed_at < cutoff:
            return 0.0
        trades = (
            db.query(BotTrade)
            .filter(BotTrade.position_id == position.id, BotTrade.quarantined_at.is_(None))
            .all()
        )
        sell = sum(t.fill_price_cents * t.qty for t in trades if t.side.lower() in ("sell", "short_sell", "short"))
        buy = sum(t.fill_price_cents * t.qty for t in trades if t.side.lower() in ("buy", "cover", "short_cover"))
        fees = sum(t.fees_cents or 0 for t in trades)
        return float(sell - buy - fees)

    last_trade = (
        db.query(BotTrade)
        .filter(BotTrade.position_id == position.id, BotTrade.quarantined_at.is_(None))
        .order_by(BotTrade.ts.desc())
        .first()
    )
    if last_trade is None:
        return 0.0
    mark = float(last_trade.fill_price_cents)
    return float((mark - position.avg_cost_cents) * position.qty)


# ── Main aggregator ───────────────────────────────────────────────────────────

def compute_factor_attribution(
    db: Session,
    user_id: int,
    window: str = "30d",
) -> Dict[str, Any]:
    """Build the factor-attribution response for a user.

    Shape matches the Phase 6 spec exactly.
    """
    since, window_label = parse_window(window)

    allocations: List[BotAllocation] = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id)
        .all()
    )

    if not allocations:
        return {
            "window": window_label,
            "total_pnl_cents": 0,
            "beta_pnl_cents": 0,
            "alpha_pnl_cents": 0,
            "portfolio_beta": 0.0,
            "gross_exposure_cents": 0,
            "net_exposure_cents": 0,
            "exposures": {"by_sector": {}, "by_strategy": {}, "by_asset_class": {}},
            "top_contributors": [],
            "top_detractors": [],
        }

    alloc_ids = [a.id for a in allocations]
    alloc_by_id = {a.id: a for a in allocations}

    profile_map: Dict[int, BotProfile] = {
        p.id: p for p in db.query(BotProfile)
        .filter(BotProfile.id.in_({a.profile_id for a in allocations}))
        .all()
    }

    # 1. Pull positions touching the window
    since_naive = since.replace(tzinfo=None)
    try:
        window_filter = or_(
            BotPosition.closed_at.is_(None),
            BotPosition.closed_at >= since_naive,
        )
    except TypeError:
        # Test fakes pass MagicMock columns through; skip the OR predicate.
        window_filter = None

    pos_q = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.quarantined_at.is_(None),
        )
    )
    if window_filter is not None:
        pos_q = pos_q.filter(window_filter)
    positions: List[BotPosition] = pos_q.all()

    # 2. Aggregate per symbol
    by_symbol: Dict[str, Dict[str, float]] = {}
    gross_exposure_cents = 0.0
    net_exposure_cents = 0.0
    beta_x_exposure_sum = 0.0

    by_sector_exposure: Dict[str, float] = {}
    by_strategy_exposure: Dict[str, float] = {}
    by_asset_class_exposure: Dict[str, float] = {}

    def _strategy_for_position(pos: BotPosition) -> str:
        try:
            q = db.query(BotSignal).filter(
                BotSignal.allocation_id == pos.allocation_id,
                BotSignal.symbol == pos.symbol,
            )
            if pos.opened_at is not None:
                try:
                    q = q.filter(BotSignal.ts <= (pos.opened_at + timedelta(minutes=10)))
                except TypeError:
                    pass
            sig = q.order_by(BotSignal.ts.desc()).first()
        except Exception:
            sig = None
        if sig and getattr(sig, "strategy", None):
            return sig.strategy
        return "unattributed"

    for pos in positions:
        sym = pos.symbol
        alloc = alloc_by_id.get(pos.allocation_id)
        if alloc is None:
            continue
        profile = profile_map.get(alloc.profile_id)
        profile_asset_class = profile.asset_class if profile else None

        pnl_cents = _position_pnl_cents_for_window(db, pos, since)

        if pos.closed_at is None:
            notional = float(pos.avg_cost_cents) * float(pos.qty)
            signed = notional if pos.side.lower() == "long" else -notional
            gross_exposure_cents += abs(signed)
            net_exposure_cents += signed

            beta = get_beta(sym)
            beta_x_exposure_sum += beta * abs(signed)

            ac = _asset_class_for_symbol(sym, profile_asset_class)
            by_asset_class_exposure[ac] = by_asset_class_exposure.get(ac, 0.0) + abs(signed)

            sector = get_sector(sym) or "other"
            by_sector_exposure[sector] = by_sector_exposure.get(sector, 0.0) + abs(signed)

            strat = _strategy_for_position(pos)
            by_strategy_exposure[strat] = by_strategy_exposure.get(strat, 0.0) + abs(signed)

        entry = by_symbol.setdefault(sym, {"pnl_cents": 0.0})
        entry["pnl_cents"] += pnl_cents

    total_pnl_cents = sum(v["pnl_cents"] for v in by_symbol.values())

    # 3. Portfolio beta & beta P&L
    portfolio_beta = (
        beta_x_exposure_sum / gross_exposure_cents if gross_exposure_cents > 0 else 0.0
    )
    spy_return = fetch_spy_return(since)
    beta_pnl_cents = portfolio_beta * spy_return * gross_exposure_cents
    alpha_pnl_cents = total_pnl_cents - beta_pnl_cents

    # 4. Normalize exposure fractions
    def _normalize(d: Dict[str, float]) -> Dict[str, float]:
        if gross_exposure_cents <= 0:
            return {}
        return {k: round(v / gross_exposure_cents, 4) for k, v in d.items() if v > 0}

    exposures = {
        "by_sector": _normalize(by_sector_exposure),
        "by_strategy": _normalize(by_strategy_exposure),
        "by_asset_class": _normalize(by_asset_class_exposure),
    }

    # 5. Top contributors / detractors
    sym_rows = [
        {"symbol": s, "pnl_cents": int(round(v["pnl_cents"]))}
        for s, v in by_symbol.items()
        if v["pnl_cents"] != 0
    ]
    sym_rows.sort(key=lambda x: x["pnl_cents"], reverse=True)

    abs_total = abs(total_pnl_cents) if total_pnl_cents != 0 else 1.0

    def _pct(p: float) -> float:
        return round(p / abs_total * 100.0, 2)

    top_contributors = [
        {"symbol": r["symbol"], "pnl_cents": r["pnl_cents"], "pct_of_total": _pct(r["pnl_cents"])}
        for r in sym_rows if r["pnl_cents"] > 0
    ][:5]
    top_detractors = [
        {"symbol": r["symbol"], "pnl_cents": r["pnl_cents"], "pct_of_total": _pct(r["pnl_cents"])}
        for r in sorted(sym_rows, key=lambda x: x["pnl_cents"]) if r["pnl_cents"] < 0
    ][:5]

    return {
        "window": window_label,
        "total_pnl_cents": int(round(total_pnl_cents)),
        "beta_pnl_cents": int(round(beta_pnl_cents)),
        "alpha_pnl_cents": int(round(alpha_pnl_cents)),
        "portfolio_beta": round(portfolio_beta, 3),
        "gross_exposure_cents": int(round(gross_exposure_cents)),
        "net_exposure_cents": int(round(net_exposure_cents)),
        "exposures": exposures,
        "top_contributors": top_contributors,
        "top_detractors": top_detractors,
    }
