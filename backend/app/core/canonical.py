"""
Canonical computation layer for Strategy Lab.

Every endpoint that shows portfolio value, P&L, or position counts
calls these functions — no inline computation allowed.

INVARIANT (enforced by runtime assertion):
  portfolio_value = starting_capital + realized_pnl + unrealized_pnl

  realized_pnl  = SUM(qty × (exit_fill_price - entry_avg_cost) - fees)
                  from bot_trade JOIN bot_position (sell-side trades only)

  unrealized_pnl = SUM(qty × (current_market_price - entry_avg_cost))
                   from bot_position WHERE closed_at IS NULL
                   — uses 0 when live prices are not available

ZERO-TRADE RULE:
  If bot_trade has no rows AND bot_position has no open rows for a bot:
    portfolio_value = starting_capital (exactly)
    today_pnl = 0, return_30d_pct = 0, all_time_return_pct = 0

BotDailyPnL is NOT used for portfolio value or return calculations.
It exists for the audit log and cron digests only.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta, datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+ stdlib
    _FUND_TZ = ZoneInfo("America/Chicago")
except Exception:
    # Extremely defensive — if zoneinfo is unavailable, fall back to UTC.
    # Every deployment target (Railway Python 3.11) has zoneinfo natively.
    _FUND_TZ = timezone.utc


def _fund_today() -> date:
    """Return today's date anchored to America/Chicago midnight.

    2026-07-02 Brock ask: "today" on the leaderboard was rolling over at UTC
    midnight (= 7 PM CDT the prior day). For a Milwaukee user looking at
    positions moved during the workday, everything before UTC midnight got
    counted as "yesterday's P&L" — showing "+$0 today" for bots that had
    actually earned all day.
    """
    return datetime.now(_FUND_TZ).date()


def _fund_date(dt) -> Optional[date]:
    """Convert a naive-UTC or aware datetime to America/Chicago calendar date.

    Trade / signal timestamps are stored as naive UTC in the DB. Comparing
    `t.ts.date()` against `_fund_today()` would slice at UTC midnight, not
    Milwaukee midnight — same bug that made the leaderboard TODAY column
    show +$0 for most bots. Convert to fund tz before extracting the date.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_FUND_TZ).date()

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Live price cache ──────────────────────────────────────────────────────────
import time as _time

_PRICE_CACHE: dict[str, tuple[float, float]] = {}  # symbol → (price, monotonic_ts)
_PRICE_CACHE_TTL = 60.0  # seconds — 1 quote per symbol per minute is enough


def _cached_live_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch live prices via fetch_live_prices with a 60 s in-memory cache.

    Never raises — returns an empty dict on any error so callers can fall back
    to showing 0 unrealized P&L rather than crashing.
    """
    if not symbols:
        return {}
    try:
        from app.services.live_prices import fetch_live_prices
        now = _time.monotonic()
        stale = [s for s in symbols if s not in _PRICE_CACHE or now - _PRICE_CACHE[s][1] > _PRICE_CACHE_TTL]
        if stale:
            fresh = fetch_live_prices(stale)
            for sym, price in fresh.items():
                _PRICE_CACHE[sym] = (price, now)
        return {s: _PRICE_CACHE[s][0] for s in symbols if s in _PRICE_CACHE}
    except Exception as exc:
        logger.warning("[canonical] live price fetch failed (non-fatal): %s", exc)
        return {}


def _option_unrealized_cents(pos, current_mark_cents: Optional[int], pos_side_map: dict) -> int:
    """Unrealized P&L (cents) for one open option position.

    Formula:
      long:  (current_mark - entry_premium) × contracts × 100
      short: (entry_premium - current_mark) × contracts × 100

    where avg_cost_cents is the entry premium per share in cents, qty is the
    contract count, and the ×100 multiplier converts per-share to per-contract
    (US equity options = 100 shares per contract).

    Returns 0 when:
      - no live mark (fetch failed / illiquid bid=ask=0 / composite contract)
      - missing entry or qty
    """
    if current_mark_cents is None:
        return 0
    entry = pos.avg_cost_cents
    qty = pos.qty
    if not entry or not qty:
        return 0
    contracts = float(qty)
    is_short = pos_side_map.get(pos.id, "long") == "short"
    if is_short:
        return int((entry - current_mark_cents) * contracts * 100)
    return int((current_mark_cents - entry) * contracts * 100)


# ── Display names (single source of truth) ────────────────────────────────────

DISPLAY_NAMES: dict[str, str] = {
    "stock_swing":                  "Stock Swing",
    "stock_day":                    "Stock Day",
    "stock_lt":                     "Stock Long-Term",
    "crypto_swing":                 "Crypto Swing",
    "crypto_day":                   "Crypto Day",
    "crypto_lt":                    "Crypto Long-Term",
    "crypto_onchain":               "Crypto Onchain",
    "crypto_quant_aggressive":      "Quant Aggressive",
    "crypto_quant_scalper":         "Quant Scalper",
    "crypto_quant_mean_reversion":  "Quant Mean Reversion",
    "crypto_meanrev_2163":          "Mean Rev 2163",
    # 2026-06-30: was "Equity Income" / "Equity Directional" — caused user
    # confusion on /strategy homepage where the dedicated leaderboard already
    # showed "Options Income" / "Options Directional". Renamed for consistency.
    "options_income":               "Options Income",
    "options_directional":          "Options Directional",
}


def display_name(profile_name: str) -> str:
    return DISPLAY_NAMES.get(
        profile_name,
        profile_name.replace("_", " ").title(),
    )


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class BotSnapshot:
    allocation_id: int
    profile_name: str
    display_name: str
    asset_class: str
    enabled: bool

    starting_capital_cents: int
    portfolio_value_cents: int
    today_pnl_cents: int
    today_pnl_pct: float
    realized_pnl_cents: int      # all-time cumulative realized
    unrealized_pnl_cents: int    # latest unrealized
    all_time_return_pct: float
    return_30d_pct: float

    open_positions_count: int
    watchlist_count: int
    sharpe_30d: Optional[float]

    # win_rate: fraction (0–1) of closed trades with positive realized PnL.
    # Computed from BotTrade sell/close/cover fills, same source as realized_pnl_cents.
    # None when there are no closed trades yet.
    win_rate: Optional[float] = None
    win_count: int = 0
    loss_count: int = 0

    capital_cents_within_portfolio: int = 0  # allocation within its portfolio

    # Capital currently deployed in open positions (entry-cost notional).
    # Matches the "deployed" definition used by /portfolio/allocation-live so
    # downstream UI can show "X% of $Y deployed" without a second round trip.
    deployed_cents: int = 0

    open_positions: list = field(default_factory=list)  # [{id, symbol, qty, avg_cost, ...}]
    equity_curve: list = field(default_factory=list)    # [{date, value_cents}]


@dataclass
class PortfolioSnapshot:
    portfolio_id: int
    name: str
    asset_class: str
    emoji: str
    color_hex: str

    starting_capital_cents: int
    portfolio_value_cents: int
    today_pnl_cents: int
    today_pnl_pct: float
    realized_pnl_cents: int
    unrealized_pnl_cents: int
    all_time_return_pct: float
    return_30d_pct: float

    open_positions_count: int
    watchlist_count: int
    bots_active: int
    bots_total: int

    bots: list = field(default_factory=list)  # list[BotSnapshot]
    equity_curve: list = field(default_factory=list)


# ── Bot-level computation ─────────────────────────────────────────────────────

def compute_bot_snapshot(alloc, profile, db: Session) -> BotSnapshot:
    """
    Single canonical computation for one bot allocation.

    INVARIANT: portfolio_value = starting_capital + realized_pnl + unrealized_pnl
      realized_pnl  — from bot_trade (sell-side fills vs position avg_cost)
      unrealized_pnl — from bot_position open rows (0 if no live price)

    BotDailyPnL is NOT read here. Zero trades → exactly starting_capital.
    """
    from app.db.models.bots import BotTrade, BotPosition, BotWatchlist, BotDailyPnL

    # America/Chicago-anchored day boundary. The prior version used
    # `date.today()` which on Railway resolves to UTC and would slice at
    # UTC midnight (= 7 PM Milwaukee the prior day), incorrectly attributing
    # afternoon-Milwaukee P&L to "yesterday."
    today = _fund_today()
    thirty_days_ago = today - timedelta(days=30)

    # ── Starting capital ──────────────────────────────────────────────────────
    starting_capital_cents = int(alloc.starting_capital_cents or alloc.capital_cents_within_portfolio or 0)
    # inception_capital_cents (added in m023) is the ORIGINAL seed capital
    # for this bot, preserved across capital adjustments. Used as the
    # denominator for all_time_return so leaderboard P&L history doesn't
    # get silently recomputed when starting_capital_cents changes (clean-
    # slate restart etc.). Falls back to starting_capital_cents on older
    # rows where the column wasn't populated.
    inception_capital_cents = int(
        getattr(alloc, "inception_capital_cents", None)
        or starting_capital_cents
    )

    # ── All positions (open + closed) for avg_cost lookup ────────────────────
    all_positions = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id == alloc.id)
        .all()
    )
    pos_cost_map: dict[int, float] = {p.id: p.avg_cost_cents for p in all_positions}
    pos_side_map: dict[int, str] = {p.id: getattr(p, "side", "long") or "long" for p in all_positions}

    # ── All trades (excluding quarantined) ───────────────────────────────────
    all_trades = (
        db.query(BotTrade)
        .filter(
            BotTrade.allocation_id == alloc.id,
            BotTrade.quarantined_at.is_(None),
        )
        .order_by(BotTrade.ts)
        .all()
    )

    # ── Realized PnL ─────────────────────────────────────────────────────────
    # Long exits:  side="sell"|"close"  — PnL = (exit - entry) × qty
    # Short exits: side="cover"         — PnL = (entry - exit) × qty
    realized_pnl_cents = 0
    today_realized_cents = 0
    realized_30d_cents = 0
    win_count = 0
    loss_count = 0

    # Fallback avg_cost by symbol: last buy/short-entry price for trades without position_id
    buy_price_by_symbol: dict[str, float] = {}
    for t in all_trades:
        if t.side.lower() in ("buy", "open", "short"):
            buy_price_by_symbol[t.symbol] = t.fill_price_cents

    for t in all_trades:
        side_lower = t.side.lower()
        if side_lower not in ("sell", "close", "cover"):
            continue
        avg_cost = pos_cost_map.get(t.position_id) if t.position_id else None
        if avg_cost is None:
            avg_cost = buy_price_by_symbol.get(t.symbol, t.fill_price_cents)
        # "cover" closes a short: profit when exit price < entry price
        if side_lower == "cover":
            fill_pnl = int((avg_cost - t.fill_price_cents) * t.qty) - int(t.fees_cents or 0)
        else:
            fill_pnl = int((t.fill_price_cents - avg_cost) * t.qty) - int(t.fees_cents or 0)
        realized_pnl_cents += fill_pnl
        if fill_pnl > 0:
            win_count += 1
        elif fill_pnl < 0:
            loss_count += 1
        # fill_pnl == 0 is a scratch — neither win nor loss
        # Convert trade timestamp (naive UTC) → America/Chicago date so a
        # trade at 22:00 UTC (5 PM CDT) buckets to the correct Milwaukee day
        # instead of getting split across "yesterday" (UTC-early) and "today"
        # (UTC-late).
        trade_date = _fund_date(t.ts) if hasattr(t.ts, "date") else t.ts
        if trade_date == today:
            today_realized_cents += fill_pnl
        if trade_date >= thirty_days_ago:
            realized_30d_cents += fill_pnl

    total_closed = win_count + loss_count
    win_rate = (win_count / total_closed) if total_closed > 0 else None

    # ── Open positions ────────────────────────────────────────────────────────
    open_pos_display = [p for p in all_positions if p.closed_at is None]
    # Canonical "open position" = not closed AND not quarantined.
    # open_pos_rows is used for ALL counts so portfolio matches bot-health.
    open_pos_rows = [p for p in open_pos_display if not p.quarantined_at]

    # 2026-07-02: defensive filter for phantom equity-style positions on
    # options bots. options_income was showing +$76k unrealized fund gain
    # despite zero realized trades and no legitimate open contracts. Root
    # cause: legacy BotPosition rows exist with option_type=NULL but a
    # non-OCC symbol (residue from m033_close_options_bot_equity_violations
    # that missed a subset). canonical's equity_positions filter picks them
    # up and multiplies avg_cost_cents (per-share OPTION premium in cents,
    # ~350 for a $3.50 strike) by live equity price (~$300/share × 100 =
    # 30000 cents), producing tens of thousands in phantom unrealized.
    #
    # Fix: on options-class bots, exclude any position without a proper
    # option_type. Log the count so we can clean up the underlying rows
    # in a follow-up migration.
    _asset_class = (getattr(profile, "asset_class", "") or "").lower() if profile else ""
    if _asset_class == "options":
        _pre = len(open_pos_rows)
        open_pos_rows = [p for p in open_pos_rows if p.option_type is not None]
        _dropped = _pre - len(open_pos_rows)
        if _dropped:
            logger.warning(
                "[canonical] filtered %d phantom equity-style positions on "
                "options bot %s (option_type=NULL, likely legacy pre-m033 rows)",
                _dropped, getattr(profile, "name", "?"),
            )

    # ── Deployed capital (entry-cost notional) ────────────────────────────────
    # Sum of qty × avg_cost across open positions. Equities: dollars-at-cost.
    # Options: premium × contracts × 100 (per-share entry × contract multiplier).
    # Mirrors the definition used by /api/portfolio/allocation-live so the
    # leaderboard "deployed %" and the deployment summary widget agree.
    deployed_cents = 0
    for p in open_pos_rows:
        if not p.avg_cost_cents or not p.qty:
            continue
        if p.option_type is not None:
            contracts = float(p.qty)
            deployed_cents += int(p.avg_cost_cents * contracts * 100)
        else:
            deployed_cents += int(p.avg_cost_cents * p.qty)

    # ── Unrealized PnL from live prices ──────────────────────────────────────
    # Split: equities/crypto use spot-price feeds; options use option-quote feed.
    equity_positions = [p for p in open_pos_rows if p.option_type is None]
    option_positions = [p for p in open_pos_rows if p.option_type is not None]

    symbols_needed = list({p.symbol for p in equity_positions})
    live_prices = _cached_live_prices(symbols_needed)

    # Fetch live option marks (60s cached) for open option positions.
    option_marks_cents: dict[int, Optional[int]] = {}
    if option_positions:
        try:
            from app.services.option_marks import occ_for_position, fetch_option_marks_cents
            occ_by_pos: dict[int, str] = {}
            for p in option_positions:
                occ = occ_for_position(p)
                if occ:
                    occ_by_pos[p.id] = occ
                else:
                    logger.info(
                        "options:mtm:composite symbol=%s type=%s pos_id=%d (no single-leg OCC)",
                        p.symbol, p.option_type, p.id,
                    )
            mark_by_occ = fetch_option_marks_cents(list(set(occ_by_pos.values())))
            option_marks_cents = {pid: mark_by_occ.get(occ) for pid, occ in occ_by_pos.items()}
        except Exception as exc:
            logger.warning("[canonical] option mark fetch failed (non-fatal): %s", exc)

    unrealized_pnl_cents = 0
    for p in equity_positions:
        price = live_prices.get(p.symbol)
        if price and p.avg_cost_cents and p.qty:
            is_short = pos_side_map.get(p.id, "long") == "short"
            if is_short:
                unrealized_pnl_cents += int((p.avg_cost_cents - price * 100) * p.qty)
            else:
                unrealized_pnl_cents += int((price * 100 - p.avg_cost_cents) * p.qty)

    for p in option_positions:
        mark_cents = option_marks_cents.get(p.id)
        unrealized_pnl_cents += _option_unrealized_cents(p, mark_cents, pos_side_map)

    # ── Portfolio value (the invariant) ──────────────────────────────────────
    portfolio_value_cents = starting_capital_cents + realized_pnl_cents + unrealized_pnl_cents

    # ── Today P&L ────────────────────────────────────────────────────────────
    # 2026-07-02 v2 (Brock feedback): the v1 fix (portfolio_value_eod_cents
    # baseline) worked when a yesterday snapshot existed, but silently fell
    # back to `today_realized_cents` for two big classes of bots:
    #
    #   1. New bots seeded today (m052/m053 batch — all 8 new bots): no prior
    #      BotDailyPnL row exists yet, so fallback fires → shows +$0 today
    #      even when the bot earned +$329 all-time (all of which IS today).
    #   2. Older bots where the nightly rollup skipped a day, or where the
    #      `portfolio_value_eod_cents` column wasn't populated: same +$0.
    #
    # New three-tier logic:
    #   (a) yesterday_snapshot has portfolio_value_eod_cents:
    #         today_pnl = pv_now - pv_eod_yesterday   (best — includes unrealized)
    #   (b) yesterday_snapshot exists but eod_pv missing:
    #         today_pnl = today_realized + (unrealized_now - unrealized_yesterday)
    #         (uses BotDailyPnL.unrealized_cents column that IS populated)
    #   (c) no prior BotDailyPnL row at all (brand-new bot):
    #         today_pnl = realized_pnl_cents + unrealized_pnl_cents
    #         (all-time == today because there was no yesterday)
    #
    # Final fallback: today_realized_cents (very rare — only if the query
    # itself fails).
    today_pnl_cents = today_realized_cents  # last-resort fallback
    try:
        _yday_snap = (
            db.query(BotDailyPnL)
            .filter(
                BotDailyPnL.allocation_id == alloc.id,
                BotDailyPnL.date < today,
            )
            .order_by(BotDailyPnL.date.desc())
            .first()
        )
        if _yday_snap is None:
            # Case (c): brand-new bot with no prior snapshot. All-time = today.
            today_pnl_cents = realized_pnl_cents + unrealized_pnl_cents
        elif _yday_snap.portfolio_value_eod_cents is not None:
            # Case (a): full snapshot available.
            today_pnl_cents = portfolio_value_cents - int(_yday_snap.portfolio_value_eod_cents)
        else:
            # Case (b): partial snapshot, use unrealized delta.
            _yday_unreal = int(_yday_snap.unrealized_cents or 0)
            today_pnl_cents = today_realized_cents + (unrealized_pnl_cents - _yday_unreal)
    except Exception:
        pass  # keep the today_realized_cents fallback
    yesterday_value = portfolio_value_cents - today_pnl_cents
    today_pnl_pct = round(today_pnl_cents / yesterday_value * 100, 2) if yesterday_value > 0 else 0.0

    # ── All-time return ───────────────────────────────────────────────────────
    # 2026-06-30: SHIP 3 used SUM(bot_daily_pnl.realized_cents)/inception which
    # silently dropped any unrealized P&L from open positions. Stock Swing showed
    # 0.00% on the leaderboard while the detail page UI — which derived its number
    # from current_value — showed +0.15% on a $161 unrealized AMD position.
    # Source of truth = (portfolio_value - starting) / starting where
    # portfolio_value already includes realized + unrealized (line 344 invariant).
    # We still call get_all_time_pct so legacy callers / spec tests can read the
    # historical realized-only metric, but the user-facing all_time_return_pct
    # reflects what the user actually owns right now.
    from app.services.bot_performance import get_all_time_pct as _get_all_time_pct
    _pnl_based_pct = _get_all_time_pct(alloc.id, db)  # historical realized-only — kept for legacy callers
    if starting_capital_cents:
        all_time_return_pct = round(
            (portfolio_value_cents - starting_capital_cents) / starting_capital_cents * 100, 2
        )
    elif _pnl_based_pct != 0.0:
        # Fallback for the unusual case where starting is zero but a track record exists.
        all_time_return_pct = _pnl_based_pct
    else:
        all_time_return_pct = 0.0

    # ── 30-day return ─────────────────────────────────────────────────────────
    # 2026-07-02 (Brock feedback): the old formula was
    #   return_30d_pct = realized_30d_cents / starting_capital
    # which silently dropped unrealized P&L. For a bot created today with
    # a +$329 unrealized gain and no closed trades, the 30-day return
    # showed 0% — divergent from an all-time return that showed the same
    # +1.64%. Same defect Claude Code flagged for today_pnl_cents.
    #
    # New formula: 30d = (pv_now - pv_30_days_ago) / capital_30_days_ago
    # Case (a) — BotDailyPnL row at cutoff with portfolio_value_eod_cents:
    #             use that as the baseline
    # Case (b) — row exists, eod_pv NULL but unrealized_cents populated:
    #             return_30d = realized_since_cutoff + unrealized_delta
    # Case (c) — no snapshot at cutoff (bot is newer than 30 days OR
    #             rollup gap): 30d ≡ all_time (there was no yesterday)
    return_30d_pct = 0.0
    if starting_capital_cents:
        return_30d_baseline_cents: Optional[int] = None
        try:
            _cutoff_snap = (
                db.query(BotDailyPnL)
                .filter(
                    BotDailyPnL.allocation_id == alloc.id,
                    BotDailyPnL.date <= thirty_days_ago,
                )
                .order_by(BotDailyPnL.date.desc())
                .first()
            )
            if _cutoff_snap is None:
                # Case (c): bot younger than 30 days → 30d = all_time
                return_30d_pct = all_time_return_pct
            elif _cutoff_snap.portfolio_value_eod_cents is not None:
                # Case (a): full snapshot
                return_30d_baseline_cents = int(_cutoff_snap.portfolio_value_eod_cents)
                _delta = portfolio_value_cents - return_30d_baseline_cents
                return_30d_pct = round(_delta / return_30d_baseline_cents * 100, 2) if return_30d_baseline_cents > 0 else 0.0
            else:
                # Case (b): partial snapshot — infer via unrealized delta
                _cutoff_unreal = int(_cutoff_snap.unrealized_cents or 0)
                _30d_pnl = realized_30d_cents + (unrealized_pnl_cents - _cutoff_unreal)
                return_30d_pct = round(_30d_pnl / starting_capital_cents * 100, 2)
        except Exception:
            # Very last-resort fallback — legacy realized-only.
            return_30d_pct = round(realized_30d_cents / starting_capital_cents * 100, 2)

    # ── Sharpe: not computable without daily return series ───────────────────
    sharpe_30d: Optional[float] = None

    # ── Open position details with live mark-to-market ───────────────────────
    price_ts = datetime.now(timezone.utc).isoformat()
    open_positions = []
    for p in open_pos_display:
        cost = p.avg_cost_cents / 100 if p.avg_cost_cents else None
        qty = p.qty or 0
        _pos_short = pos_side_map.get(p.id, "long") == "short"

        if p.option_type is not None:
            # Option position: use option-quote mark, not underlying spot.
            mark_cents = option_marks_cents.get(p.id)
            if mark_cents is not None:
                mark_dollars = mark_cents / 100.0
                contracts = float(qty)
                market_val = round(mark_dollars * contracts * 100, 2)
                pnl_cents = _option_unrealized_cents(p, mark_cents, pos_side_map)
                unreal = round(pnl_cents / 100.0, 2)
                cost_basis_cents = (p.avg_cost_cents or 0) * contracts * 100
                unreal_pct = round(pnl_cents / cost_basis_cents * 100, 2) if cost_basis_cents > 0 else None
                cur_price = round(mark_dollars, 4)
                cur_ts = price_ts
            else:
                market_val = None
                unreal = None
                unreal_pct = None
                cur_price = None
                cur_ts = None
        else:
            price = live_prices.get(p.symbol)
            market_val = round(price * qty, 2) if price and qty else None
            if price and cost:
                unreal = round((cost - price) * qty, 2) if _pos_short else round((price - cost) * qty, 2)
                unreal_pct = round((cost - price) / cost * 100, 2) if _pos_short else round((price - cost) / cost * 100, 2)
            else:
                unreal = None
                unreal_pct = None
            cur_price = price
            cur_ts = price_ts if price else None

        open_positions.append({
            "id": p.id,
            "symbol": p.symbol,
            "qty": qty,
            "avg_cost_cents": p.avg_cost_cents,
            "avg_cost": round(cost, 2) if cost else None,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "is_paper": p.is_paper,
            "current_price": cur_price,
            "current_price_at": cur_ts,
            "market_value": market_val,
            "unrealized_pnl": unreal,
            "unrealized_pnl_pct": unreal_pct,
        })

    # ── Watchlist count ──────────────────────────────────────────────────────
    watchlist_count = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id == alloc.profile_id,
            BotWatchlist.status.in_(["watching", "pending_entry", "active"]),
        )
        .count()
    )

    # Equity curve: built from sell-side trades, bucketed by date
    equity_curve: list = []
    if all_trades:
        daily_pnl: dict[str, int] = {}
        _buy_price_by_sym: dict[str, float] = {}
        for t in all_trades:
            if t.side.lower() in ("buy", "open", "short"):
                _buy_price_by_sym[t.symbol] = t.fill_price_cents
        for t in all_trades:
            s = t.side.lower()
            if s not in ("sell", "close", "cover"):
                continue
            avg = pos_cost_map.get(t.position_id) if t.position_id else None
            if avg is None:
                avg = _buy_price_by_sym.get(t.symbol, t.fill_price_cents)
            if s == "cover":
                pnl = int((avg - t.fill_price_cents) * t.qty) - int(t.fees_cents or 0)
            else:
                pnl = int((t.fill_price_cents - avg) * t.qty) - int(t.fees_cents or 0)
            d_key = (t.ts.date() if hasattr(t.ts, "date") else t.ts).isoformat()
            daily_pnl[d_key] = daily_pnl.get(d_key, 0) + pnl
        running = starting_capital_cents
        for d_key in sorted(daily_pnl):
            running += daily_pnl[d_key]
            equity_curve.append({"date": d_key, "portfolio": round(running / 100, 2), "benchmark": 0})

    capital_within = int(alloc.capital_cents_within_portfolio or 0)

    return BotSnapshot(
        allocation_id=alloc.id,
        profile_name=profile.name,
        display_name=display_name(profile.name),
        asset_class=profile.asset_class,
        enabled=bool(alloc.enabled),
        starting_capital_cents=starting_capital_cents,
        portfolio_value_cents=portfolio_value_cents,
        today_pnl_cents=today_pnl_cents,
        today_pnl_pct=today_pnl_pct,
        realized_pnl_cents=realized_pnl_cents,
        unrealized_pnl_cents=unrealized_pnl_cents,
        all_time_return_pct=all_time_return_pct,
        return_30d_pct=return_30d_pct,
        open_positions_count=len(open_pos_rows),
        watchlist_count=watchlist_count,
        sharpe_30d=sharpe_30d,
        win_rate=win_rate,
        win_count=win_count,
        loss_count=loss_count,
        capital_cents_within_portfolio=capital_within,
        deployed_cents=deployed_cents,
        open_positions=open_positions,
        equity_curve=equity_curve,
    )


# ── Portfolio-level computation ───────────────────────────────────────────────

def compute_portfolio_snapshot(
    port, allocs_with_profiles: list[tuple], db: Session
) -> PortfolioSnapshot:
    """
    Canonical computation for one StrategyPortfolio.
    allocs_with_profiles: list of (BotAllocation, BotProfile) tuples for this portfolio.

    SELF-CONSISTENCY (Option A):
      portfolio_value_cents     = SUM(bot.portfolio_value_cents)
      starting_capital_cents    = SUM(bot.starting_capital_cents)
      portfolio_value           = starting + realized + unrealized  (still holds)

    The portfolio row's own starting_capital_cents column is informational only
    and can drift from the sum of its allocations (e.g. a new bot is added
    without updating the parent). Trusting the children keeps the rollup
    consistent with bot-detail pages and eliminates the discrepancy log.
    """
    bot_snapshots = [compute_bot_snapshot(alloc, profile, db) for alloc, profile in allocs_with_profiles]

    realized_pnl_cents = sum(s.realized_pnl_cents for s in bot_snapshots)
    unrealized_pnl_cents = sum(s.unrealized_pnl_cents for s in bot_snapshots)
    today_pnl_cents = sum(s.today_pnl_cents for s in bot_snapshots)
    open_positions_count = sum(s.open_positions_count for s in bot_snapshots)
    watchlist_count = sum(s.watchlist_count for s in bot_snapshots)
    bots_active = sum(1 for s in bot_snapshots if s.enabled)

    # Derive starting + value from the children so they always reconcile.
    # Fallback to port.starting_capital_cents when there are no allocations.
    bot_starting_sum = sum(s.starting_capital_cents for s in bot_snapshots)
    starting_capital_cents = bot_starting_sum if bot_snapshots else int(port.starting_capital_cents or 0)
    portfolio_value_cents = sum(s.portfolio_value_cents for s in bot_snapshots) if bot_snapshots else starting_capital_cents

    # Surface drift between the StrategyPortfolio row and its allocations so
    # data ops can reconcile, but do not let it change the reported value.
    port_starting_row = int(port.starting_capital_cents or 0)
    if bot_snapshots and abs(bot_starting_sum - port_starting_row) > 10_000:
        logger.info(
            "Portfolio %d (%s) starting_capital drift: row=%d sum(allocations)=%d diff=%d (using allocation sum)",
            port.id, port.name, port_starting_row, bot_starting_sum, bot_starting_sum - port_starting_row,
        )

    yesterday_value = portfolio_value_cents - today_pnl_cents
    today_pnl_pct = round(today_pnl_cents / yesterday_value * 100, 2) if yesterday_value > 0 else 0.0

    # Portfolio-level all-time.
    # 2026-06-30: same SHIP 3 bug as compute_bot_snapshot — summing
    # SUM(realized)/SUM(inception) silently dropped unrealized P&L from open
    # positions. Source of truth = (portfolio_value - starting) / starting where
    # portfolio_value rolls up each child bot's snapshot (which already includes
    # realized + unrealized). The get_all_time_pct call is kept so legacy callers
    # / spec tests can still read the realized-only historical metric.
    from app.services.bot_performance import get_all_time_pct as _get_all_time_pct
    bot_inception_sum = sum(
        int(getattr(alloc, "inception_capital_cents", None) or alloc.starting_capital_cents or 0)
        for alloc, _profile in allocs_with_profiles
    )
    inception_denom = bot_inception_sum or starting_capital_cents

    # Sum per-bot realized PnL (historical only) — preserved for legacy callers.
    total_pnl_based_cents = 0
    for alloc, _profile in allocs_with_profiles:
        alloc_inception = int(
            getattr(alloc, "inception_capital_cents", None) or alloc.starting_capital_cents or 0
        )
        alloc_pct = _get_all_time_pct(alloc.id, db)
        if alloc_inception:
            total_pnl_based_cents += int(alloc_pct / 100 * alloc_inception)

    if starting_capital_cents:
        all_time_return_pct = round(
            (portfolio_value_cents - starting_capital_cents) / starting_capital_cents * 100, 2
        )
    elif inception_denom and total_pnl_based_cents != 0:
        # Fallback for portfolios with zero starting but a track record from constituents.
        all_time_return_pct = round(total_pnl_based_cents / inception_denom * 100, 2)
    else:
        all_time_return_pct = 0.0

    # 30d return: average across bots weighted by starting capital
    return_30d_pct = 0.0
    total_weight = sum(s.starting_capital_cents for s in bot_snapshots if s.starting_capital_cents)
    if total_weight:
        return_30d_pct = round(
            sum(
                s.return_30d_pct * s.starting_capital_cents
                for s in bot_snapshots
                if s.starting_capital_cents
            ) / total_weight,
            2,
        )

    return PortfolioSnapshot(
        portfolio_id=port.id,
        name=port.name,
        asset_class=port.asset_class,
        emoji=port.emoji or "",
        color_hex=port.color_hex or "#888888",
        starting_capital_cents=starting_capital_cents,
        portfolio_value_cents=portfolio_value_cents,
        today_pnl_cents=today_pnl_cents,
        today_pnl_pct=today_pnl_pct,
        realized_pnl_cents=realized_pnl_cents,
        unrealized_pnl_cents=unrealized_pnl_cents,
        all_time_return_pct=all_time_return_pct,
        return_30d_pct=return_30d_pct,
        open_positions_count=open_positions_count,
        watchlist_count=watchlist_count,
        bots_active=bots_active,
        bots_total=len(bot_snapshots),
        bots=bot_snapshots,
    )


# ── Aggregate (whole Strategy Lab) ───────────────────────────────────────────

def compute_strategy_lab_aggregate(user_id: int, db: Session) -> dict:
    """
    Aggregate across all 3 portfolios. Used by /api/strategy-lab/portfolio.
    Returns a plain dict compatible with the existing API shape.
    """
    from app.db.models.bots import StrategyPortfolio, BotAllocation, BotProfile

    portfolios = (
        db.query(StrategyPortfolio)
        .filter(StrategyPortfolio.user_id == user_id)
        .order_by(StrategyPortfolio.id)
        .all()
    )
    if not portfolios:
        return {}

    all_allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id)
        .all()
    )
    alloc_map = {a.id: a for a in all_allocs}

    profile_ids = list({a.profile_id for a in all_allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}

    # ── Per-allocation snapshots (SINGLE SOURCE OF TRUTH for totals) ──────
    # Compute once per alloc and use as the authoritative source for all
    # totals returned. Mirrors Dashboard's pattern exactly, eliminating any
    # chance of a Dashboard/Strategy-Lab split-brain on portfolio_value.
    # Allocs whose profile is missing or whose snapshot raises fall back to
    # starting_capital so we never silently drop a real dollar.
    bot_snap_by_alloc: dict[int, BotSnapshot] = {}
    fallback_value_by_alloc: dict[int, int] = {}
    fallback_starting_by_alloc: dict[int, int] = {}
    for a in all_allocs:
        prof = profile_map.get(a.profile_id)
        if prof is None:
            fallback_value_by_alloc[a.id] = int(a.starting_capital_cents or 0)
            fallback_starting_by_alloc[a.id] = int(a.starting_capital_cents or 0)
            continue
        try:
            bot_snap_by_alloc[a.id] = compute_bot_snapshot(a, prof, db)
        except Exception as exc:
            logger.warning(
                "[canonical] compute_bot_snapshot failed for alloc %d: %s — falling back to starting",
                a.id, exc,
            )
            fallback_value_by_alloc[a.id] = int(a.starting_capital_cents or 0)
            fallback_starting_by_alloc[a.id] = int(a.starting_capital_cents or 0)

    total_value = (
        sum(s.portfolio_value_cents or 0 for s in bot_snap_by_alloc.values())
        + sum(fallback_value_by_alloc.values())
    )
    total_starting = (
        sum(s.starting_capital_cents or 0 for s in bot_snap_by_alloc.values())
        + sum(fallback_starting_by_alloc.values())
    )
    total_today_pnl = sum(s.today_pnl_cents or 0 for s in bot_snap_by_alloc.values())
    total_open_positions = sum(s.open_positions_count or 0 for s in bot_snap_by_alloc.values())

    # ── Per-portfolio snapshots (response breakdown only) ──────────────────
    portfolio_snapshots = []
    accounted_alloc_ids: set[int] = set()
    for port in portfolios:
        port_allocs = [a for a in all_allocs if a.portfolio_id == port.id]
        pairs = [(a, profile_map[a.profile_id]) for a in port_allocs if a.profile_id in profile_map]
        accounted_alloc_ids.update(a.id for a, _ in pairs)
        portfolio_snapshots.append(compute_portfolio_snapshot(port, pairs, db))

    total_watchlist = sum(s.watchlist_count for s in portfolio_snapshots)

    # Diagnostic: surface any drift between the per-alloc sum (authoritative)
    # and the portfolio_snapshots + orphan path. Useful for spotting cases
    # where _ensure_portfolios_for_user binds an alloc into a portfolio with
    # a sleeve mismatch, etc.
    orphan_alloc_ids = [a.id for a in all_allocs if a.id not in accounted_alloc_ids]
    orphan_value_diag = sum(
        (bot_snap_by_alloc[aid].portfolio_value_cents or 0) if aid in bot_snap_by_alloc
        else fallback_value_by_alloc.get(aid, 0)
        for aid in orphan_alloc_ids
    )
    portfolio_sum_diag = sum(s.portfolio_value_cents for s in portfolio_snapshots)
    diag_total = portfolio_sum_diag + orphan_value_diag
    if abs(total_value - diag_total) > 100:  # > $1 drift
        logger.error(
            "[canonical] split-brain drift: per_alloc=%d portfolio_sum=%d orphan=%d diag_total=%d diff=%d allocs=%d",
            total_value, portfolio_sum_diag, orphan_value_diag, diag_total,
            total_value - diag_total, len(all_allocs),
        )

    # SHIP 3: fleet all-time % = SUM(bot_daily_pnl.realized_cents) / SUM(inception_capital_cents)
    # Replaces (total_value - total_starting) / total_starting which re-zeroed history
    # whenever starting_capital_cents changed post-reset (known-issues #10).
    _fleet_alloc_ids = [a.id for a in all_allocs]
    if _fleet_alloc_ids:
        _fleet_pnl_row = db.execute(
            text(
                "SELECT COALESCE(SUM(p.realized_cents), 0), "
                "       COALESCE(SUM(COALESCE(a.inception_capital_cents, a.starting_capital_cents, 0)), 0) "
                "FROM bot_allocations a "
                "LEFT JOIN bot_daily_pnl p ON p.allocation_id = a.id "
                "  AND (p.note IS NULL OR p.note != 'track_reset_marker') "
                "WHERE a.id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": _fleet_alloc_ids},
        ).fetchone()
        _fleet_realized = int(_fleet_pnl_row[0] or 0)
        _fleet_inception = int(_fleet_pnl_row[1] or 0)
        all_time_pct = round(_fleet_realized / _fleet_inception * 100, 2) if _fleet_inception else 0.0
    else:
        all_time_pct = 0.0
    yesterday_total = total_value - total_today_pnl
    today_pct = round(total_today_pnl / yesterday_total * 100, 2) if yesterday_total > 0 else 0.0

    # 30d return: weighted average across portfolios
    return_30d_pct = 0.0
    if total_starting:
        return_30d_pct = round(
            sum(s.return_30d_pct * s.starting_capital_cents for s in portfolio_snapshots) / total_starting, 2
        )

    # Leaderboard: one entry per bot across all portfolios
    # 2026-06-30: added all_time_return_pct, enabled, paused_reason, and
    # unrealized_pnl_cents so the /strategy homepage shows the same numbers as
    # the dedicated /strategy/leaderboard. Both surfaces now derive from the
    # canonical snapshot. Sort by all_time_return_pct so the winner ranks first.
    # 2026-06-30 (evening): ALSO include orphan allocations (bots not bound to
    # any StrategyPortfolio row — e.g. cash_floor) so the homepage leaderboard
    # matches the dedicated /api/leaderboard/strategies which iterates every
    # user allocation. Without this, cash_floor's $100k silently disappeared
    # from the homepage sleeve-sum + leaderboard total, making the fund
    # appear $100k lighter than it actually is.
    # 2026-07-02: bulk-count signals + trades in last 24h per allocation.
    # Two grouped queries (not per-bot loops) so this scales to 30+ bots
    # without turning the leaderboard endpoint into an N+1.
    from datetime import timedelta as _td
    from app.db.models.bots import BotSignal as _BSig, BotTrade as _BTrd
    _cut_24h = datetime.now(timezone.utc) - _td(hours=24)
    signals_24h_by_alloc: dict[int, int] = {}
    trades_24h_by_alloc: dict[int, int] = {}
    try:
        for aid, cnt in db.execute(
            text(
                "SELECT allocation_id, COUNT(*) FROM bot_signals "
                "WHERE ts >= :cut GROUP BY allocation_id"
            ),
            {"cut": _cut_24h.isoformat()},
        ).fetchall():
            signals_24h_by_alloc[int(aid)] = int(cnt)
        for aid, cnt in db.execute(
            text(
                "SELECT allocation_id, COUNT(*) FROM bot_trades "
                "WHERE ts >= :cut AND quarantined_at IS NULL "
                "GROUP BY allocation_id"
            ),
            {"cut": _cut_24h.isoformat()},
        ).fetchall():
            trades_24h_by_alloc[int(aid)] = int(cnt)
    except Exception as _cnt_exc:
        logger.warning("[leaderboard] 24h signal/trade count query failed: %s", _cnt_exc)

    leaderboard = []
    seen_alloc_ids: set[int] = set()
    for port_snap in portfolio_snapshots:
        for bot in port_snap.bots:
            leaderboard.append({
                "rank": 0,
                "profile": bot.profile_name,
                "name": bot.display_name,
                "enabled": bot.enabled,
                "return_30d_pct": bot.return_30d_pct,
                "all_time_return_pct": bot.all_time_return_pct,
                "today_pnl_cents": bot.today_pnl_cents,
                "watchlist_count": bot.watchlist_count,
                "portfolio_value_cents": bot.portfolio_value_cents,
                "realized_pnl_cents": bot.realized_pnl_cents,
                "unrealized_pnl_cents": bot.unrealized_pnl_cents,
                # Capital deployed in open positions (entry-cost notional).
                # Used by Strategy Lab + Dashboard to show "X% of $Y deployed".
                "deployed_cents": bot.deployed_cents,
                "starting_capital_cents": bot.starting_capital_cents,
                # 24h activity — surfaces signal→fill conversion on leaderboard.
                # Bots below ~30% conversion are candidates for execution
                # investigation (asset-class gate, cooldowns, missing prices).
                "signals_24h": signals_24h_by_alloc.get(bot.allocation_id, 0),
                "trades_24h":  trades_24h_by_alloc.get(bot.allocation_id, 0),
            })
            seen_alloc_ids.add(bot.allocation_id)

    # Append orphan allocations that were counted in total_value above but
    # weren't in any portfolio_snapshot.bots list. This is where cash_floor
    # lives (its allocation has no portfolio_id binding). Use the snapshot
    # if we computed one; fall back to a minimal stub built from the alloc
    # + profile so the row still appears with the correct starting capital.
    for a in all_allocs:
        if a.id in seen_alloc_ids:
            continue
        snap = bot_snap_by_alloc.get(a.id)
        prof = profile_map.get(a.profile_id)
        profile_name = prof.name if prof else f"alloc_{a.id}"
        # Fall back to title-cased slug so the leaderboard never shows alloc_N.
        display = DISPLAY_NAMES.get(profile_name) or profile_name.replace("_", " ").title()
        if snap:
            leaderboard.append({
                "rank": 0,
                "profile": profile_name,
                "name": snap.display_name or display,
                "enabled": snap.enabled,
                "return_30d_pct": snap.return_30d_pct,
                "all_time_return_pct": snap.all_time_return_pct,
                "today_pnl_cents": snap.today_pnl_cents,
                "watchlist_count": snap.watchlist_count,
                "portfolio_value_cents": snap.portfolio_value_cents,
                "realized_pnl_cents": snap.realized_pnl_cents,
                "unrealized_pnl_cents": snap.unrealized_pnl_cents,
                "deployed_cents": snap.deployed_cents,
                "starting_capital_cents": snap.starting_capital_cents,
                "signals_24h": signals_24h_by_alloc.get(a.id, 0),
                "trades_24h":  trades_24h_by_alloc.get(a.id, 0),
            })
        else:
            starting_c = int(a.starting_capital_cents or 0)
            leaderboard.append({
                "rank": 0,
                "profile": profile_name,
                "name": display,
                "enabled": bool(a.enabled),
                "return_30d_pct": 0.0,
                "all_time_return_pct": 0.0,
                "today_pnl_cents": 0,
                "watchlist_count": 0,
                "portfolio_value_cents": starting_c,
                "realized_pnl_cents": 0,
                "unrealized_pnl_cents": 0,
                "deployed_cents": 0,
                "starting_capital_cents": starting_c,
                "signals_24h": signals_24h_by_alloc.get(a.id, 0),
                "trades_24h":  trades_24h_by_alloc.get(a.id, 0),
            })
    leaderboard.sort(
        key=lambda x: (
            x["all_time_return_pct"],
            x["return_30d_pct"],
            x["realized_pnl_cents"],
            x["today_pnl_cents"],
            x["watchlist_count"],
        ),
        reverse=True,
    )
    for i, e in enumerate(leaderboard, 1):
        e["rank"] = i

    best = leaderboard[0] if leaderboard else None
    worst = leaderboard[-1] if leaderboard else None

    # Integrity check is now inline above where total_value is derived from
    # per-allocation snapshots (single source of truth). The previous block
    # logged drift between the portfolio_snapshots+orphan path and total_value
    # — that drift is now captured by the split-brain diagnostic earlier.

    # ── COMMIT 5: Canonical invariant — fleet = sleeves + cash ───────────────
    # Cash isn't separately tracked in this aggregate (capital lives inside
    # allocations as starting_capital_cents and is implicitly part of
    # portfolio_value via the invariant `value = starting + realized + unrealized`).
    # We compare fleet total_value vs the per-portfolio breakdown sum + orphan,
    # treating orphan_value_diag + (any unaccounted cash) as effective "cash".
    # > 100 cents drift → warn log so ops can investigate without breaking the API.
    sleeve_sum_cents = sum(p.get("portfolio_value_cents", 0) for p in [
        {
            "portfolio_value_cents": s.portfolio_value_cents,
        }
        for s in portfolio_snapshots
    ])
    fleet_total = total_value
    total_cash_cents = orphan_value_diag  # orphan allocations act as residual "cash"
    if abs(fleet_total - (sleeve_sum_cents + total_cash_cents)) > 100:
        logger.warning(
            "[canonical-invariant] fleet %d != sleeves %d + cash %d (drift)",
            fleet_total, sleeve_sum_cents, total_cash_cents,
        )

    return {
        "total_value_cents": total_value,
        # Alias for callers that read portfolio_value_cents at the aggregate
        # level (mirrors the per-portfolio shape). Always populated — never None.
        "portfolio_value_cents": total_value,
        "yesterday_value_cents": yesterday_total,
        "today_pnl_cents": total_today_pnl,
        "today_pnl_pct": today_pct,
        "return_30d_pct": return_30d_pct,
        "return_30d_value_cents": total_value - total_starting,
        "return_all_time_pct": all_time_pct,
        "total_open_positions": total_open_positions,
        "total_watchlist_count": total_watchlist,
        "equity_curve": [],  # kept for compatibility
        "leaderboard": leaderboard,
        "best_performer": {
            "profile": best["profile"],
            "return_30d_pct": best["return_30d_pct"],
            "all_time_return_pct": best["all_time_return_pct"],
        } if best else None,
        "worst_performer": {
            "profile": worst["profile"],
            "return_30d_pct": worst["return_30d_pct"],
            "all_time_return_pct": worst["all_time_return_pct"],
        } if worst else None,
        "portfolios": [
            {
                "id": s.portfolio_id,
                "name": s.name,
                "asset_class": s.asset_class,
                "portfolio_value_cents": s.portfolio_value_cents,
                "today_pnl_cents": s.today_pnl_cents,
                "return_30d_pct": s.return_30d_pct,
            }
            for s in portfolio_snapshots
        ],
    }


# ── get_canonical_portfolio_state — single named contract for every consumer ──

# Canonical sleeve labels. Every consumer of canonical state sees ONE of these
# five strings — never lowercase, never "equities", never "stock" (singular).
# Backend code paths that today emit "stocks"/"crypto"/etc. lowercase get
# normalized through CANONICAL_SLEEVE_LABEL_MAP below.
CANONICAL_SLEEVES = ("Stocks", "Crypto", "Options", "Quant", "Cash")
_SLEEVE_LABEL_MAP = {
    # Stocks
    "stock": "Stocks", "stocks": "Stocks", "equity": "Stocks", "equities": "Stocks",
    # Crypto
    "crypto": "Crypto", "cryptocurrency": "Crypto",
    # Options
    "option": "Options", "options": "Options",
    # Quant
    "quant": "Quant", "quantitative": "Quant",
    # Cash
    "cash": "Cash", "cash_floor": "Cash", "cash floor": "Cash",
}


def _canonicalize_sleeve(raw: str | None) -> str:
    """Normalize a raw sleeve string to one of CANONICAL_SLEEVES.

    Unknown labels fall back to "Quant" rather than raising — the canonical
    state contract returns a normalized response even when upstream data is
    dirty. Ship 7 will hard-error on unknown labels; this wrapper does not.
    """
    if not raw:
        return "Cash"
    key = str(raw).strip().lower()
    return _SLEEVE_LABEL_MAP.get(key, "Quant")


def get_canonical_portfolio_state(user_id: int, db: Session) -> dict:
    """Single canonical portfolio state. Every endpoint that needs portfolio,
    sleeve, or P&L data MUST call this function — no bypass paths.

    Returns:
        {
            "portfolio_value_cents": int,
            "sleeve_totals": {"Stocks": int, "Crypto": int, "Options": int,
                              "Quant": int, "Cash": int},
            "today_pnl_cents": int,
            "per_bot": [
                {"bot_id": str, "sleeve": str, "starting_cents": int,
                 "current_cents": int, "today_pnl_cents": int,
                 "deployed_cents": int, "deployed_pct": float}
            ],
            "last_computed_at": ISO-8601 str (UTC),
        }

    Numbers are sourced from compute_strategy_lab_aggregate — which is the
    same function Dashboard, Strategy Lab, Portfolio, and Mission Control
    already use (or will use after PART B refactors). Calling this wrapper
    guarantees byte-for-byte equality across surfaces.
    """
    agg = compute_strategy_lab_aggregate(user_id, db) or {}

    leaderboard = agg.get("leaderboard", []) or []
    portfolios = agg.get("portfolios", []) or []

    # Map portfolio_id -> canonical sleeve label.
    sleeve_by_portfolio: dict[int, str] = {
        p["id"]: _canonicalize_sleeve(p.get("asset_class")) for p in portfolios
    }

    # ── Resolve per-bot sleeve via allocation -> portfolio_id -> sleeve ─────
    from app.db.models.bots import BotAllocation, BotProfile

    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == user_id)
        .all()
    )
    profile_id_to_name: dict[int, str] = {
        p.id: p.name
        for p in db.query(BotProfile).filter(
            BotProfile.id.in_({a.profile_id for a in allocs})
        ).all()
    }
    name_to_sleeve: dict[str, str] = {}
    for a in allocs:
        name = profile_id_to_name.get(a.profile_id)
        if not name:
            continue
        # Cash floor: orphan allocation (portfolio_id IS NULL). Canonical sleeve
        # is "Cash".
        if a.portfolio_id is None or name == "cash_floor":
            name_to_sleeve[name] = "Cash"
        else:
            name_to_sleeve[name] = sleeve_by_portfolio.get(a.portfolio_id, "Quant")

    # ── Build per_bot from leaderboard + alloc lookup ──────────────────────
    per_bot: list[dict] = []
    sleeve_totals: dict[str, int] = {s: 0 for s in CANONICAL_SLEEVES}

    for entry in leaderboard:
        profile_name = entry.get("profile") or ""
        sleeve = name_to_sleeve.get(profile_name, "Quant")
        starting = int(entry.get("starting_capital_cents") or 0)
        current = int(entry.get("portfolio_value_cents") or 0)
        today_pnl = int(entry.get("today_pnl_cents") or 0)
        deployed = int(entry.get("deployed_cents") or 0)
        deployed_pct = round((deployed / current * 100.0), 2) if current > 0 else 0.0

        per_bot.append({
            "bot_id": profile_name,
            "sleeve": sleeve,
            "starting_cents": starting,
            "current_cents": current,
            "today_pnl_cents": today_pnl,
            "deployed_cents": deployed,
            "deployed_pct": deployed_pct,
        })
        sleeve_totals[sleeve] = sleeve_totals.get(sleeve, 0) + current

    portfolio_value = int(agg.get("portfolio_value_cents") or agg.get("total_value_cents") or 0)
    today_pnl = int(agg.get("today_pnl_cents") or 0)

    return {
        "portfolio_value_cents": portfolio_value,
        "sleeve_totals": sleeve_totals,
        "today_pnl_cents": today_pnl,
        "per_bot": per_bot,
        "last_computed_at": datetime.now(timezone.utc).isoformat(),
    }
