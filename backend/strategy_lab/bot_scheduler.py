"""APScheduler integration for the six bot profiles.

setup_bot_scheduler(scheduler) is called from app/main.py lifespan,
after setup_monitoring_scheduler, using the same AsyncIOScheduler instance.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import pytz
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Ledger #32 §W1
from app.services.position_write_gate import check_position_pre_write  # noqa: F401

ET = pytz.timezone("America/New_York")
UTC = pytz.utc


def _run_bot_position_monitor(bot_name: str) -> None:
    """Per-bot position monitor. Cost cut 2026-08-13: skip if this bot has
    no open positions (no work to do; skips the whole DB + broker call chain).
    """
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text as _sql
        db = SessionLocal()
        try:
            row = db.execute(
                _sql(
                    "SELECT 1 FROM bot_positions bp "
                    "JOIN bot_allocations ba ON ba.id = bp.allocation_id "
                    "JOIN bot_profiles bpf ON bpf.id = ba.profile_id "
                    "WHERE bp.closed_at IS NULL AND bpf.name = :n LIMIT 1"
                ),
                {"n": bot_name},
            ).first()
        finally:
            db.close()
        if not row:
            return  # no open positions for this bot — skip
        from strategy_lab.core.position_monitor import monitor_bot_positions
        try:
            from app.services.mem_probe import probe_job
            probe_job(f"bot_pos_mon:{bot_name}", monitor_bot_positions, bot_name)
        except Exception:
            monitor_bot_positions(bot_name)
    except Exception as exc:
        logger.error("bot_position_monitor[%s] failed: %s", bot_name, exc)


# ──────────────────────────────────────────────────────────────────────────────
# COMMIT 10 — Watchlist staleness sweep (module-level so admin endpoint can call)
# ──────────────────────────────────────────────────────────────────────────────
_INCUBATING_PROFILE_NAMES = ("earnings_nlp", "quality_factor", "value_quality")


def run_watchlist_stale_sweep() -> dict:
    """Soft-remove watchlist entries older than 7 days (status → stale_removed).

    Skips incubating profiles whose allocations are intentionally inactive.
    Returns {"swept": N} on success or {"error": ...} on failure.
    """
    from app.db.session import SessionLocal as _SL
    from sqlalchemy import text as _sql
    from app.services.discord import send_ops_alert as _alert

    db = _SL()
    try:
        inc_ids_rows = db.execute(_sql(
            "SELECT id FROM bot_profiles WHERE name IN (:p0, :p1, :p2)"
        ), {
            "p0": _INCUBATING_PROFILE_NAMES[0],
            "p1": _INCUBATING_PROFILE_NAMES[1],
            "p2": _INCUBATING_PROFILE_NAMES[2],
        }).fetchall()
        inc_ids = [r[0] for r in inc_ids_rows]
        inc_clause = ""
        params: dict = {}
        if inc_ids:
            placeholders = ",".join(f":i{i}" for i in range(len(inc_ids)))
            inc_clause = f"AND profile_id NOT IN ({placeholders})"
            params = {f"i{i}": inc_ids[i] for i in range(len(inc_ids))}

        count_row = db.execute(_sql(
            f"SELECT COUNT(*) FROM bot_watchlist "
            f"WHERE status IN ('active','watching','pending_entry') "
            f"  AND added_at < datetime('now', '-7 days') "
            f"  {inc_clause}"
        ), params).fetchone()
        stale_count = int(count_row[0] if count_row else 0)

        updated = 0
        if stale_count > 0:
            result = db.execute(_sql(
                f"UPDATE bot_watchlist SET status = 'stale_removed' "
                f"WHERE status IN ('active','watching','pending_entry') "
                f"  AND added_at < datetime('now', '-7 days') "
                f"  {inc_clause}"
            ), params)
            db.commit()
            updated = getattr(result, "rowcount", stale_count) or stale_count

        logger.warning("[watchlist-sweep] swept %d stale entries (≥7d, non-incubating)", updated)
        if updated > 0:
            try:
                _alert(
                    title="Watchlist staleness sweep",
                    message=f"Soft-removed {updated} watchlist entries older than 7 days "
                            f"(status → stale_removed).",
                    severity="info",
                    source="bot_scheduler.watchlist_sweep",
                    fields=[
                        {"name": "swept_count", "value": str(updated), "inline": True},
                        {"name": "exempt_profiles", "value": ",".join(_INCUBATING_PROFILE_NAMES), "inline": False},
                    ],
                )
            except Exception as exc:
                logger.warning("[watchlist-sweep] ops alert failed: %s", exc)
        return {"swept": updated, "stale_count": stale_count}
    except Exception as exc:
        logger.error("[watchlist-sweep] failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        db.close()


def _run_and_log(profile_name: str) -> None:
    """Thin wrapper so APScheduler job invocations appear in Railway logs.

    2026-08-13: RSS probe added around the scan body. Deltas > 5MB emit
    WARN; cumulative deltas surface via /admin/mem-probe/snapshot to find
    the ~12min-lifespan container leak.
    """
    import sentry_sdk

    # Ledger #22 kill switch: consult scans_gate before doing any DB work
    # or emitting a scan. Fails open on gate errors — safety comes from
    # env vars if the file-based gate misbehaves.
    try:
        from app.services.scans_gate import is_scans_enabled
        _ok, _reason = is_scans_enabled(profile_name)
        if not _ok:
            logger.warning("[scan-gate] SKIP %s — %s", profile_name, _reason)
            return
    except Exception as _gate_exc:
        logger.warning("[scan-gate] check raised (fail-open): %s", _gate_exc)

    # RSS probe entry — pair with matching exit in the finally block.
    try:
        from app.services.mem_probe import _rss_mb, _tally, _lock  # type: ignore
        _mp_before = _rss_mb()
    except Exception:
        _mp_before = -1.0

    logger.warning("[scheduled] %s scan START", profile_name)
    from app.db.session import SessionLocal
    from strategy_lab.scan_and_execute import scan_and_execute
    db = SessionLocal()
    try:
        with sentry_sdk.start_transaction(op="bot_scan", name=f"scan:{profile_name}"):
            sentry_sdk.set_tag("bot_id", profile_name)
            try:
                result = scan_and_execute(profile_name, db, persist=True, execute=True)
                logger.warning(
                    "[scheduled] %s scan DONE — signals=%d trades=%d errors=%d",
                    profile_name,
                    result.get("signals_generated", 0),
                    result.get("trades_executed", 0),
                    len(result.get("errors", [])),
                )
            except Exception as e:
                sentry_sdk.capture_exception(e)
                raise
    except Exception as exc:
        logger.error("[scheduled] %s FAILED: %s", profile_name, exc, exc_info=True)
    finally:
        # 2026-06-30 (evening): write heartbeat in finally so it fires whether
        # scan_and_execute succeeds OR crashes. Previously PR #48 moved the
        # write out of the signal-fired conditional but kept it inside the
        # outer try block, meaning any scan crash silently prevented the
        # heartbeat update. crypto_onchain has shown last_scan_at =
        # 2026-06-08T21:33 for 22 days despite the scheduler job being
        # registered (bot_scheduler.py:370) — best hypothesis is that
        # scan_and_execute crashes for that bot every fire, and the missing
        # heartbeat hides the fact that the scheduler IS firing. With this
        # change, next deploy's heartbeat behavior distinguishes:
        #   heartbeat updates → scheduler fires (scan crashes; grep Railway
        #                       logs for "[scheduled] X FAILED" to find why)
        #   heartbeat stays stale → scheduler doesn't fire (job never registered
        #                           OR APScheduler dropped it; grep for
        #                           "[startup-trace] registered job bot_X")
        # RSS probe exit — record delta into per-job tally.
        try:
            from app.services.mem_probe import _rss_mb, _tally, _lock  # type: ignore
            _mp_after = _rss_mb()
            _mp_delta = _mp_after - _mp_before if _mp_before >= 0 else 0.0
            _key = f"scan:{profile_name}"
            with _lock:
                _row = _tally[_key]
                _row[0] += 1
                _row[1] += _mp_delta
                if _mp_delta > _row[2]:
                    _row[2] = _mp_delta
                _row[3] = _mp_after
            if _mp_delta >= 5.0:
                logger.warning("[mem-probe] scan:%s +%.1fMB rss=%.0fMB",
                               profile_name, _mp_delta, _mp_after)
        except Exception:
            pass

        try:
            from sqlalchemy import text as _hb_text
            from datetime import datetime as _hb_dt, timezone as _hb_tz
            _now_iso = _hb_dt.now(_hb_tz.utc).isoformat()
            # Default cadence for the initial INSERT only — existing rows keep
            # whatever cadence was seeded by the stale-check upserter (which
            # writes real values from bot_profiles.asset_class). The NOT NULL
            # constraint on expected_cadence_minutes was silently rejecting
            # every new-row heartbeat write and hiding scanner activity from
            # /admin/inert-bot-scan. Heuristic: crypto → 240, options → 30,
            # everything else → 90; overwritten on next stale-sweep.
            _pn = profile_name.lower()
            if _pn.startswith("options_"):
                _default_cadence = 30
            elif _pn.startswith("crypto_"):
                _default_cadence = 240
            else:
                _default_cadence = 90
            db.execute(
                _hb_text(
                    "INSERT INTO bot_heartbeat (bot_name, expected_cadence_minutes, "
                    "last_scan_at, updated_at) VALUES (:n, :c, :t, :t) "
                    "ON CONFLICT(bot_name) DO UPDATE SET "
                    "last_scan_at = :t, updated_at = :t"
                ),
                {"n": profile_name, "c": _default_cadence, "t": _now_iso},
            )
            db.commit()
        except Exception as _hb_exc:
            logger.warning(
                "[heartbeat:%s] write failed (non-fatal): %s",
                profile_name, _hb_exc,
            )
        finally:
            db.close()


def setup_bot_scheduler(scheduler) -> None:
    """Register the six bot-profile cron jobs.

    Schedule reference (all times ET unless noted):
      stock_swing  — weekdays 4:05 PM ET (market close + 5 min)
      stock_lt     — first Tuesday of each month, 10:00 AM ET
      crypto_swing — every 4 hours (24/7)
      crypto_lt    — Monday 10:00 AM UTC (weekly DCA)
    """
    logger.warning("[startup-trace] setup_bot_scheduler called — registering bot jobs")

    # ------------------------------------------------------------------
    # stock_swing: 4:05 PM ET, Mon-Fri
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("stock_swing"),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=50, timezone=ET),
        id="bot_stock_swing",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # stock_day: intraday — every 5 min during market hours, Mon-Fri
    # (opening-range established after first 30 min)
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("stock_day"),
        CronTrigger(day_of_week="mon-fri", hour="4-19", minute="*/5", timezone=ET),
        id="bot_stock_day",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # stock_lt: every Tuesday 10:00 AM ET
    # next_run_time fires once on deploy for pipeline verification.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("stock_lt"),
        CronTrigger(day_of_week="tue", hour=10, minute=0, timezone=ET),
        id="bot_stock_lt",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_swing: every 4 hours, 24/7 — fire immediately on startup
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_swing"),
        CronTrigger(hour="*/4", minute=0),
        id="bot_crypto_swing",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_day: every 5 min, 24/7 — crypto has no market-hours gate
    # Reduced from 1min: each scan takes 15-30s; 1min with max_instances=1
    # meant every 10s Alpaca timeout dropped the next trigger permanently.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_day"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_day",
        replace_existing=True,
        next_run_time=datetime.now(UTC),  # fire immediately on startup
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_lt DCA: Monday 10:00 AM UTC
    # next_run_time=datetime.now(UTC) fires once on startup so we get a
    # health record immediately without waiting until next Monday.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_lt"),
        CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=UTC),
        id="bot_crypto_lt_dca",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # v2 LEAN framework — crypto_lt shadow runner (same schedule as v1)
    # Runs side-by-side: writes to v2_shadow_runs, no trade execution.
    # Compare output with v1 bot_signals to validate parity before cutover.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: __import__("strategy_lab.v2.shadow_runner", fromlist=["run_v2_shadow"]).run_v2_shadow("crypto_lt"),
        CronTrigger(day_of_week="mon", hour=10, minute=1, timezone=UTC),  # 1 min after v1
        id="bot_crypto_lt_v2_shadow",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Daily briefing email: 8:00 AM ET, Mon-Fri
    # ------------------------------------------------------------------
    def _run_daily_briefing():
        from app.db.session import SessionLocal
        from strategy_lab.daily_briefing import run_daily_briefing_job

        db = SessionLocal()
        try:
            run_daily_briefing_job(db)
        except Exception as exc:
            logger.error("daily_briefing job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_daily_briefing,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=ET),
        id="daily_briefing_email",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Position monitor: every 2 minutes, 24/7
    # Checks open positions against stop/target; handles trailing stop.
    # ------------------------------------------------------------------
    def _run_position_monitor():
        try:
            from strategy_lab.core.position_monitor import run_position_monitor
            run_position_monitor()
        except Exception as exc:
            logger.error("position_monitor job failed: %s", exc)

    # Cost cut 2026-08-12 (Brock): 2-min → 15-min. Same protection on the
    # book (stops/targets/expiry checks) at 1/7 the compute. Bot-specific
    # monitors below stay at their per-bot cadence; this is the fleet-wide
    # sweep.
    scheduler.add_job(
        _run_position_monitor,
        CronTrigger(minute="*/15"),
        id="position_monitor",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # stock_day intraday position monitor: every 5 min, 4am–7pm ET, Mon-Fri
    # Extended to cover premarket + afterhours positions.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_bot_position_monitor("stock_day"),
        CronTrigger(day_of_week="mon-fri", hour="4-19", minute="*/5", timezone=ET),
        id="bot_stock_day_position_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # stock_swing intraday position monitor: every 5 min, 9–15 ET, Mon-Fri
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_bot_position_monitor("stock_swing"),
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=ET),
        id="bot_stock_swing_position_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Dead-man's switch: every hour during market hours, Mon-Fri
    # (check_dead_mans_switch itself gates on 9:30–16:00 ET)
    # ------------------------------------------------------------------
    def _run_dead_mans_switch():
        from app.db.session import SessionLocal
        from strategy_lab.core.bot_health import check_dead_mans_switch

        db = SessionLocal()
        try:
            check_dead_mans_switch(db, lookback_hours=4)
        except Exception as exc:
            logger.error("dead_mans_switch job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_dead_mans_switch,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute=0, timezone=ET),
        id="dead_mans_switch",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # crypto_onchain: every 4 hours, 24/7 (same cadence as crypto_swing)
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_onchain"),
        CronTrigger(hour="*/4", minute=30),
        id="bot_crypto_onchain",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # options_income: every 30 min during market hours, Mon-Fri
    # Scans high-IV stocks for wheel / covered-call / CSP entries.
    # Starts at 10:00 AM (after opening range) through 3:30 PM.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("options_income"),
        CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=ET),
        id="bot_options_income",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # options_directional: every 30 min during market hours, Mon-Fri
    # Scans for credit/debit spreads and momentum options entries.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("options_directional"),
        CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=ET),
        id="bot_options_directional",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_quant_aggressive: every 5 min, 24/7
    # High-turnover quant bot — 20-coin universe, 5-signal stack.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_aggressive"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_aggressive",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_aggressive (*/5 min, fires immediately)")

    # ------------------------------------------------------------------
    # Quant fleet hourly summary: every hour at :00, 24/7
    # Drains _quant_buffer and posts a single embed to #quant-signals.
    # If the buffer is empty (no quant signals that hour), silently skips.
    # ------------------------------------------------------------------
    def _quant_hourly_summary():
        try:
            from app.services.discord_public import post_quant_hourly_summary
            post_quant_hourly_summary()
        except Exception as exc:
            logger.error("[quant-hourly-summary] failed: %s", exc)

    scheduler.add_job(
        _quant_hourly_summary,
        CronTrigger(minute=0),  # top of every hour
        id="quant_hourly_summary",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job quant_hourly_summary (every hour at :00)")

    # ------------------------------------------------------------------
    # Quant fleet daily summary: 4:00 PM ET — fleet stats for the day
    # ------------------------------------------------------------------
    def _quant_daily_summary():
        try:
            from app.services.discord_public import post_quant_daily_summary
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                post_quant_daily_summary(db)
            finally:
                db.close()
        except Exception as exc:
            logger.error("[quant-daily-summary] failed: %s", exc)

    scheduler.add_job(
        _quant_daily_summary,
        CronTrigger(hour=16, minute=0, timezone=ET),
        id="quant_daily_summary",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job quant_daily_summary (4:00 PM ET daily)")

    # ------------------------------------------------------------------
    # crypto_quant_scalper: every 15 min, 24/7 (was 1min — cost cut 2026-08-13)
    # 15× reduction. Scalper strategy loses edge at 15min but fund is halted;
    # bump back down to */1 when unhalted if bot is still funded.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_scalper"),
        CronTrigger(minute="*/15"),
        id="bot_crypto_quant_scalper",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_scalper (*/15 min, fires immediately)")

    # ------------------------------------------------------------------
    # crypto_quant_mean_reversion: every 15 min, 24/7 (was 3min — cost cut 2026-08-13)
    # 5× reduction; 4h holds are unaffected by scan cadence.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_mean_reversion"),
        CronTrigger(minute="*/15"),
        id="bot_crypto_quant_mean_reversion",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_mean_reversion (*/15 min, fires immediately)")

    # ------------------------------------------------------------------
    # 2026-07-01 NEW BOTS (funded by m052 reallocation from halted bots)
    # ------------------------------------------------------------------

    # crypto_quant_alt_focus: every 5 min, 24/7. Same strategy stack as
    # crypto_quant_aggressive but universe is Tier B/C/D only (skips BTC/ETH).
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_alt_focus"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_alt_focus",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_alt_focus (*/5 min, fires immediately)")

    # crypto_quant_scalp_1m: every 15 min, 24/7 (was 2min — cost cut 2026-08-13).
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_scalp_1m"),
        CronTrigger(minute="*/15"),
        id="bot_crypto_quant_scalp_1m",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_scalp_1m (*/15 min, fires immediately)")

    # crypto_dca_btc_eth: Monday 10:00 UTC, weekly. Boring DCA baseline.
    scheduler.add_job(
        lambda: _run_and_log("crypto_dca_btc_eth"),
        CronTrigger(day_of_week="mon", hour=10, minute=0),
        id="bot_crypto_dca_btc_eth",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_dca_btc_eth (mon 10:00 UTC, weekly)")

    # ------------------------------------------------------------------
    # 2026-07-02 SECOND BATCH — 5 more quant bots (m053 reallocation)
    # Brock directive: same-volume-as-aggressive quant bots. Different
    # universes + timeframes; same 8-strategy stack. $20k each.
    # ------------------------------------------------------------------

    # top6 majors — concentrated liquidity, 5m
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_universe_top6"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_universe_top6",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_universe_top6 (*/5 min, fires immediately)")

    # defi + L2 basket
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_defi_l2"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_defi_l2",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_defi_l2 (*/5 min, fires immediately)")

    # meme + high-beta tier
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_meme_tier"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_meme_tier",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_meme_tier (*/5 min, fires immediately)")

    # 10-minute timeframe variant
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_10m"),
        CronTrigger(minute="*/10"),
        id="bot_crypto_quant_10m",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_10m (*/10 min, fires immediately)")

    # 15-minute timeframe variant
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_15m"),
        CronTrigger(minute="*/15"),
        id="bot_crypto_quant_15m",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_15m (*/15 min, fires immediately)")

    # ------------------------------------------------------------------
    # 2026-07-02 STOCK QUANT BATCH — 4 new bots (funded by m056)
    # 2 day traders + 2 swing traders. Complementary strategy families —
    # momentum vs mean-rev intraday, growth vs value on swing.
    # ------------------------------------------------------------------

    # stock_quant_day_momentum: */5 min during market hours Mon-Fri
    scheduler.add_job(
        lambda: _run_and_log("stock_quant_day_momentum"),
        CronTrigger(day_of_week="mon-fri", minute="*/5", hour="9-15", timezone=ET),
        id="bot_stock_quant_day_momentum",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_quant_day_momentum (*/5 9-15 ET Mon-Fri)")

    # stock_quant_day_meanrev: */5 min during market hours Mon-Fri
    scheduler.add_job(
        lambda: _run_and_log("stock_quant_day_meanrev"),
        CronTrigger(day_of_week="mon-fri", minute="*/5", hour="9-15", timezone=ET),
        id="bot_stock_quant_day_meanrev",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_quant_day_meanrev (*/5 9-15 ET Mon-Fri)")

    # stock_quant_swing_growth: 3:30 PM ET Mon-Fri (30 min before close)
    scheduler.add_job(
        lambda: _run_and_log("stock_quant_swing_growth"),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone=ET),
        id="bot_stock_quant_swing_growth",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_quant_swing_growth (15:30 ET Mon-Fri)")

    # stock_quant_swing_value: 4:00 PM ET Mon-Fri (right after close)
    scheduler.add_job(
        lambda: _run_and_log("stock_quant_swing_value"),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        id="bot_stock_quant_swing_value",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_quant_swing_value (16:00 ET Mon-Fri)")

    # ------------------------------------------------------------------
    # 2026-07-02 BROCK TABLE BATCH — 4 new stock traders per spec
    # Ships as enabled=false in the YAML profiles. Scheduler still
    # registers so that once m057 enables the bots (post-approval), the
    # cron fires without a redeploy.
    # ------------------------------------------------------------------

    # stock_gap_fade: 9:00-10:59 ET Mon-Fri, */5 min
    scheduler.add_job(
        lambda: _run_and_log("stock_gap_fade"),
        CronTrigger(day_of_week="mon-fri", minute="*/5", hour="9-10", timezone=ET),
        id="bot_stock_gap_fade",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_gap_fade (*/5 9-10 ET Mon-Fri)")

    # stock_orb_breakout: 10-15 ET Mon-Fri, */5 min (ORB window ends 10 AM)
    scheduler.add_job(
        lambda: _run_and_log("stock_orb_breakout"),
        CronTrigger(day_of_week="mon-fri", minute="*/5", hour="10-15", timezone=ET),
        id="bot_stock_orb_breakout",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_orb_breakout (*/5 10-15 ET Mon-Fri)")

    # stock_momentum_breakout: 3:30 PM ET Mon-Fri
    scheduler.add_job(
        lambda: _run_and_log("stock_momentum_breakout"),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone=ET),
        id="bot_stock_momentum_breakout",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_momentum_breakout (15:30 ET Mon-Fri)")

    # stock_pead: 4:00 PM ET Mon-Fri
    scheduler.add_job(
        lambda: _run_and_log("stock_pead"),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        id="bot_stock_pead",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_stock_pead (16:00 ET Mon-Fri)")

    # macro_faber_gtaa: 3:45 PM ET daily Mon-Fri (post-close prep, applies
    # 10-month SMA rule on 5 macro ETFs). Fires once immediately so bar
    # cache warms on deploy.
    scheduler.add_job(
        lambda: _run_and_log("macro_faber_gtaa"),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=45, timezone=ET),
        id="bot_macro_faber_gtaa",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_macro_faber_gtaa (15:45 ET Mon-Fri)")

    # spy_iron_condor_weekly: Monday 10:00 AM ET (weekly 16-delta condor
    # entry on SPY/QQQ/IWM at 45 DTE). One-shot per week during RTH.
    scheduler.add_job(
        lambda: _run_and_log("spy_iron_condor_weekly"),
        CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=ET),
        id="bot_spy_iron_condor_weekly",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_spy_iron_condor_weekly (10:00 ET Mon)")

    # One-time startup log: emit cooldown_minutes for each quant bot so Railway
    # logs confirm the YAML setting is in effect on this deploy.
    try:
        from strategy_lab.seeds import load_profile as _lp
        for _pname in ("crypto_quant_scalper", "crypto_quant_aggressive", "crypto_quant_mean_reversion"):
            _p = _lp(_pname) or {}
            logger.warning(
                "[cooldown-active] bot=%s cadence=%s cooldown_minutes=%s position_cap=%s",
                _pname, _p.get("cadence", "?"), _p.get("cooldown_minutes", 0), _p.get("position_cap", "?"),
            )
    except Exception as _exc:
        logger.warning("[cooldown-active] could not load profiles: %s", _exc)

    # ------------------------------------------------------------------
    # Public Discord daily digest: 4:30 PM ET weekdays + midnight UTC (crypto)
    # ------------------------------------------------------------------
    def _discord_daily_digest():
        try:
            from app.services.discord_public import post_daily_digest
            from app.db.session import SessionLocal
            from app.db.models.bots import BotSignal, BotDailyPnL
            from datetime import date
            db = SessionLocal()
            try:
                today = date.today()
                from sqlalchemy import func
                sigs = db.query(BotSignal).filter(
                    func.date(BotSignal.ts) == today
                ).all()
                by_bot: dict = {}
                for s in sigs:
                    from app.db.models.bots import BotAllocation, BotProfile
                    alloc = db.get(BotAllocation, s.allocation_id)
                    if alloc:
                        prof = db.get(BotProfile, alloc.profile_id)
                        if prof:
                            by_bot[prof.name] = by_bot.get(prof.name, 0) + 1
                top_syms = list({s.symbol for s in sigs})[:5]
                pnl_rows = db.query(BotDailyPnL).filter(BotDailyPnL.date == today).all()
                realized = sum(r.realized_cents for r in pnl_rows)
                post_daily_digest({
                    "total_signals": len(sigs),
                    "by_bot": by_bot,
                    "top_symbols": top_syms,
                    "realized_pnl_cents": realized,
                })
            finally:
                db.close()
        except Exception as exc:
            logger.error("discord daily digest failed: %s", exc)

    scheduler.add_job(
        _discord_daily_digest,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="discord_daily_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        _discord_daily_digest,
        CronTrigger(hour=0, minute=5, timezone=UTC),  # midnight UTC for crypto
        id="discord_daily_digest_crypto",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Weekly leaderboard: Sundays 6 PM ET
    # ------------------------------------------------------------------
    def _discord_weekly_leaderboard():
        try:
            from app.services.discord_public import post_weekly_leaderboard
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                from app.core.canonical import compute_strategy_lab_aggregate
                from app.db.models.users import User
                users = db.query(User).filter(User.is_active.is_(True)).limit(1).all()
                if users:
                    result = compute_strategy_lab_aggregate(users[0].id, db)
                    post_weekly_leaderboard(result.get("leaderboard", []))
            finally:
                db.close()
        except Exception as exc:
            logger.error("discord weekly leaderboard failed: %s", exc)

    scheduler.add_job(
        _discord_weekly_leaderboard,
        CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=ET),
        id="discord_weekly_leaderboard",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Monthly recap: 1st of month, 9:00 AM ET
    # ------------------------------------------------------------------
    def _discord_monthly_recap():
        try:
            from app.services.discord_public import post_monthly_recap
            from app.db.session import SessionLocal
            from app.db.models.bots import BotSignal, BotDailyPnL, BotTrade
            from datetime import date
            import calendar

            db = SessionLocal()
            try:
                today      = date.today()
                # Previous month bounds
                first_prev = date(today.year, today.month - 1 if today.month > 1 else 12, 1)
                if today.month == 1:
                    first_prev = date(today.year - 1, 12, 1)
                else:
                    first_prev = date(today.year, today.month - 1, 1)
                last_prev  = date(first_prev.year, first_prev.month,
                                  calendar.monthrange(first_prev.year, first_prev.month)[1])
                from sqlalchemy import func
                signals = db.query(BotSignal).filter(
                    func.date(BotSignal.ts) >= first_prev,
                    func.date(BotSignal.ts) <= last_prev,
                ).count()
                pnl_rows = db.query(BotDailyPnL).filter(
                    BotDailyPnL.date >= first_prev,
                    BotDailyPnL.date <= last_prev,
                ).all()
                pnl_cents = sum(
                    (r.realized_cents or 0) + (r.unrealized_cents or 0)
                    for r in pnl_rows
                )
                trades = db.query(BotTrade).filter(
                    BotTrade.side == "sell",
                    func.date(BotTrade.ts) >= first_prev,
                    func.date(BotTrade.ts) <= last_prev,
                ).count()
                post_monthly_recap({
                    "month_name": first_prev.strftime("%B %Y"),
                    "signals":    signals,
                    "trades":     trades,
                    "pnl_cents":  pnl_cents,
                })
            finally:
                db.close()
        except Exception as exc:
            logger.error("discord monthly recap failed: %s", exc)

    scheduler.add_job(
        _discord_monthly_recap,
        CronTrigger(day=1, hour=9, minute=0, timezone=ET),
        id="discord_monthly_recap",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # C8 — Daily NAV calculation: 4:30 PM ET, Mon-Fri
    # Computes portfolio NAV (starting capital + realized + unrealized),
    # stores to nav_history table, renders as chart on /portfolio page.
    # ------------------------------------------------------------------
    def _compute_daily_nav():
        from app.db.session import SessionLocal
        from app.jobs.compute_nav import compute_and_store_nav
        db = SessionLocal()
        try:
            result = compute_and_store_nav(db)
            logger.warning(
                "[nav-cron] computed: date=%s nav_cents=%d pct_change=%s",
                result.get("date"), result.get("nav_cents", 0), result.get("pct_change"),
            )
        except Exception as exc:
            logger.error("[nav-cron] failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _compute_daily_nav,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="daily_nav_calculation",
        replace_existing=True,
    )
    # Also compute on startup so the chart has a row from day 1
    scheduler.add_job(
        _compute_daily_nav,
        "date",
        run_date=datetime.now(UTC),
        id="daily_nav_startup",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # C1 — Bot health watchdog: every 15 min, 24/7
    # Independent of queen sessions — catches RED transitions even when
    # no session is firing (e.g., weekends, overnight).
    # ------------------------------------------------------------------
    def _health_watchdog():
        from app.db.session import SessionLocal
        from strategy_lab.agents.strategy_monitor import run_strategy_health_check
        db = SessionLocal()
        try:
            run_strategy_health_check(db)
        except Exception as exc:
            logger.error("[health-watchdog] failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _health_watchdog,
        CronTrigger(minute="*/15"),
        id="bot_health_watchdog",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered bot_health_watchdog (*/15 min)")

    # ------------------------------------------------------------------
    # Recurring dupe quarantine: every 10 min, 24/7
    # Band-aid until cooldown root cause is confirmed fixed. Same logic
    # as the startup migration but runs repeatedly so dupes can't
    # accumulate between restarts.
    # ------------------------------------------------------------------
    def _quarantine_dupes_periodic():
        try:
            from app.db.session import SessionLocal
            from sqlalchemy import text
            from datetime import datetime as _dt, timezone as _tz
            from collections import defaultdict as _dd

            db = SessionLocal()
            try:
                rows = db.execute(text("""
                    SELECT id, allocation_id, symbol, avg_cost_cents, qty, opened_at
                    FROM bot_positions
                    WHERE closed_at IS NULL
                      AND quarantined_at IS NULL
                    ORDER BY allocation_id, symbol, id
                """)).fetchall()

                groups = _dd(list)
                for row in rows:
                    groups[(row[1], row[2])].append({
                        "id": row[0], "avg_cost_cents": row[3] or 0,
                        "qty": row[4] or 0, "opened_at": row[5],
                    })

                def _ts(s):
                    if not s:
                        return 0
                    try:
                        if isinstance(s, _dt):
                            return int(s.timestamp())
                        return int(_dt.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
                    except Exception:
                        return 0

                to_quarantine = []
                for positions in groups.values():
                    if len(positions) < 2:
                        continue
                    sorted_pos = sorted(positions, key=lambda x: x["id"])
                    keeper = sorted_pos[0]
                    keeper_ts = _ts(keeper["opened_at"])
                    for pos in sorted_pos[1:]:
                        same_cost = abs(pos["avg_cost_cents"] - keeper["avg_cost_cents"]) <= 1
                        same_qty = abs(pos["qty"] - keeper["qty"]) < 0.0001
                        within_60s = abs(_ts(pos["opened_at"]) - keeper_ts) <= 60
                        if same_cost and same_qty and within_60s:
                            to_quarantine.append(pos["id"])

                if to_quarantine:
                    now = _dt.now(_tz.utc).isoformat()
                    for pos_id in to_quarantine:
                        db.execute(text("""
                            UPDATE bot_positions
                            SET quarantined_at = :now,
                                quarantine_reason = 'cooldown_dupe_merged'
                            WHERE id = :id
                        """), {"now": now, "id": pos_id})
                    db.commit()
                    logger.error(
                        "[dupe-quarantine] periodic: quarantined %d duplicate positions",
                        len(to_quarantine),
                    )
                else:
                    logger.warning("[dupe-quarantine] periodic: no duplicates found")
            finally:
                db.close()
        except Exception as exc:
            logger.error("[dupe-quarantine] periodic job failed: %s", exc)

    scheduler.add_job(
        _quarantine_dupes_periodic,
        CronTrigger(minute="*/10"),
        id="quarantine_dupes_periodic",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Fleet Sentinel: every 10 min, 24/7
    # Runs 7 health checks and posts paste-ready alerts to #fund-updates
    # when issues are detected. 4-hour in-memory dedup prevents spam.
    # ------------------------------------------------------------------
    def _run_fleet_sentinel():
        from app.db.session import SessionLocal
        from strategy_lab.core.fleet_sentinel import run_fleet_sentinel
        db = SessionLocal()
        try:
            run_fleet_sentinel(db)
        except Exception as exc:
            logger.error("[fleet-sentinel] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_fleet_sentinel,
        CronTrigger(minute="*/10"),
        id="fleet_sentinel",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered fleet_sentinel (*/10 min)")

    def _post_discord_daily_digest(db) -> None:
        from strategy_lab.daily_briefing import build_discord_digest
        from app.services.discord_public import post_daily_digest
        try:
            digest = build_discord_digest(db)
            post_daily_digest(digest)
            logger.warning(
                "[daily-digest] posted — signals=%d pnl_cents=%d open=%d",
                digest["total_signals"], digest["realized_pnl_cents"], digest["open_positions"],
            )
        except Exception as exc:
            logger.error("[daily-digest] build/post failed: %s", exc)

    # ------------------------------------------------------------------
    # Daily Discord digest: 4:30 PM ET, Mon-Fri (after stock market close)
    # Posts P&L summary, top trades, signal count to #daily-digest.
    # ------------------------------------------------------------------
    def _run_daily_discord_digest():
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            _post_discord_daily_digest(db)
        except Exception as exc:
            logger.error("daily_discord_digest job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_daily_discord_digest,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="daily_discord_digest",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Strategy Scout scanner: every 5 min — gate on ENABLE_STRATEGY_SCOUT.
    # ------------------------------------------------------------------
    def _run_scout_scan():
        try:
            from strategy_lab.scout_scanner import run_scout_scan
            run_scout_scan()
        except Exception as exc:
            logger.error("[scout-scanner] job failed: %s", exc)

    scheduler.add_job(
        _run_scout_scan,
        CronTrigger(minute="*/5"),
        id="strategy_scout_scan",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # The Forge scanner: every 5 min — gate on ENABLE_STRATEGY_FORGE.
    # ------------------------------------------------------------------
    def _run_forge_scan():
        try:
            from strategy_lab.forge_scanner import run_forge_scan
            run_forge_scan()
        except Exception as exc:
            logger.error("[forge-scanner] job failed: %s", exc)

    scheduler.add_job(
        _run_forge_scan,
        CronTrigger(minute="*/5"),
        id="strategy_forge_scan",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Signal explanation pre-gen: hourly — gate on ENABLE_TRADE_EXPLAIN.
    # ------------------------------------------------------------------
    def _run_explain_pregen():
        import os
        if os.getenv("ENABLE_TRADE_EXPLAIN", "false").strip().lower() != "true":
            return
        try:
            from strategy_lab.explain_pregen import run_explain_pregen
            run_explain_pregen()
        except Exception as exc:
            logger.error("[explain-pregen] job failed: %s", exc)

    scheduler.add_job(
        _run_explain_pregen,
        CronTrigger(minute=30),
        id="signal_explain_pregen",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # tsmom_multi_asset: Friday 5PM ET weekly rebalance
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("tsmom_multi_asset"),
        CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=ET),
        id="bot_tsmom_multi_asset",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # quality_factor: first Tuesday of month 10:30 AM ET
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("quality_factor"),
        CronTrigger(day_of_week="tue", hour=10, minute=30, timezone=ET),
        id="bot_quality_factor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # value_quality: first Tuesday of month 11 AM ET
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("value_quality"),
        CronTrigger(day_of_week="tue", hour=11, minute=0, timezone=ET),
        id="bot_value_quality",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_meanrev_2163: every 4 hours, 24/7
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_meanrev_2163"),
        CronTrigger(hour="*/4", minute=30),
        id="bot_crypto_meanrev_2163",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # earnings_nlp: 9AM ET daily Mon-Fri (BLOCKED stub)
    # ------------------------------------------------------------------
    def _earnings_nlp_guarded():
        if not os.getenv("ENABLE_EARNINGS_NLP"):
            return
        _run_and_log("earnings_nlp")

    scheduler.add_job(
        _earnings_nlp_guarded,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=ET),
        id="bot_earnings_nlp",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Bot performance stats rollup: 2:00 AM ET daily
    # ------------------------------------------------------------------
    def _run_compute_bot_stats():
        try:
            from app.jobs.compute_bot_stats import run as run_stats
            result = run_stats()
            logger.warning(
                "[compute-bot-stats] done — processed=%d promoted=%d demoted=%d errors=%d",
                result.get("processed", 0), result.get("promoted", 0),
                result.get("demoted", 0), result.get("errors", 0),
            )
        except Exception as exc:
            logger.error("[compute-bot-stats] failed: %s", exc)

    scheduler.add_job(
        _run_compute_bot_stats,
        CronTrigger(hour=2, minute=0, timezone=ET),
        id="compute_bot_stats",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job compute_bot_stats (2:00 AM ET daily)")

    # ------------------------------------------------------------------
    # Queen Agent — 1 consolidated morning brief per day to #dev-log
    #   morning  06:30 AM ET  Mon-Sun (quiet mode: was 6x/day)
    #
    # Expected brief format when run_queen_daily(db, session="morning") fires:
    #
    # // QUEEN MORNING BRIEF — <date>
    #
    # Fleet P&L (24h): $X (Z bps)
    # Open positions: N
    # Top winner: <bot> +$X
    # Top loser: <bot> -$X
    #
    # // RISK (Dick) — <status emoji>
    # <one-line summary>
    #
    # // DATA (Vick) — <status emoji>
    # <one-line summary>
    #
    # // OPS (Wick) — <status emoji>
    # <one-line summary>
    #
    # // MACRO (Rick) — <regime>
    # <one-line summary>
    #
    # // RESEARCHER (Nick) — <signal count>
    # <one-line summary>
    #
    # Items needing your attention: <bullet list or "none">
    # ------------------------------------------------------------------
    def _make_queen_job(session_name: str):
        def _job():
            from app.db.session import SessionLocal
            from strategy_lab.agents.queen import run_queen_daily
            db = SessionLocal()
            try:
                run_queen_daily(db, session=session_name)
            except Exception as exc:
                logger.error("[queen-%s] job failed: %s", session_name, exc)
            finally:
                db.close()
        _job.__name__ = f"_queen_{session_name}"
        return _job

    # Brock's cadence spec: Brick/Queen → weekdays at 6:30 AM ET
    scheduler.add_job(
        _make_queen_job("morning"),
        CronTrigger(day_of_week="mon-fri", hour=6, minute=30, timezone=ET),
        id="queen_morning",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job queen_morning (weekdays 6:30 AM ET)")

    # ------------------------------------------------------------------
    # Pre-market book — weekdays 8:00 AM CT (9:00 AM ET).
    # Brock's 2026-07-02 aggressive-paper directive: post "here's the book,
    # here's what fired overnight, here's what's armed" every morning so
    # he sees the fleet state before market open without opening a page.
    # ------------------------------------------------------------------
    def _run_pre_market_book():
        from app.db.session import SessionLocal
        from app.jobs.pre_market_book import post_pre_market_book
        db = SessionLocal()
        try:
            post_pre_market_book(db)
        except Exception as exc:
            logger.error("[pre-market-book] job failed: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _run_pre_market_book,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=ET),  # 8:00 AM CT = 9:00 AM ET
        id="pre_market_book",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job pre_market_book (weekdays 8:00 AM CT / 9:00 AM ET)")

    # ------------------------------------------------------------------
    # Pre-open readiness — weekdays 8:15 AM CT (9:15 AM ET). 15 minutes
    # after the pre-market book, so both post before market open. This one
    # is the operational readiness summary Brock explicitly asked for.
    # ------------------------------------------------------------------
    def _run_pre_open_readiness():
        from app.db.session import SessionLocal
        from app.jobs.pre_open_readiness import post_readiness
        db = SessionLocal()
        try:
            post_readiness(db)
        except Exception as exc:
            logger.error("[pre-open-readiness] job failed: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _run_pre_open_readiness,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=15, timezone=ET),  # 8:15 AM CT = 9:15 AM ET
        id="pre_open_readiness",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job pre_open_readiness (weekdays 8:15 AM CT / 9:15 AM ET)")

    def _run_market_open_check():
        from app.db.session import SessionLocal
        from scripts.market_open_check import post_market_open_check
        db = SessionLocal()
        try:
            post_market_open_check(db)
        except Exception as exc:
            logger.error("[market_open_check] job failed: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _run_market_open_check,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=55, timezone=ET),  # 8:55 CT / 9:55 ET
        id="market_open_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job market_open_check (weekdays 8:55 AM CT / 9:55 AM ET)")

    # ------------------------------------------------------------------
    # Regime snapshot refresh — hourly, keeps regime_snapshots table fresh
    # so DQW, researcher, and queen always have current market regime data.
    # Fires immediately on startup to seed the table.
    # ------------------------------------------------------------------
    def _run_regime_refresh():
        from app.db.session import SessionLocal
        from strategy_lab.core.regime_detector import get_regime, _persist_snapshot
        db = SessionLocal()
        try:
            # get_regime() returns cached value if fresh — always force a DB persist
            regime = get_regime(db)
            _persist_snapshot(regime, db)  # _persist_snapshot has its own 15-min DB guard
            logger.info("[regime_refresh] snapshot updated: vix=%s trend=%s",
                        regime.get("vix_regime"), regime.get("trend_regime"))
        except Exception as exc:
            logger.error("[regime_refresh] failed: %s", exc)
        finally:
            db.close()

    from apscheduler.triggers.interval import IntervalTrigger as _IT
    from datetime import datetime as _dt, timezone as _tz
    scheduler.add_job(
        _run_regime_refresh,
        _IT(hours=1),
        id="regime_snapshot_refresh",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
        next_run_time=_dt.now(_tz.utc),  # fire immediately on startup
    )
    logger.warning("[startup-trace] registered job regime_snapshot_refresh (hourly, fires now)")

    # ------------------------------------------------------------------
    # Regime alert check — event-driven, polls every 30 min
    # Posts immediately to Discord when a condition fires (24h cooldown).
    # ------------------------------------------------------------------
    def _run_regime_alert_check():
        from app.db.session import SessionLocal
        from strategy_lab.agents.queen import run_regime_alert_check
        db = SessionLocal()
        try:
            run_regime_alert_check(db)
        except Exception as exc:
            logger.error("[queen-regime-alert] failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_regime_alert_check,
        CronTrigger(minute="*/30"),
        id="queen_regime_alert_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job queen_regime_alert_check (every 30 min)")

    # ------------------------------------------------------------------
    # Deploy 2 — Tier A monitor agents
    # ------------------------------------------------------------------

    # Risk Sentinel: every 30 min — fleet drawdown + consecutive loss watchdog
    def _run_risk_sentinel():
        from app.db.session import SessionLocal
        from strategy_lab.agents.risk_sentinel import run_risk_health_check
        db = SessionLocal()
        try:
            run_risk_health_check(db)
        except Exception as exc:
            logger.error("[risk_sentinel] job failed: %s", exc)
        finally:
            db.close()

    # Quiet mode: 2x daily instead of every 30 min — no startup immediate fire
    scheduler.add_job(
        _run_risk_sentinel,
        CronTrigger(hour=9, minute=0, timezone=ET),
        id="risk_sentinel_premarket",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    scheduler.add_job(
        _run_risk_sentinel,
        CronTrigger(hour=16, minute=30, timezone=ET),
        id="risk_sentinel_postclose",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered jobs risk_sentinel_premarket (9 AM ET) + risk_sentinel_postclose (4:30 PM ET)")

    # Data Quality Watcher: every hour — regime snapshot + signal freshness
    def _run_data_quality_watcher():
        from app.db.session import SessionLocal
        from strategy_lab.agents.data_quality_watcher import run_data_quality_check
        db = SessionLocal()
        try:
            run_data_quality_check(db)
        except Exception as exc:
            logger.error("[data_quality_watcher] job failed: %s", exc)
        finally:
            db.close()

    # Quiet mode: 1x daily at 8 AM instead of every hour — no startup immediate fire
    scheduler.add_job(
        _run_data_quality_watcher,
        CronTrigger(hour=8, minute=0, timezone=ET),
        id="data_quality_watcher",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job data_quality_watcher (8 AM ET daily)")

    # Execution Auditor: 5 PM ET Mon-Fri — fill quality + slippage after market close
    def _run_execution_auditor():
        from app.db.session import SessionLocal
        from strategy_lab.agents.execution_auditor import run_execution_audit
        db = SessionLocal()
        try:
            run_execution_audit(db)
        except Exception as exc:
            logger.error("[execution_auditor] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_execution_auditor,
        CronTrigger(day_of_week="mon-fri", hour=17, minute=0, timezone=ET),
        id="execution_auditor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job execution_auditor (5 PM ET Mon-Fri)")

    # Operations: 6 PM ET Mon-Fri — back-office reconciliation after execution audit
    def _run_operations():
        from app.db.session import SessionLocal
        from strategy_lab.agents.operations import run_operations_reconciliation
        db = SessionLocal()
        try:
            run_operations_reconciliation(db)
        except Exception as exc:
            logger.error("[operations] job failed: %s", exc)
        finally:
            db.close()

    # Brock's cadence spec: Wick/daily-plan → weekdays only at 6:00 AM ET
    scheduler.add_job(
        _run_operations,
        CronTrigger(day_of_week="mon-fri", hour=6, minute=0, timezone=ET),
        id="operations",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job operations (Mon-Fri 6 AM ET)")

    # ------------------------------------------------------------------
    # Daily standup: 7:00 AM ET — all agents contribute, Queen synthesizes plan
    # Fires immediately on startup so we get a first plan without waiting.
    # ------------------------------------------------------------------
    def _run_daily_standup():
        from app.db.session import SessionLocal
        from agents.standup import run_daily_standup
        db = SessionLocal()
        try:
            run_daily_standup(db)
        except Exception as exc:
            logger.error("[daily_standup] job failed: %s", exc)
        finally:
            db.close()

    # Brock's cadence spec: Nick/research-log → Mon/Thu/Sun at 7 AM ET (every 3 days)
    scheduler.add_job(
        _run_daily_standup,
        CronTrigger(day_of_week="mon,thu,sun", hour=7, minute=0, timezone=ET),
        id="daily_standup",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job daily_standup (Mon/Thu/Sun 7 AM ET)")

    # ------------------------------------------------------------------
    # Macro Strategist: 7:05 AM ET daily — classify regime after standup
    # ------------------------------------------------------------------
    def _run_macro_classification():
        from app.db.session import SessionLocal
        from strategy_lab.agents.macro_strategist import run_macro_classification
        db = SessionLocal()
        try:
            run_macro_classification(db)
        except Exception as exc:
            logger.error("[macro_classification] job failed: %s", exc)
        finally:
            db.close()

    # Brock's cadence spec: Rick/macro → Mondays only at 6:15 AM ET
    scheduler.add_job(
        _run_macro_classification,
        CronTrigger(day_of_week="mon", hour=6, minute=15, timezone=ET),
        id="macro_classification_daily",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job macro_classification_daily (Mondays 6:15 AM ET)")

    # ------------------------------------------------------------------
    # Proposal reaction handler: every 60s — polls Discord for CIO reactions
    # on #queen-proposals messages and routes to executors.
    # ------------------------------------------------------------------
    def _run_proposal_handler():
        from app.db.session import SessionLocal
        from agents.proposal_handler import run_proposal_handler
        db = SessionLocal()
        try:
            run_proposal_handler(db)
        except Exception as exc:
            logger.debug("[proposal_handler] job failed: %s", exc)
        finally:
            db.close()

    # Cost cut 2026-08-13: 60s → 15min. 15× reduction. No pending proposals need per-minute scan.
    scheduler.add_job(
        _run_proposal_handler,
        IntervalTrigger(minutes=15),
        id="proposal_reaction_handler",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job proposal_reaction_handler (every 15min)")

    # ------------------------------------------------------------------
    # Auto-defer check: every 5 minutes — proposals pending > 6h get deferred
    # CIO can still react ✅/❌ after deferral; handler logs it as 'late_decision'.
    # ------------------------------------------------------------------
    def _run_auto_defer_check():
        from app.db.session import SessionLocal
        from agents.proposal_handler import run_auto_defer_check
        db = SessionLocal()
        try:
            run_auto_defer_check(db)
        except Exception as exc:
            logger.debug("[proposal_auto_defer] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_auto_defer_check,
        IntervalTrigger(minutes=5),
        id="proposal_auto_defer",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job proposal_auto_defer (every 5 min, fires immediately)")

    # ------------------------------------------------------------------
    # Fleet heartbeat: every 30s — keeps /fund status dashboard live.
    # Publishes a lightweight "alive" tick to agent_heartbeats for each
    # deployed agent so /api/agents/status can report active/degraded/offline.
    # ------------------------------------------------------------------
    def _fleet_heartbeat():
        from app.db.session import SessionLocal
        from agents.bus import heartbeat
        db = SessionLocal()
        try:
            heartbeat(db, agent_id="queen")
            heartbeat(db, agent_id="researcher")
            heartbeat(db, agent_id="sentinel_devops")
            heartbeat(db, agent_id="risk_sentinel")
            heartbeat(db, agent_id="data_quality_watcher")
            heartbeat(db, agent_id="execution_auditor")
            heartbeat(db, agent_id="operations")
            heartbeat(db, agent_id="macro_strategist")
            heartbeat(db, agent_id="quant_researcher")
        except Exception as exc:
            logger.debug("[fleet_heartbeat] failed: %s", exc)
        finally:
            db.close()

    # Cost cut 2026-08-13: 30s → 30min. 60× reduction in heartbeat writes.
    # Dashboard "alive" tick doesn't need per-30s granularity while fund is halted.
    scheduler.add_job(
        _fleet_heartbeat,
        IntervalTrigger(minutes=30),
        id="fleet_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job fleet_heartbeat (every 30min, fires immediately)")

    # ------------------------------------------------------------------
    # 2026-08-13 Brock: nightly restart @ 04:30 UTC as interim mitigation for
    # the ~12min-lifespan container leak. os._exit(0) exits cleanly; Railway
    # auto-restarts. This keeps the service up while RSS instrumentation
    # gathers 24h of data to locate the leak.
    # ------------------------------------------------------------------
    def _nightly_restart():
        import os as _os
        import time as _t
        logger.warning(
            "[nightly-restart] scheduled restart firing — os._exit(0). "
            "Railway will auto-restart the container.")
        _t.sleep(1)  # flush stdout
        _os._exit(0)

    scheduler.add_job(
        _nightly_restart,
        CronTrigger(hour=4, minute=30, timezone=UTC),
        id="nightly_restart",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job nightly_restart (04:30 UTC daily)")

    # ------------------------------------------------------------------
    # 2026-08-13 Brock: Alpaca WS held-symbols sync — every 15 min.
    # Narrows StockDataStream subscription to only symbols we currently
    # hold. Was: 30-slot buffer filled by frontend subscribe calls.
    # Now: only tickers in open Alpaca positions.
    # ------------------------------------------------------------------
    def _sync_ws_to_held():
        try:
            from app.alpaca.stream import stream_manager
            from app.services.held_symbols import get_held_stock_symbols
            import asyncio as _asy
            held = get_held_stock_symbols()
            # Fire-and-forget async sync (won't block the scheduler thread)
            _loop = None
            try:
                _loop = _asy.get_event_loop()
            except RuntimeError:
                pass
            if _loop and _loop.is_running():
                # Schedule on the running loop
                _asy.run_coroutine_threadsafe(
                    stream_manager.sync_to_held(held), _loop
                )
            else:
                logger.debug("[ws-sync] no event loop running; skip")
        except Exception as exc:
            logger.warning("[ws-sync] failed: %s", exc)

    scheduler.add_job(
        _sync_ws_to_held,
        CronTrigger(minute="*/15"),
        id="alpaca_ws_sync_held",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job alpaca_ws_sync_held (*/15 min)")

    # ------------------------------------------------------------------
    # Deploy 4.5.E — Defensive halt check: every 15 minutes
    # Tier A autonomous executor: pauses a bot on hard drawdown breach.
    # Max 3 auto-pauses/day; escalates to CRITICAL if cap is hit.
    # ------------------------------------------------------------------
    def _run_defensive_halt_check():
        from app.db.session import SessionLocal
        from agents.executors.auto_defensive_halt import run_defensive_halt_check
        db = SessionLocal()
        try:
            result = run_defensive_halt_check(db)
            logger.warning(
                "[defensive_halt_check] done — checked=%d halted=%d skipped_cap=%s",
                result.get("checked", 0),
                result.get("halted", 0),
                result.get("skipped_cap", False),
            )
        except Exception as exc:
            logger.error("[defensive_halt_check] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_defensive_halt_check,
        IntervalTrigger(minutes=15),
        id="defensive_halt_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job defensive_halt_check (every 15 min, fires immediately)")

    # ------------------------------------------------------------------
    # Deploy 4.5.E — Resume check: every 2 minutes
    # Polls Discord for ▶️ reactions on auto-halt messages.
    # If CIO reacted, unpauses the bot and updates proposal_audit.
    # ------------------------------------------------------------------
    def _run_resume_check():
        from app.db.session import SessionLocal
        from agents.executors.auto_defensive_halt import run_resume_check
        db = SessionLocal()
        try:
            result = run_resume_check(db)
            if result.get("resumed", 0) > 0:
                logger.warning(
                    "[resume_check] resumed %d bot(s)", result["resumed"]
                )
        except Exception as exc:
            logger.error("[resume_check] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_resume_check,
        IntervalTrigger(minutes=2),
        id="resume_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job resume_check (every 2 min)")

    # ------------------------------------------------------------------
    # Candidate Pipeline Daemon: 2:30 AM ET daily
    # Advances CANDIDATE→BACKTEST_DONE→WFA_DONE→SHADOW_PAPER→PROMOTED
    # ------------------------------------------------------------------
    def _run_pipeline_daemon():
        from app.db.session import SessionLocal
        from strategy_lab.core.pipeline.executor import advance_pipeline
        db = SessionLocal()
        try:
            result = advance_pipeline(db)
            logger.warning("[pipeline-daemon] run complete: %s", result)
        except Exception as exc:
            logger.error("[pipeline-daemon] failed: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _run_pipeline_daemon,
        CronTrigger(hour=2, minute=30, timezone=ET),
        id="candidate_pipeline_daemon",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job candidate_pipeline_daemon (2:30 AM ET daily)")

    # ------------------------------------------------------------------
    # Price Alert Monitor — checks armed user price alerts vs live prices
    # Stocks: every 1 min during US market hours (9:30–16:00 ET weekdays)
    # Crypto: every 5 min 24/7
    # ------------------------------------------------------------------
    def _run_price_alert_monitor():
        from app.db.session import SessionLocal
        from app.services.price_monitor import run_price_alert_monitor
        db = SessionLocal()
        try:
            run_price_alert_monitor(db)
        except Exception as exc:
            logger.error("[price-alert-monitor] job failed: %s", exc)
        finally:
            db.close()

    # Cost cut 2026-08-13: */1 min → */15 min. 15× reduction. Price alerts
    # aren't triggering real trades while fund is halted; 15min still catches
    # any relevant threshold cross for a paused alert queue.
    scheduler.add_job(
        _run_price_alert_monitor,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/15", timezone=ET),
        id="price_alert_monitor_market",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    scheduler.add_job(
        _run_price_alert_monitor,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        id="price_alert_monitor_close",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )
    scheduler.add_job(
        _run_price_alert_monitor,
        IntervalTrigger(minutes=5),
        id="price_alert_monitor_5min",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered jobs price_alert_monitor (1min market + 5min 24/7)")

    # ------------------------------------------------------------------
    # COMMIT 7 — Scheduler heartbeat / per-bot signal cadence
    # ------------------------------------------------------------------
    # Every 5 min during RTH (stocks) and every 4hr always-on (crypto), poll
    # MAX(bot_signals.ts) per bot, compare to bot_heartbeat.expected_cadence_minutes,
    # and fire an ops alert if stale. Crypto cadence = 240 min (4h); stocks = 90.
    def _run_bot_heartbeat_check(asset_class_filter: str = "all") -> None:
        try:
            from app.db.session import SessionLocal as _SL
            from sqlalchemy import text as _sql
            from app.services.discord import send_ops_alert as _alert
            from datetime import datetime as _dt, timezone as _tz

            db = _SL()
            try:
                # Ensure rows exist for every enabled bot profile with sensible
                # default cadence by asset class. Safe to repeat — UPSERT pattern.
                profile_rows = db.execute(_sql(
                    "SELECT p.name, p.asset_class FROM bot_profiles p "
                    "JOIN bot_allocations a ON a.profile_id = p.id "
                    "WHERE a.enabled = 1 GROUP BY p.name, p.asset_class"
                )).fetchall()
                for name, asset_class in profile_rows:
                    cadence = 240 if str(asset_class).lower().startswith("crypto") else 90
                    db.execute(_sql(
                        "INSERT INTO bot_heartbeat (bot_name, expected_cadence_minutes, updated_at) "
                        "VALUES (:n, :c, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(bot_name) DO UPDATE SET expected_cadence_minutes=:c, "
                        "updated_at=CURRENT_TIMESTAMP"
                    ), {"n": name, "c": cadence})

                # Update last_signal_at / last_scan_at from bot_signals MAX(ts)
                last_sig_rows = db.execute(_sql(
                    "SELECT p.name, MAX(s.ts) AS last_ts "
                    "FROM bot_signals s "
                    "JOIN bot_allocations a ON a.id = s.allocation_id "
                    "JOIN bot_profiles p ON p.id = a.profile_id "
                    "GROUP BY p.name"
                )).fetchall()
                for name, last_ts in last_sig_rows:
                    if last_ts:
                        db.execute(_sql(
                            "UPDATE bot_heartbeat SET last_signal_at = :t, last_scan_at = :t, "
                            "updated_at = CURRENT_TIMESTAMP WHERE bot_name = :n"
                        ), {"n": name, "t": last_ts})
                db.commit()

                # Now check staleness
                stale_rows = db.execute(_sql(
                    "SELECT bot_name, last_signal_at, expected_cadence_minutes "
                    "FROM bot_heartbeat WHERE last_signal_at IS NOT NULL"
                )).fetchall()
                now = _dt.now(_tz.utc)
                stale_list: list[tuple[str, int, int]] = []
                for name, last_signal_at, cadence in stale_rows:
                    if asset_class_filter == "crypto" and (cadence or 0) < 200:
                        continue
                    if asset_class_filter == "stock" and (cadence or 0) > 200:
                        continue
                    if isinstance(last_signal_at, str):
                        try:
                            last_signal_at = _dt.fromisoformat(last_signal_at.replace("Z", "+00:00"))
                        except Exception:
                            continue
                    if last_signal_at.tzinfo is None:
                        last_signal_at = last_signal_at.replace(tzinfo=_tz.utc)
                    age_min = int((now - last_signal_at).total_seconds() / 60)
                    threshold = max(int(cadence or 90) * 2, 30)
                    if age_min > threshold:
                        stale_list.append((name, age_min, threshold))

                if stale_list:
                    fields = [
                        {"name": n, "value": f"{age}m old (threshold {th}m)", "inline": True}
                        for n, age, th in stale_list[:10]
                    ]
                    _alert(
                        title=f"Bot heartbeat stale ({asset_class_filter})",
                        message=f"{len(stale_list)} bot(s) have not emitted signals within cadence threshold.",
                        severity="warn",
                        source="bot_scheduler.heartbeat",
                        fields=fields,
                    )
                    logger.warning("[heartbeat] %d stale bots (%s): %s",
                                   len(stale_list), asset_class_filter,
                                   [n for n, _, _ in stale_list])
                else:
                    logger.info("[heartbeat] all bots fresh (filter=%s, checked=%d)",
                                asset_class_filter, len(stale_rows))
            finally:
                db.close()
        except Exception as exc:
            logger.error("[heartbeat] check failed: %s", exc, exc_info=True)

    scheduler.add_job(
        lambda: _run_bot_heartbeat_check("stock"),
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=ET),
        id="bot_heartbeat_stock_rth",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: _run_bot_heartbeat_check("crypto"),
        IntervalTrigger(hours=4),
        id="bot_heartbeat_crypto_4h",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered jobs bot_heartbeat (stock 5min RTH + crypto 4h)")

    # ------------------------------------------------------------------
    # COMMIT 10 — Watchlist staleness sweep (nightly 2 AM Central)
    # ------------------------------------------------------------------
    # Module-level run_watchlist_stale_sweep() is also called by the on-demand
    # POST /api/admin/watchlist/sweep-stale endpoint.
    scheduler.add_job(
        run_watchlist_stale_sweep,
        CronTrigger(hour=2, minute=0, timezone=pytz.timezone("America/Chicago")),
        id="watchlist_stale_sweep_nightly",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job watchlist_stale_sweep_nightly (02:00 CT)")

    # ------------------------------------------------------------------
    # COMMIT 13 — Cooldown re-entry storm detection (every 30 min during RTH)
    # ------------------------------------------------------------------
    def _run_cooldown_storm_check() -> None:
        try:
            from app.db.session import SessionLocal as _SL
            from sqlalchemy import text as _sql
            from app.services.discord import send_ops_alert as _alert

            db = _SL()
            try:
                rows = db.execute(_sql(
                    "SELECT a.profile_id, p.name AS bot_name, bt.symbol, "
                    "       COUNT(*) AS entries_4h "
                    "FROM bot_trades bt "
                    "JOIN bot_allocations a ON a.id = bt.allocation_id "
                    "JOIN bot_profiles p ON p.id = a.profile_id "
                    "WHERE bt.ts >= datetime('now','-4 hours') "
                    "  AND bt.side IN ('buy','short') "
                    "GROUP BY a.profile_id, bt.symbol "
                    "HAVING COUNT(*) > 2 "
                    "ORDER BY entries_4h DESC"
                )).fetchall()
                if not rows:
                    logger.info("[cooldown-storm] clean (no pairs > 2 entries in 4h)")
                    return
                storms = [(r[1], r[2], int(r[3])) for r in rows]
                fields = [
                    {"name": f"{name} / {sym}", "value": f"{n} entries in 4h", "inline": True}
                    for name, sym, n in storms[:10]
                ]
                _alert(
                    title="Cooldown re-entry storm detected",
                    message=f"{len(storms)} (bot, symbol) pair(s) opened > 2 positions in the last 4 hours.",
                    severity="warn",
                    source="bot_scheduler.cooldown_storm_check",
                    fields=fields,
                )
                logger.warning("[cooldown-storm] %d pairs flagged", len(storms))
            finally:
                db.close()
        except Exception as exc:
            logger.error("[cooldown-storm] check failed: %s", exc, exc_info=True)

    scheduler.add_job(
        _run_cooldown_storm_check,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/30", timezone=ET),
        id="cooldown_storm_check_rth",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job cooldown_storm_check_rth (every 30min RTH)")

    # ------------------------------------------------------------------
    # COMMIT 15 — Brain Graph edge decay TTL (nightly 3 AM ET)
    # ------------------------------------------------------------------
    # NOTE: The brain_edges table does NOT exist in the current schema. The
    # decay job is stubbed: it logs that the table is missing and exits.
    # When the Brain Graph subsystem ships its table (columns expected:
    # id, weight, updated_at) the body should be replaced with:
    #
    #   UPDATE brain_edges SET weight = weight * 0.95
    #     WHERE updated_at < datetime('now','-30 days') AND weight > 0.01;
    #   DELETE FROM brain_edges WHERE weight < 0.01;
    #
    # Registering the cron now keeps the scheduler shape stable and gives
    # us a single place to flip the implementation on when the table lands.
    def _run_brain_edge_decay() -> None:
        try:
            from app.db.session import SessionLocal as _SL
            from sqlalchemy import text as _sql

            db = _SL()
            try:
                # Check if brain_edges table exists. SQLite-portable check.
                exists_row = db.execute(_sql(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='brain_edges'"
                )).fetchone()
                if not exists_row:
                    logger.info(
                        "[brain-decay] brain_edges table does not exist yet — "
                        "decay job is a no-op until the Brain Graph subsystem ships."
                    )
                    return
                # When the table exists in the future, replace the no-op above
                # with the decay + delete SQL. Kept here for traceability.
                decay_result = db.execute(_sql(
                    "UPDATE brain_edges SET weight = weight * 0.95 "
                    "WHERE updated_at < datetime('now', '-30 days') AND weight > 0.01"
                ))
                decayed = getattr(decay_result, "rowcount", 0) or 0
                delete_result = db.execute(_sql(
                    "DELETE FROM brain_edges WHERE weight < 0.01"
                ))
                deleted = getattr(delete_result, "rowcount", 0) or 0
                db.commit()
                logger.warning(
                    "[brain-decay] decayed=%d deleted=%d", decayed, deleted,
                )
                if decayed or deleted:
                    try:
                        from app.services.discord import send_ops_alert as _alert
                        _alert(
                            title="Brain Graph edge decay sweep",
                            message=f"Decayed {decayed} edges (×0.95), deleted {deleted} (weight < 0.01).",
                            severity="info",
                            source="bot_scheduler.brain_edge_decay",
                        )
                    except Exception as exc:
                        logger.warning("[brain-decay] ops alert failed: %s", exc)
            finally:
                db.close()
        except Exception as exc:
            logger.error("[brain-decay] failed: %s", exc, exc_info=True)

    scheduler.add_job(
        _run_brain_edge_decay,
        CronTrigger(hour=3, minute=0, timezone=ET),
        id="brain_edge_decay_nightly",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job brain_edge_decay_nightly (03:00 ET) — stubbed until brain_edges ships")

    # ── Discipline threshold auto-promote (nightly 04:00 ET) ────────────────
    def _run_threshold_auto_promote() -> None:
        try:
            from app.db.session import SessionLocal
            from app.services.threshold_auto_promote import run_threshold_auto_promote
            _db = SessionLocal()
            try:
                result = run_threshold_auto_promote(_db)
                logger.warning(
                    "[threshold-auto-promote] done loose=%s tight=%s",
                    result.get("loose_count"), result.get("tight_count"),
                )
            finally:
                _db.close()
        except Exception as exc:
            logger.error("[threshold-auto-promote] failed: %s", exc, exc_info=True)

    scheduler.add_job(
        _run_threshold_auto_promote,
        CronTrigger(hour=4, minute=0, timezone=ET),
        id="threshold_auto_promote_nightly",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job threshold_auto_promote_nightly (04:00 ET)")

    # ── Phase 1 closed-loop learning: per-bot daily journal (04:00 UTC) ─────
    # NOTE: threshold_auto_promote_nightly runs at 04:00 ET (~08:00-09:00 UTC
    # depending on DST). This job runs at 04:00 UTC (midnight ET in EST) — no
    # real collision, but two nightly jobs run close together. Flagged in PR.
    def _run_daily_journal():
        import sentry_sdk
        from app.db.session import SessionLocal
        from app.jobs.daily_journal import run_daily_journal
        from datetime import datetime, timezone, timedelta
        target = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        db = SessionLocal()
        try:
            with sentry_sdk.start_transaction(
                op="daily_journal", name=f"daily_journal:{target.isoformat()}"
            ):
                sentry_sdk.set_tag("target_date", target.isoformat())
                result = run_daily_journal(db, target_date=target)
                logger.warning(
                    "[daily-journal] target=%s processed=%d written=%d errors=%d",
                    target,
                    result.get("bots_processed", 0),
                    result.get("rows_written", 0),
                    len(result.get("errors", [])),
                )
        except Exception as exc:
            logger.error("[daily-journal] job failed: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _run_daily_journal,
        CronTrigger(hour=4, minute=0, timezone=UTC),   # 04:00 UTC = midnight ET (ish, DST drift OK)
        id="daily_journal_nightly",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job daily_journal_nightly (04:00 UTC)")

    # ── Daily Strategy Lab Audit (04:30 UTC) ─────────────────────────────────
    # Runs 30 min after the journal job (04:00 UTC) so journal writes are
    # complete before the audit reads them. Wraps in Sentry transaction for
    # observability. READ-ONLY against bot_trades/positions/allocations.
    def _daily_audit_job_wrapper():
        import sentry_sdk
        from datetime import datetime, timezone
        from app.jobs.daily_strategy_lab_audit import run_daily_audit
        from app.db.session import SessionLocal
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with sentry_sdk.start_transaction(op="daily_audit", name=f"daily_audit:{date_str}"):
            db = SessionLocal()
            try:
                run_daily_audit(db)
            finally:
                db.close()

    scheduler.add_job(
        _daily_audit_job_wrapper,
        CronTrigger(hour=4, minute=30, timezone="UTC"),
        id="daily_strategy_lab_audit",
        name="daily_strategy_lab_audit",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job daily_strategy_lab_audit (04:30 UTC)")

    # ── Cash Floor passive rebalance ────────────────────────────────────────
    # Fires twice on RTH weekdays:
    #   09:35 ET — 5 min after market open, so first day's $100K deploys
    #              promptly into SPY/QQQ.
    #   15:50 ET — 10 min before close, daily rebalance to maintain 60/40.
    # Both runs respect CAPITAL_EXECUTE_ENABLED kill switch — if it's off,
    # the job logs the skip and exits without touching positions.
    def _run_cash_floor_rebalance(tag: str) -> None:
        import os as _os
        if _os.getenv("CAPITAL_EXECUTE_ENABLED", "false").strip().lower() != "true":
            logger.warning("[cash-floor:%s] skipped — CAPITAL_EXECUTE_ENABLED=false", tag)
            return
        try:
            from app.db.session import SessionLocal
            from app.db.models.bots import BotAllocation, BotProfile, BotPosition, BotTrade
            from app.services.cash_floor import propose_rebalance
            from app.services.friction import model_friction_cents
            from datetime import datetime as _dt, timezone as _tz
            _db = SessionLocal()
            try:
                cf_prof = _db.query(BotProfile).filter(BotProfile.name == "cash_floor").first()
                if cf_prof is None:
                    logger.warning("[cash-floor:%s] no cash_floor profile — skipped", tag)
                    return
                # Iterate all enabled cash_floor allocations across users
                for alloc in _db.query(BotAllocation).filter(
                    BotAllocation.profile_id == cf_prof.id,
                    BotAllocation.enabled.is_(True),
                ).all():
                    plan = propose_rebalance(_db)
                    now = _dt.now(_tz.utc)
                    for trade in plan.get("trades_to_place", []):
                        live_px = trade.get("limit_price_hint_usd") or 0
                        if live_px <= 0:
                            continue
                        symbol = trade["symbol"]
                        # ── SHIP 2 asset-class gate (path #5) ────────────────
                        try:
                            from app.services.asset_class_registry import validate_order
                            validate_order("cash_floor", symbol)
                        except RuntimeError as _acr_exc:
                            logger.error(
                                "[asset_class_gate:cash_floor] scheduler rebalance "
                                "BLOCKED %s: %s", symbol, _acr_exc,
                            )
                            continue
                        # ── end asset-class gate ─────────────────────────────
                        approx_dollars = float(trade["approx_dollars"])
                        qty = round(approx_dollars / live_px, 4)
                        if qty <= 0:
                            continue
                        fill_cents = int(round(live_px * 100))
                        friction = model_friction_cents("stock", qty, live_px)
                        side = trade["side"]
                        if side == "buy":
                            existing = _db.query(BotPosition).filter(
                                BotPosition.allocation_id == alloc.id,
                                BotPosition.symbol == symbol,
                                BotPosition.closed_at.is_(None),
                                BotPosition.quarantined_at.is_(None),
                            ).first()
                            if existing:
                                old_qty = float(existing.qty or 0)
                                old_cost = float(existing.avg_cost_cents or 0)
                                new_qty = old_qty + qty
                                existing.qty = new_qty
                                existing.avg_cost_cents = (
                                    ((old_qty * old_cost) + (qty * fill_cents)) / new_qty
                                    if new_qty > 0 else fill_cents
                                )
                                pos = existing
                            else:
                                pos = BotPosition(
                                    allocation_id=alloc.id, symbol=symbol, qty=qty,
                                    avg_cost_cents=fill_cents, side="long",
                                    opened_at=now, closed_at=None, is_paper=True,
                                    stop_price_usd=None, target_price_usd=None,
                                    trailing_stop_activated=False,
                                    origin="BROKER_FILL",  # m099 — cash_floor rebalance
                                )
                                _db.add(pos); _db.flush()
                            # 2026-08-07 sim-leak sweep: gate before write
                            from app.services.trade_write_gate import check_trade_write as _ctw_sched
                            _sched_gate = _ctw_sched(alpaca_order_id=None, source_path="bot_scheduler.cash_floor_rebalance")
                            if _sched_gate.blocked:
                                logger.warning(
                                    "[bot_scheduler.cash_floor_rebalance] WRITE BLOCKED %s reason=%s",
                                    symbol, _sched_gate.reason,
                                )
                                continue
                            from app.services.regime_tag import regime_tag_dict as _regime_tag_dict
                            _rt_sched = _regime_tag_dict(_db, source="bot_scheduler.cash_floor_rebalance")
                            _db.add(BotTrade(
                                allocation_id=alloc.id, symbol=symbol, side="buy",
                                qty=qty, fill_price_cents=fill_cents,
                                fees_cents=friction, ts=now, position_id=pos.id,
                                is_paper=True, expected_fill_cents=fill_cents,
                                slippage_bps=3.0, strategy="cash_floor",
                                origin="BROKER_FILL",  # m099 — cash_floor rebalance
                                **_rt_sched,
                            ))
                _db.commit()
                logger.warning("[cash-floor:%s] rebalance committed", tag)
            finally:
                _db.close()
        except Exception as exc:
            logger.error("[cash-floor:%s] failed: %s", tag, exc, exc_info=True)

    scheduler.add_job(
        lambda: _run_cash_floor_rebalance("open"),
        CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone=ET),
        id="cash_floor_open",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: _run_cash_floor_rebalance("close"),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=50, timezone=ET),
        id="cash_floor_close",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered jobs cash_floor_open (09:35 ET) + cash_floor_close (15:50 ET)")

    # Fleet EOD summary: gated by should_post_to_fund_updates — suppressed in quiet mode.
    # To re-enable: pass urgency="critical" to should_post_to_fund_updates, or remove gate.

    # ------------------------------------------------------------------
    # congress_data_refresh: daily at 7:00 AM ET (pre-market)
    # Fetches congressional disclosures via FMP Senate/House feeds (last 90 days).
    # ------------------------------------------------------------------
    def _refresh_congress_data() -> None:
        import asyncio as _asyncio
        from app.db.session import SessionLocal as _SessionLocal
        from app.services.smart_money.congress import fetch_and_upsert_congress as _fetch

        _db = _SessionLocal()
        try:
            result = _asyncio.run(_fetch(_db, days_back=90))
            logger.info("[congress-daily] refresh done: %s", result)
        except Exception as exc:
            logger.error("[congress-daily] refresh failed: %s", exc, exc_info=True)
        finally:
            _db.close()

    scheduler.add_job(
        _refresh_congress_data,
        CronTrigger(hour=7, minute=0, timezone=ET),
        id="congress_data_refresh",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    logger.warning(
        "[startup-trace] ALL BOT JOBS REGISTERED: stock_swing stock_day stock_lt "
        "crypto_swing crypto_day crypto_lt crypto_onchain "
        "crypto_quant_aggressive crypto_quant_scalper crypto_quant_mean_reversion "
        "options_income options_directional position_monitor dead_mans_switch "
        "quarantine_dupes_periodic daily_discord_digest strategy_scout_scan "
        "strategy_forge_scan signal_explain_pregen "
        "tsmom_multi_asset quality_factor value_quality crypto_meanrev_2163 earnings_nlp "
        "queen_morning(mon-only) queen_regime_alert_check "
        "risk_sentinel_premarket risk_sentinel_postclose "
        "data_quality_watcher operations(weekdays-only) "
        "defensive_halt_check resume_check compute_bot_stats "
        "macro_classification_daily(mon-only) daily_standup(mon-thu-sun) "
        "candidate_pipeline_daemon price_alert_monitor congress_data_refresh"
    )

    # ------------------------------------------------------------------
    # Startup: post pause banners to signal channels + "quiet mode active"
    # message to #daily-plan when DISCORD_SIGNAL_POSTING_ENABLED=false.
    # Fire once 30s after startup (enough time for DB to be ready).
    # ------------------------------------------------------------------
    def _post_quiet_mode_notice():
        import os as _os
        try:
            from app.services.discord_public import post_signal_channel_pause_banners, _signal_posting_enabled
            if _signal_posting_enabled():
                return
            post_signal_channel_pause_banners()
            # Post "Quiet mode active" to #daily-plan
            import httpx as _hx, subprocess as _sp
            ch_daily_plan = _os.getenv("DISCORD_CH_DAILY_PLAN", "").strip()
            bot_token = _os.getenv("DISCORD_BOT_TOKEN", "").strip()
            try:
                from app.config import settings as _s
                bot_token = _s.discord_bot_token or bot_token
            except Exception:
                pass
            if ch_daily_plan and bot_token:
                try:
                    sha = _sp.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=_sp.DEVNULL).decode().strip()
                except Exception:
                    sha = "unknown"
                content = (
                    f"📵 **Quiet mode active.** Signal channels paused. "
                    f"Agent schedule reduced per Brock's spec. Commit `{sha}`.\n"
                    f"Re-enable: set `DISCORD_SIGNAL_POSTING_ENABLED=true` in Railway."
                )
                try:
                    _hx.post(
                        f"https://discord.com/api/v10/channels/{ch_daily_plan}/messages",
                        headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                        json={"content": content},
                        timeout=8,
                    )
                    logger.warning("[quiet-mode] notice posted to #daily-plan")
                except Exception as exc:
                    logger.warning("[quiet-mode] #daily-plan post failed: %s", exc)
        except Exception as exc:
            logger.error("[quiet-mode] startup notice failed: %s", exc)

    scheduler.add_job(
        _post_quiet_mode_notice,
        "date",
        run_date=datetime.now(UTC),
        id="quiet_mode_startup_notice",
        replace_existing=True,
    )
