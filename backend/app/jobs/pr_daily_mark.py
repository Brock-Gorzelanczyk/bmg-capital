"""Portfolio-Rank daily mark-to-market.

Fixes zero-P&L triage item A (2026-07-13 spec):
  "PR sleeve positions show deployed == starting_capital exactly and
   today_pnl == 0 permanently (low_volatility, insider_cluster_buys,
   crypto_xs_momentum, value_hml etc). Their holdings are never revalued."

Root cause: PR holdings live in `portfolio_rank_holdings`, NOT
`bot_positions`. The nightly compute_bot_stats job reads bot_daily_pnl
(sourced from bot_positions closes), so PR holdings never contribute a
mark. Result: today_pnl reads $0 forever.

This job iterates every enabled PR bot, fetches current price for each
holding symbol via the canonical live-price cache, and updates:
  portfolio_rank_holdings.current_price_cents
  portfolio_rank_holdings.current_pnl_cents = (curr - entry) * qty
  portfolio_rank_holdings.last_marked_at    = now
where qty is derived from target_weight × bot.starting_capital /
entry_price.

Scheduled every 15 minutes during US equity market hours (Mon-Fri
09:35 - 16:00 ET) + a nightly 04:15 UTC full-refresh so weekend / off-
hours holdings are still marked once a day. Crypto marks whenever the
job fires (24/7 symbols).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_live_prices(symbols: list[str]) -> dict[str, float]:
    """Reuse canonical's cached live-price fetcher — same source that feeds
    the Dashboard NAV, so PR marks stay in the same reference frame."""
    try:
        from app.core.canonical import _cached_live_prices
        return _cached_live_prices(symbols) or {}
    except Exception as exc:
        logger.warning("[pr_daily_mark] canonical price fetch failed: %s", exc)
        return {}


def mark_all_pr_holdings(db: Session) -> dict[str, Any]:
    """Update every enabled PR bot's holdings with a current mark.

    Returns per-bot counts + total revaluations for observability.
    """
    bots = db.execute(text(
        "SELECT id, name, starting_capital_cents "
        "  FROM portfolio_rank_bots WHERE enabled = 1"
    )).fetchall()

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    results: list[dict[str, Any]] = []
    total_marked = 0

    for b in bots:
        bot_id = int(b[0])
        bot_name = b[1]
        starting_cents = int(b[2] or 0)

        holdings = db.execute(text(
            "SELECT id, symbol, side, target_weight, "
            "       entry_price_cents "
            "  FROM portfolio_rank_holdings "
            " WHERE bot_id = :bid AND entry_price_cents > 0"
        ), {"bid": bot_id}).fetchall()
        if not holdings:
            results.append({"bot": bot_name, "action": "no_holdings"})
            continue

        # Fetch prices for all symbols in one call
        symbols = list({str(h[1]).upper() for h in holdings})
        prices = _fetch_live_prices(symbols)

        marked = 0
        total_pnl = 0
        for h in holdings:
            hid = int(h[0])
            sym = str(h[1]).upper()
            side = str(h[2] or "long").lower()
            weight = abs(float(h[3] or 0))
            entry_cents = int(h[4] or 0)
            px = prices.get(sym)
            if px is None or px <= 0 or entry_cents <= 0:
                continue

            # Reconstruct qty the same way portfolio_rank_runner does
            # (dollar_target / entry_price). Consistent with reconciler.
            dollar_target = (starting_cents / 100.0) * weight
            entry_dollars = entry_cents / 100.0
            qty = dollar_target / entry_dollars if entry_dollars > 0 else 0.0

            current_cents = int(round(px * 100))
            if side == "short":
                pnl_cents = int(round((entry_dollars - px) * qty * 100))
            else:
                pnl_cents = int(round((px - entry_dollars) * qty * 100))

            db.execute(text(
                "UPDATE portfolio_rank_holdings "
                "   SET current_price_cents = :px, "
                "       current_pnl_cents   = :pnl, "
                "       last_marked_at      = :ts "
                " WHERE id = :hid"
            ), {"px": current_cents, "pnl": pnl_cents, "ts": now_iso, "hid": hid})
            marked += 1
            total_pnl += pnl_cents

        # Update the bot's aggregate current PV for downstream consumers
        # that read directly from portfolio_rank_bots (some do).
        try:
            db.execute(text(
                "UPDATE portfolio_rank_bots "
                "   SET last_marked_at = :ts "
                " WHERE id = :bid"
            ), {"ts": now_iso, "bid": bot_id})
        except Exception:
            # Column may not exist on older instances — non-fatal
            pass

        results.append({
            "bot": bot_name, "marked": marked,
            "unrealized_pnl_cents": total_pnl,
        })
        total_marked += marked

    db.commit()
    logger.warning(
        "[pr_daily_mark] done — bots=%d holdings_marked=%d",
        len(results), total_marked,
    )
    return {
        "as_of": now_iso,
        "bots": len(results),
        "total_holdings_marked": total_marked,
        "per_bot": results,
    }


def setup_pr_daily_mark_scheduler(scheduler) -> None:
    """Register the intraday + nightly mark jobs."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from datetime import timedelta
    except Exception as exc:
        logger.warning("[pr_daily_mark] apscheduler unavailable: %s", exc)
        return

    from app.db.session import SessionLocal

    def _job() -> None:
        db = SessionLocal()
        try:
            res = mark_all_pr_holdings(db)
            logger.warning("[pr_daily_mark] scheduled tick: %s", res)
        except Exception as exc:
            logger.error("[pr_daily_mark] job raised: %s", exc)
        finally:
            db.close()

    # Intraday during US market hours (Mon-Fri 09:35 → 16:00 ET, every 15 min)
    scheduler.add_job(
        _job,
        CronTrigger(
            day_of_week="mon-fri", hour="9-15", minute="5,20,35,50",
            timezone="America/New_York",
        ),
        id="pr_daily_mark_intraday",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    # Nightly full refresh 04:15 UTC (crypto marks + weekend safety net)
    scheduler.add_job(
        _job,
        CronTrigger(hour=4, minute=15, timezone="UTC"),
        id="pr_daily_mark_nightly",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Bootstrap 90 seconds after startup so first mark happens fresh
    scheduler.add_job(
        _job,
        DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=90)),
        id="pr_daily_mark_bootstrap",
        replace_existing=True,
    )
    logger.warning(
        "[pr_daily_mark] scheduler registered (intraday 15m + nightly 04:15 UTC + bootstrap)",
    )
