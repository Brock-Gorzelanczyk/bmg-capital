"""Time-boxed threshold experiment (2026-07-13 follow-up on 985f176d).

The composite_threshold_override: 30 change we shipped on 5 profiles
(crypto_day, stock_gap_fade, stock_momentum_breakout, stock_pead,
stock_quant_swing_growth) plus the confidence + composite relaxations
on crypto_swing and stock_swing admitted trades that the previous
default 60 composite gate would have blocked. Every admitted trade is
now tagged with `bot_trades.composite_score_at_execution` (m095).

This module:

  1. bucket_report(days=14) — for each affected bot, aggregate closed
     trades by score band {30-59, 60+} and report {trades, win_rate,
     expectancy_usd}. Powers /api/admin/threshold-experiment.

  2. auto_revert_check() — daily job. For each affected bot with ≥ 20
     closed trades in the 30-59 band and expectancy_usd < 0, log an
     action recommending revert. Does NOT automatically edit YAMLs
     (that's a code change requiring PR/deploy) — the revert candidate
     list is surfaced in the endpoint + a Discord alert for Brock to
     act on.

Affected-bot list is hard-coded to match what 985f176d + c7998b12
actually touched — trades from other bots (options_directional,
options_income, spy_iron_condor_weekly which already had prior
composite_threshold overrides) are reported for context but not part
of the auto-revert decision.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Bots whose composite gate was TIGHTER than 30 before 985f176d and were
# loosened by the fire-more push. These are the only bots subject to the
# auto-revert decision — other bots that already had thresholds ≤ 30
# (options_directional=30, options_income=30, spy_iron_condor_weekly=20)
# are shown in the report but excluded from auto-revert.
_EXPERIMENT_BOTS: dict[str, dict[str, Any]] = {
    "crypto_day":              {"prior_threshold": 60, "new_threshold": 30},
    "stock_gap_fade":          {"prior_threshold": 60, "new_threshold": 30},
    "stock_momentum_breakout": {"prior_threshold": 60, "new_threshold": 30},
    "stock_pead":              {"prior_threshold": 60, "new_threshold": 30},
    "stock_quant_swing_growth":{"prior_threshold": 60, "new_threshold": 30},
    "crypto_swing":            {"prior_threshold": 60, "new_threshold": 30},
    "stock_swing":             {"prior_threshold": 50, "new_threshold": 30},
}


def _band_stats(rows: list[dict]) -> dict[str, Any]:
    """Aggregate a list of {pnl_usd} dicts into {trades, wins, win_rate,
    avg_winner, avg_loser, expectancy_usd, total_pnl_usd}."""
    trades = len(rows)
    if trades == 0:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": None,
            "avg_winner_usd": None, "avg_loser_usd": None,
            "expectancy_usd": None, "total_pnl_usd": 0.0,
        }
    wins = [r["pnl_usd"] for r in rows if r["pnl_usd"] > 0]
    losses = [r["pnl_usd"] for r in rows if r["pnl_usd"] < 0]
    win_rate = len(wins) / trades if trades > 0 else None
    avg_winner = sum(wins) / len(wins) if wins else 0.0
    avg_loser = sum(losses) / len(losses) if losses else 0.0
    total_pnl = sum(r["pnl_usd"] for r in rows)
    expectancy = total_pnl / trades if trades > 0 else 0.0
    return {
        "trades": trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "avg_winner_usd": round(avg_winner, 2),
        "avg_loser_usd": round(avg_loser, 2),
        "expectancy_usd": round(expectancy, 3),
        "total_pnl_usd": round(total_pnl, 2),
    }


def bucket_report(db: Session, days: int = 14) -> dict[str, Any]:
    """Per-bot, per-band bucketed report.

    Query: closed round-trip trades in the last `days` days where the
    ENTRY trade has composite_score_at_execution set. Bucket by band:
      30-59 : admitted under the loosened gate; wouldn't have executed
              before 985f176d
      60+   : would have been admitted even at the old default
      NULL  : pre-experiment trades — reported but not bucketed
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Join sell/close trades to their entry trade for composite score
    # (the score was written on ENTRY, not on close). Match via position_id.
    rows = db.execute(text(
        """
        SELECT p.name                            AS bot,
               entry.composite_score_at_execution AS score,
               CASE WHEN pos.side = 'short'
                    THEN (pos.avg_cost_cents - exit.fill_price_cents)
                    ELSE (exit.fill_price_cents - pos.avg_cost_cents)
               END * pos.qty / 100.0             AS pnl_usd
          FROM bot_trades exit
          JOIN bot_positions pos ON pos.id = exit.position_id
          JOIN bot_allocations a ON a.id = exit.allocation_id
          JOIN bot_profiles p ON p.id = a.profile_id
          LEFT JOIN bot_trades entry ON entry.position_id = pos.id
             AND entry.side IN ('buy', 'short')
             AND entry.id != exit.id
         WHERE exit.side IN ('sell', 'cover', 'close')
           AND exit.quarantined_at IS NULL
           AND pos.closed_at IS NOT NULL
           AND exit.ts > pos.opened_at
           AND exit.ts >= :cut
           AND pos.avg_cost_cents > 0
        """
    ), {"cut": cutoff}).fetchall()

    per_bot: dict[str, dict[str, list]] = {}
    for r in rows:
        bot = r[0]
        score = r[1]
        pnl = float(r[2] or 0)
        per_bot.setdefault(bot, {"low": [], "high": [], "null": []})
        if score is None:
            band = "null"
        elif 30 <= score < 60:
            band = "low"
        else:
            band = "high"
        per_bot[bot][band].append({"pnl_usd": pnl})

    report = []
    revert_candidates: list[str] = []
    for bot, buckets in per_bot.items():
        low = _band_stats(buckets["low"])
        high = _band_stats(buckets["high"])
        null = _band_stats(buckets["null"])

        # Auto-revert candidate: experiment bot + >=20 low-band trades + neg expectancy
        exp_meta = _EXPERIMENT_BOTS.get(bot)
        candidate = False
        candidate_reason = None
        if exp_meta and low["trades"] >= 20 and low["expectancy_usd"] is not None and low["expectancy_usd"] < 0:
            candidate = True
            candidate_reason = (
                f"30-59 band: {low['trades']} trades, expectancy "
                f"{low['expectancy_usd']:+.3f}/trade, total {low['total_pnl_usd']:+.2f}. "
                f"Revert composite_threshold to {exp_meta['prior_threshold']}."
            )
            revert_candidates.append(bot)

        report.append({
            "bot": bot,
            "in_experiment": bot in _EXPERIMENT_BOTS,
            "band_30_59": low,
            "band_60_plus": high,
            "band_null_pre_experiment": null,
            "revert_candidate": candidate,
            "revert_reason": candidate_reason,
        })

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days_window": days,
        "experiment_bots": list(_EXPERIMENT_BOTS.keys()),
        "revert_candidates": revert_candidates,
        "per_bot": report,
    }


def auto_revert_check(db: Session, days: int = 14) -> dict[str, Any]:
    """Daily job. Runs bucket_report(days) and posts a Discord alert if any
    experiment bot has crossed the auto-revert threshold. Does NOT edit
    YAMLs — Brock reviews and merges the revert PR."""
    rep = bucket_report(db, days=days)
    if rep["revert_candidates"]:
        try:
            from app.services.discord import send_ops_alert
            fields = []
            for row in rep["per_bot"]:
                if row["bot"] in rep["revert_candidates"]:
                    lo = row["band_30_59"]
                    hi = row["band_60_plus"]
                    fields.append({
                        "name": row["bot"],
                        "value": (
                            f"30-59: n={lo['trades']} exp={lo['expectancy_usd']:+.3f} "
                            f"| 60+: n={hi['trades']} exp={hi['expectancy_usd'] or 0:+.3f}"
                        ),
                    })
            send_ops_alert(
                title="Threshold experiment — revert candidates",
                message=(
                    f"After {days}d, {len(rep['revert_candidates'])} bots show "
                    f"negative expectancy in the 30-59 band (previously blocked "
                    f"at default 60). Review and revert composite_threshold_override "
                    f"in each profile YAML."
                ),
                severity="warn",
                source="threshold_experiment",
                fields=fields[:10],
            )
        except Exception as exc:
            logger.warning("[threshold_experiment] discord alert failed: %s", exc)
    return rep


def setup_threshold_experiment_scheduler(scheduler) -> None:
    """Register daily 02:15 UTC job."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[threshold_experiment] apscheduler unavailable: %s", exc)
        return

    from app.db.session import SessionLocal

    def _job() -> None:
        db = SessionLocal()
        try:
            res = auto_revert_check(db, days=14)
            logger.warning(
                "[threshold_experiment] daily check: %d bots in experiment, %d revert candidates",
                len(res.get("experiment_bots", [])),
                len(res.get("revert_candidates", [])),
            )
        except Exception as exc:
            logger.error("[threshold_experiment] job raised: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _job,
        CronTrigger(hour=2, minute=15, timezone="UTC"),
        id="threshold_experiment_daily",
        replace_existing=True,
        max_instances=1,
    )
    logger.warning("[threshold_experiment] scheduler registered (daily 02:15 UTC)")
