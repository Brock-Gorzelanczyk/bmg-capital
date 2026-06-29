from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.db.models import *  # noqa: F401,F403 — registers all models with Base.metadata
from app.db.models.monitoring import MonitoringResult, AuditLog, LoginAttempt  # noqa: F401
from app.db.models.notification_channels import NotificationChannel, NotificationSubscription, NotificationLog  # noqa: F401
from app.db.models.onchain import OnChainMetric  # noqa: F401
from app.db.models.discord_posts import DiscordSignalPost  # noqa: F401
from app.db.models.bot_config import BotConfigOverride, BotConfigAudit  # noqa: F401
from app.db.models.scout import UserScoutSetup, UserScoutSignal  # noqa: F401
from app.db.models.forge import UserForgeBot, UserForgeSignal  # noqa: F401
from app.db.models.pipeline import StrategyCandidate, BacktestRun, WfaRun, CandidateStateHistory  # noqa: F401
from app.db.models.quant_analytics import LivePerformanceAlert, DecaySignal, FactorAttribution, HrpRecommendedWeight  # noqa: F401
from app.db.models.ic_metrics import SignalIcMetric, SignalIcAlert  # noqa: F401
from app.db.models.price_alert import PriceAlert  # noqa: F401
from app.routers.chart_layouts import ChartLayout  # noqa: F401
from app.db.migration import run_migrations
from app.alpaca.stream import stream_manager
from app.screener.scheduler import scheduler, setup_scheduler
from app.ws.manager import connection_manager
from app.ws.router import router as ws_router
from app.routers import bars, screener, watchlist, portfolio, alerts, market, news, earnings, strategy, auth, backtest, research, paper, screens, learn, explain, options, notifications, discovery, onboarding, journal, journal_analytics, social, tiers, chart_drawings, support, recap, crypto, db_restore, crypto_strategy, defi, security, governance, bridge, copilot, workspace, workshop, monitoring, gdpr, net_worth, tax, estate, pods, rules, tlh, engagement, robo, autonomous, autopilot, playbook, founder, linked_accounts, voice_ai, daily_brief, deposit_match, referral, learn_earn, ipo, cfp, staking, dca_baskets, bots, strategy_lab, strategy_library, custom_bot, analyst, v2_shadow, smart_money, exams, admin, discipline, hypotheses, brain, tuning
from app.routers import strategy_workshop, price_alerts
from app.routers.admin_bots import router as admin_bots_router
from app.routers.sentinel import router as sentinel_router
from app.routers.dashboard import router as dashboard_router
from app.routers.allocation import router as allocation_router
from app.routers.trading_gate import router as trading_gate_router
from app.routers.blackouts import router as blackouts_router
from app.routers.scout import router as scout_router
from app.routers.forge import router as forge_router
from app.routers.performance import router as performance_router
from app.routers.markets import router as markets_router
from app.routers import symbols as symbols_router
from app.routers import chart_layouts as chart_layouts_router
from app.routers.leaderboard import router as leaderboard_router
from app.routers.learning import router as learning_router
from app.routers.candidates import router as candidates_router
from app.routers.walk_forward import router as walk_forward_router
from app.routers.cost import router as cost_router
from app.routers.ic import router as ic_router
from app.routers.fund_agents import router as fund_agents_router
from app.routers.fund import router as fund_router
from app.routers.proposals import router as proposals_router
from app.routers.budget_router import router as budget_router
from app.routers.research_feed import router as research_feed_router
from app.routers.admin_reconstruct import router as admin_reconstruct_router
from app.routers import notification_channels as notification_channels_router
from app.db.models.engagement import MarketChallenge, MarketChallengeAttempt, LeagueCohort, LeaguePoints  # noqa: F401

logger = logging.getLogger(__name__)


async def _startup_strategy_scan() -> None:
    """Run strategy automation for all users who haven't had a scan today."""
    # Never run automation on weekends — markets are closed
    if date.today().isoweekday() >= 6:
        logger.info("Startup strategy scan skipped — weekend")
        return

    from app.db.models.strategy import DailyEquitySnapshot
    from app.db.models.users import User
    from app.screener.daily_runner import run_daily_automation

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        if not users:
            logger.info("No users registered yet — skipping startup strategy scan")
            return
        user_ids_needing_scan = []
        for user in users:
            already_ran = db.query(DailyEquitySnapshot).filter(
                DailyEquitySnapshot.snapshot_date == date.today(),
                DailyEquitySnapshot.user_id == user.id,
            ).first()
            if not already_ran:
                user_ids_needing_scan.append(user.id)
    finally:
        db.close()

    if not user_ids_needing_scan:
        logger.info("Strategy automation already ran today for all users — skipping")
        return

    for user_id in user_ids_needing_scan:
        logger.info(f"Strategy automation: starting startup scan for user {user_id}…")
        try:
            result = await run_daily_automation(user_id=user_id)
            logger.info(f"Strategy startup scan complete for user {user_id}: {result}")
        except Exception as e:
            logger.error(f"Strategy startup scan failed for user {user_id}: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all database tables (no-op if they already exist)
    Base.metadata.create_all(bind=engine)
    # Add any missing columns to existing tables
    run_migrations(engine)

    # Seed strategy definitions (upserts — safe to run every boot)
    from app.services.strategy_registry import seed_strategy_definitions
    _seed_db = SessionLocal()
    try:
        seed_strategy_definitions(_seed_db)
    finally:
        _seed_db.close()

    # Seed bot profiles from YAML (upserts — safe to run every boot)
    from strategy_lab.seeds import seed_bot_profiles
    _seed_db2 = SessionLocal()
    try:
        seed_bot_profiles(_seed_db2)
    finally:
        _seed_db2.close()

    # Seed IMCP learning curriculum (no-op if tracks already exist)
    from app.seeds.learning_seed import seed_learning_content
    _seed_db3 = SessionLocal()
    try:
        seed_learning_content(_seed_db3)
    finally:
        _seed_db3.close()

    # Seed exam questions (only if fewer than 60 exist)
    from app.seeds.exam_seed import seed_exam_questions
    from app.db.models.exams import ExamQuestion
    _seed_exam_db = SessionLocal()
    try:
        q_count = _seed_exam_db.query(ExamQuestion).count()
        if q_count < 60:
            seed_exam_questions(_seed_exam_db)
    except Exception as _exam_seed_exc:
        logger.warning("[startup] exam_seed failed (non-fatal): %s", _exam_seed_exc)
    finally:
        _seed_exam_db.close()

    # Seed example workshop charts for user_id=1 (non-fatal — idempotent)
    try:
        from app.routers.strategy_workshop import startup_seed_workshop_examples
        _seed_workshop_db = SessionLocal()
        try:
            startup_seed_workshop_examples(_seed_workshop_db)
        finally:
            _seed_workshop_db.close()
    except Exception as _workshop_seed_exc:
        logger.warning("[startup] workshop_charts seed failed (non-fatal): %s", _workshop_seed_exc)

    # Ensure bot_paper_accounts table + crypto_quant_aggressive $100k sub-account row
    # (non-fatal — same idempotent pattern as learning_seed)
    try:
        from app.db.migrations.m001_bot_paper_accounts import run as _run_m001
        with engine.connect() as _m001_conn:
            _run_m001(_m001_conn)
    except Exception as _m001_exc:
        logger.warning("[startup] m001_bot_paper_accounts failed (non-fatal): %s", _m001_exc)

    # Seed all 12 production bots at T2 PRODUCTION (one-time, idempotent)
    try:
        from app.db.migrations.m002_seed_bots_t2_v1 import run as _run_m002
        with engine.connect() as _m002_conn:
            _run_m002(_m002_conn)
    except Exception as _m002_exc:
        logger.warning("[startup] m002_seed_bots_t2_v1 failed (non-fatal): %s", _m002_exc)

    try:
        from app.db.migrations.m003_quant_research import run as _run_m003
        with engine.connect() as _m003_conn:
            _run_m003(_m003_conn)
    except Exception as _m003_exc:
        logger.warning("[startup] m003_quant_research failed (non-fatal): %s", _m003_exc)

    # Pause T0 incubation bots that incorrectly received capital (crypto_meanrev_2163 et al.)
    try:
        from app.db.migrations.m004_pause_t0_violations import run as _run_m004
        with engine.connect() as _m004_conn:
            _run_m004(_m004_conn)
    except Exception as _m004_exc:
        logger.warning("[startup] m004_pause_t0_violations failed (non-fatal): %s", _m004_exc)

    # Seed system paper allocations for all production bots (options_income, options_directional, etc.)
    try:
        from app.db.migrations.m004_seed_system_allocations import run as _run_m004_alloc
        with engine.connect() as _m004_alloc_conn:
            _run_m004_alloc(_m004_alloc_conn)
    except Exception as _m004_alloc_exc:
        logger.warning("[startup] m004_seed_system_allocations failed (non-fatal): %s", _m004_alloc_exc)

    # Add options-specific columns to bot_positions and bot_trades (idempotent)
    try:
        from app.db.migrations.m005_options_fields import run as _run_m005
        with engine.connect() as _m005_conn:
            _run_m005(_m005_conn)
    except Exception as _m005_exc:
        logger.warning("[startup] m005_options_fields failed (non-fatal): %s", _m005_exc)

    try:
        from app.db.migrations.m006_reenable_stalled_production_bots import run as _run_m006
        with engine.connect() as _m006_conn:
            _run_m006(_m006_conn)
    except Exception as _m006_exc:
        logger.warning("[startup] m006_reenable_stalled_production_bots failed (non-fatal): %s", _m006_exc)

    try:
        from app.db.migrations.m007_unlock_crypto_day import run as _run_m007
        with engine.connect() as _m007_conn:
            _run_m007(_m007_conn)
    except Exception as _m007_exc:
        logger.warning("[startup] m007_unlock_crypto_day failed (non-fatal): %s", _m007_exc)

    try:
        from app.db.migrations.m008_backfill_nav_history import run as _run_m008
        with engine.connect() as _m008_conn:
            _run_m008(_m008_conn)
    except Exception as _m008_exc:
        logger.warning("[startup] m008_backfill_nav_history failed (non-fatal): %s", _m008_exc)

    try:
        from app.db.migrations.m009_agent_conversation_log import run as _run_m009
        with engine.connect() as _m009_conn:
            _run_m009(_m009_conn)
    except Exception as _m009_exc:
        logger.warning("[startup] m009_agent_conversation_log failed (non-fatal): %s", _m009_exc)

    try:
        from app.db.migrations.m010_quarantine_legacy_options import run as _run_m010
        with engine.connect() as _m010_conn:
            _run_m010(_m010_conn)
    except Exception as _m010_exc:
        logger.warning("[startup] m010_quarantine_legacy_options failed (non-fatal): %s", _m010_exc)

    try:
        from app.db.migrations.m011_quarantine_legacy_options_trades import run as _run_m011
        with engine.connect() as _m011_conn:
            _run_m011(_m011_conn)
    except Exception as _m011_exc:
        logger.warning("[startup] m011_quarantine_legacy_options_trades failed (non-fatal): %s", _m011_exc)

    try:
        from app.db.migrations.m012_quarantine_misrouted_share_orders import run as _run_m012
        with engine.connect() as _m012_conn:
            _run_m012(_m012_conn)
    except Exception as _m012_exc:
        logger.warning("[startup] m012_quarantine_misrouted_share_orders failed (non-fatal): %s", _m012_exc)

    try:
        from app.db.migrations.m013_fix_smart_money_congress_id import run as _run_m013
        with engine.connect() as _m013_conn:
            _run_m013(_m013_conn)
    except Exception as _m013_exc:
        logger.warning("[startup] m013_fix_smart_money_congress_id failed (non-fatal): %s", _m013_exc)

    try:
        from app.db.migrations.m014_signal_gates import run as _run_m014
        with engine.connect() as _m014_conn:
            _run_m014(_m014_conn)
    except Exception as _m014_exc:
        logger.warning("[startup] m014_signal_gates failed (non-fatal): %s", _m014_exc)

    try:
        from app.db.migrations.m015_hypotheses import run as _run_m015
        with engine.connect() as _m015_conn:
            _run_m015(_m015_conn)
    except Exception as _m015_exc:
        logger.warning("[startup] m015_hypotheses failed (non-fatal): %s", _m015_exc)

    try:
        from app.db.migrations.m016_add_bot_health_status import run as _run_m016
        with engine.connect() as _m016_conn:
            _run_m016(_m016_conn)
    except Exception as _m016_exc:
        logger.warning("[startup] m016_add_bot_health_status failed (non-fatal): %s", _m016_exc)

    try:
        from app.db.migrations.m017_disable_incubating_allocations import run as _run_m017
        with engine.connect() as _m017_conn:
            _run_m017(_m017_conn)
    except Exception as _m017_exc:
        logger.warning("[startup] m017_disable_incubating_allocations failed (non-fatal): %s", _m017_exc)

    try:
        from app.db.migrations.m018_add_bot_heartbeat import run as _run_m018
        with engine.connect() as _m018_conn:
            _run_m018(_m018_conn)
    except Exception as _m018_exc:
        logger.warning("[startup] m018_add_bot_heartbeat failed (non-fatal): %s", _m018_exc)

    try:
        from app.db.migrations.m019_add_modeled_fees_cents import run as _run_m019
        with engine.connect() as _m019_conn:
            _run_m019(_m019_conn)
    except Exception as _m019_exc:
        logger.warning("[startup] m019_add_modeled_fees_cents failed (non-fatal): %s", _m019_exc)

    try:
        from app.db.migrations.m020_add_bot_threshold_dynamic import run as _run_m020
        with engine.connect() as _m020_conn:
            _run_m020(_m020_conn)
    except Exception as _m020_exc:
        logger.warning("[startup] m020_add_bot_threshold_dynamic failed (non-fatal): %s", _m020_exc)

    try:
        from app.db.migrations.m021_merge_and_resize_allocations import run as _run_m021
        with engine.connect() as _m021_conn:
            _run_m021(_m021_conn)
    except Exception as _m021_exc:
        logger.warning("[startup] m021_merge_and_resize_allocations failed (non-fatal): %s", _m021_exc)

    try:
        from app.db.migrations.m023_add_inception_capital_cents import run as _run_m023
        with engine.connect() as _m023_conn:
            _run_m023(_m023_conn)
    except Exception as _m023_exc:
        logger.warning("[startup] m023_add_inception_capital_cents failed (non-fatal): %s", _m023_exc)

    try:
        from app.db.migrations.m024_corrective_capital_reset import run as _run_m024
        with engine.connect() as _m024_conn:
            _m024_result = _run_m024(_m024_conn)
        logger.warning("[startup] m024 OK: %s", _m024_result)
    except Exception as _m024_exc:
        # exc_info=True so the FULL traceback lands in Railway logs.
        # Migrations failing silently was the root cause of the
        # 2026-06-27 $1.7M divergence — never make a migration failure
        # quiet again.
        logger.error("[startup] m024_corrective_capital_reset FAILED: %s", _m024_exc, exc_info=True)

    try:
        from app.db.migrations.m025_clean_slate_one_million import run as _run_m025
        with engine.connect() as _m025_conn:
            _m025_result = _run_m025(_m025_conn)
        logger.warning("[startup] m025 OK: %s", _m025_result)
    except Exception as _m025_exc:
        logger.error("[startup] m025_clean_slate_one_million FAILED: %s", _m025_exc, exc_info=True)

    try:
        from app.db.migrations.m026_disable_non_spec_allocations import run as _run_m026
        with engine.connect() as _m026_conn:
            _m026_result = _run_m026(_m026_conn)
        logger.warning("[startup] m026 OK: %s", _m026_result)
    except Exception as _m026_exc:
        logger.error("[startup] m026_disable_non_spec_allocations FAILED: %s", _m026_exc, exc_info=True)

    try:
        from app.db.migrations.m027_force_clean_slate import run as _run_m027
        with engine.connect() as _m027_conn:
            _m027_result = _run_m027(_m027_conn)
        logger.warning("[startup] m027 OK: %s", _m027_result)
    except Exception as _m027_exc:
        logger.error("[startup] m027_force_clean_slate FAILED: %s", _m027_exc, exc_info=True)

    try:
        from app.db.migrations.m028_quarantine_cross_sleeve import run as _run_m028
        with engine.connect() as _m028_conn:
            _m028_result = _run_m028(_m028_conn)
        logger.warning("[startup] m028 OK: %s", _m028_result)
    except Exception as _m028_exc:
        logger.error("[startup] m028_quarantine_cross_sleeve FAILED: %s", _m028_exc, exc_info=True)

    try:
        from app.db.migrations.m030_inception_snapshot_on_daily_pnl import run as _run_m030
        with engine.connect() as _m030_conn:
            _m030_result = _run_m030(_m030_conn)
        logger.warning("[startup] m030 OK: %s", _m030_result)
    except Exception as _m030_exc:
        logger.error("[startup] m030_inception_snapshot_on_daily_pnl FAILED: %s", _m030_exc, exc_info=True)

    # PART 2 (Layer 1+3): close equity positions held by options bots and
    # PAUSE both options bots so they stop emitting equity signals until
    # their strategies are redesigned to emit OCC option symbols.
    try:
        from app.db.migrations.m033_close_options_bot_equity_violations import run as _run_m033
        with engine.connect() as _m033_conn:
            _m033_result = _run_m033(_m033_conn)
        logger.warning("[startup] m033 OK: %s", _m033_result)
    except Exception as _m033_exc:
        logger.error("[startup] m033_close_options_bot_equity_violations FAILED: %s", _m033_exc, exc_info=True)

    # Boot-time track-record reconstruction (SHIP 3): insert markers for any
    # enabled allocation that has zero bot_daily_pnl rows post-m027 wipe.
    # Runs ONCE per deploy, after m030, before first canonical read.
    # DO NOT call reconstruct_for_user from any scheduler or per-request path.
    try:
        from app.services.track_record_reconstruction import reconstruct_for_user as _reconstruct_for_user
        _recon_db = SessionLocal()
        try:
            _recon_result = _reconstruct_for_user(user_id=1, db=_recon_db)
            logger.warning("[startup] track_record_reconstruction OK: %s", _recon_result)
        finally:
            _recon_db.close()
    except Exception as _recon_exc:
        logger.error("[startup] track_record_reconstruction FAILED (non-fatal): %s", _recon_exc, exc_info=True)

    # Register the capital audit ORM listener AFTER m027 runs so its initial
    # writes don't spam the audit log. Listener catches every subsequent
    # ORM-level write to bot_allocations capital fields, proving the
    # auto-grow kill in routers/bots.py:_ensure_portfolios_for_user holds.
    try:
        from app.services.capital_audit import register_capital_audit_listener
        register_capital_audit_listener()
    except Exception as _audit_exc:
        logger.error("[startup] capital_audit listener FAILED to register: %s",
                     _audit_exc, exc_info=True)

    # Run capital invariant check on boot — logs OK/WARN/CRIT and posts to
    # ops Discord on drift. Scheduler also runs this every 5 min (see
    # screener/scheduler.py).
    try:
        from app.services.capital_invariant import run_check_with_session
        run_check_with_session(user_id=1)
    except Exception as _inv_exc:
        logger.error("[startup] capital_invariant boot check failed: %s",
                     _inv_exc, exc_info=True)

    # Seed hypotheses from strategy_definitions (idempotent — adds only new entries)
    try:
        from app.services.hypotheses import seed_hypotheses_from_strategies as _seed_hyp
        _hyp_db = SessionLocal()
        try:
            _seed_hyp(_hyp_db)
        finally:
            _hyp_db.close()
    except Exception as _hyp_seed_exc:
        logger.warning("[startup] hypotheses seed failed (non-fatal): %s", _hyp_seed_exc)

    # Seed smart_money_congress if table is empty (non-fatal — network may be down)
    from app.db.models.smart_money import SmartMoneyCongressTrade
    _smc_db = SessionLocal()
    try:
        smc_count = _smc_db.query(SmartMoneyCongressTrade).count()
        if smc_count == 0:
            from app.services.smart_money.congress import fetch_and_upsert_congress

            async def _seed_congress():
                _seed_smc_db = SessionLocal()
                try:
                    result = await fetch_and_upsert_congress(_seed_smc_db, days_back=30)
                    logger.info("[startup] smart_money_congress seeded: %s", result)
                except Exception as _e:
                    logger.warning("[startup] smart_money_congress seed failed (non-fatal): %s", _e)
                finally:
                    _seed_smc_db.close()

            asyncio.create_task(_seed_congress())
        else:
            logger.info("[startup] smart_money_congress already has %d rows — skipping seed", smc_count)
    except Exception as _e:
        logger.warning("[startup] smart_money_congress seed check failed (non-fatal): %s", _e)
    finally:
        _smc_db.close()

    # Wire Alpaca stream events to connected WebSocket clients
    stream_manager.on_quote(connection_manager.send_to_symbol_subscribers)
    stream_manager.on_bar(connection_manager.send_to_symbol_subscribers)

    # Start the live data stream and background scheduler
    await stream_manager.start()
    setup_scheduler()
    from app.routers.monitoring import setup_monitoring_scheduler
    setup_monitoring_scheduler(scheduler)
    logger.warning("[startup-trace] calling setup_bot_scheduler")
    from strategy_lab.bot_scheduler import setup_bot_scheduler
    setup_bot_scheduler(scheduler)
    logger.warning("[startup-trace] setup_bot_scheduler returned")
    from app.services.onchain_ingest import setup_onchain_scheduler
    setup_onchain_scheduler(scheduler)
    scheduler.start()

    # Kick off strategy scan in background — won't block server startup
    asyncio.create_task(_startup_strategy_scan())

    # Health check: warn if ANTHROPIC_API_KEY is missing — AI features degrade gracefully
    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning(
            "ANTHROPIC_API_KEY not set — AI features degraded. "
            "Set in Railway environment variables."
        )

    # Sentinel — startup heartbeat + internal tick loop + Railway watcher
    from app.services.sentinel_monitor import (
        log_config as _sentinel_log_config,
        send_startup_heartbeat as _sentinel_startup,
        sentinel_loop as _sentinel_loop,
        railway_watcher_loop as _railway_watcher_loop,
    )
    _sentinel_log_config()
    asyncio.create_task(asyncio.to_thread(_sentinel_startup))
    asyncio.create_task(_sentinel_loop())
    asyncio.create_task(_railway_watcher_loop())

    # One-time intro conversation — fires if #fund-team-chat webhook is set and never run before
    async def _maybe_run_intro():
        import asyncio as _aio
        await _aio.sleep(15)  # wait for scheduler + agents to settle
        try:
            from agents.intro_conversation import has_run_intro, run_intro_conversation as _run_intro
            from app.dependencies import get_db as _get_db
            _db = next(_get_db())
            try:
                if not has_run_intro(_db):
                    logger.info("[startup] firing first-run intro conversation")
                    await _aio.to_thread(_run_intro, _db)
            finally:
                _db.close()
        except Exception as _exc:
            logger.warning("[startup] intro conversation failed (non-fatal): %s", _exc)
    asyncio.create_task(_maybe_run_intro())

    # Post-deploy synthetic pipeline check — fires 60s after startup so scheduler is warm
    async def _post_deploy_synthetic_check():
        import asyncio as _aio
        await _aio.sleep(60)
        try:
            from strategy_lab.agents.strategy_monitor import _check_bot_windows
            from app.dependencies import get_db as _get_db
            _db = next(_get_db())
            try:
                rows = _check_bot_windows(_db)
                red   = [r["bot"] for r in rows if r.get("pipeline_health") == "RED"    and r.get("pipeline_health") != "DISABLED"]
                yellow = [r["bot"] for r in rows if r.get("pipeline_health") == "YELLOW" and r.get("pipeline_health") != "DISABLED"]
                green  = [r["bot"] for r in rows if r.get("pipeline_health") == "GREEN"]
                logger.warning(
                    "[post-deploy-check] pipeline health: %d GREEN, %d YELLOW, %d RED — RED=%s YELLOW=%s",
                    len(green), len(yellow), len(red), red, yellow,
                )
                if red:
                    try:
                        from app.services.discord import post_embed_to_channel
                        import os as _os
                        ch = _os.getenv("DISCORD_CH_BMG_MONITORING") or _os.getenv("DISCORD_CH_DEV_LOG")
                        token = _os.getenv("DISCORD_BOT_TOKEN", "")
                        if ch and token:
                            embed = {
                                "title": f"🚨 Post-Deploy Health Check — {len(red)} RED bot(s)",
                                "color": 0xEF4444,
                                "fields": [
                                    {"name": "RED", "value": ", ".join(red), "inline": False},
                                    {"name": "YELLOW", "value": ", ".join(yellow) or "none", "inline": False},
                                    {"name": "GREEN", "value": str(len(green)), "inline": True},
                                ],
                                "footer": {"text": "post-deploy synthetic check · auto-fired 60s after startup"},
                            }
                            import httpx as _httpx
                            _httpx.post(
                                f"https://discord.com/api/v10/channels/{ch}/messages",
                                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                                         "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)"},
                                json={"embeds": [embed]}, timeout=8,
                            )
                    except Exception as _disc_exc:
                        logger.debug("[post-deploy-check] discord notify failed: %s", _disc_exc)
            finally:
                _db.close()
        except Exception as _exc:
            logger.warning("[post-deploy-check] failed (non-fatal): %s", _exc)

    asyncio.create_task(_post_deploy_synthetic_check())

    yield

    # Graceful shutdown
    await stream_manager.stop()
    scheduler.shutdown()


app = FastAPI(
    title="BMG Capital API",
    version="1.0.0",
    lifespan=lifespan,
)

class AgentReadOnlyMiddleware(BaseHTTPMiddleware):
    """Block non-GET requests when the agent-fleet service token is used."""
    async def dispatch(self, request: Request, call_next):
        import os as _os
        agent_token = _os.getenv("AGENT_APP_AUTH_TOKEN", "")
        if agent_token:
            auth = request.headers.get("Authorization", "")
            if auth == f"Bearer {agent_token}" and request.method != "GET":
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Agent fleet token is read-only — GET requests only"},
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # SAMEORIGIN (not DENY) — still blocks clickjacking from external sites
        # but allows our /intro page to embed itself in an iframe.
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AgentReadOnlyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(ws_router)
app.include_router(auth.router)
app.include_router(bars.router)
app.include_router(screener.router)
app.include_router(watchlist.router)
app.include_router(portfolio.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(news.router)
app.include_router(earnings.router)
app.include_router(strategy.router)
app.include_router(backtest.router)
app.include_router(research.router)
# paper.router removed — tables archived 2026-06-06
app.include_router(screens.router)
app.include_router(learn.router)
app.include_router(learning_router)
app.include_router(explain.router)
app.include_router(options.router)
app.include_router(notifications.router)
app.include_router(discovery.router)
app.include_router(onboarding.router)
app.include_router(journal.router)
app.include_router(journal_analytics.router)
app.include_router(social.router)
app.include_router(engagement.router)
app.include_router(tiers.router)
app.include_router(chart_drawings.router)
app.include_router(support.router)
app.include_router(recap.router)
app.include_router(crypto.router)
app.include_router(crypto_strategy.router)
app.include_router(defi.router)
app.include_router(security.router)
app.include_router(governance.router)
app.include_router(bridge.router)
app.include_router(db_restore.router)
app.include_router(copilot.router)
app.include_router(workspace.router)
app.include_router(workshop.router)
app.include_router(strategy_workshop.router)
app.include_router(price_alerts.router)
app.include_router(monitoring.router)
app.include_router(autonomous.router)
app.include_router(gdpr.router)
app.include_router(net_worth.router)
app.include_router(tax.router)
app.include_router(estate.router)
app.include_router(pods.router)
app.include_router(rules.router)
app.include_router(rules.transfers_router)
app.include_router(tlh.router)
app.include_router(robo.router)
app.include_router(autopilot.router)
app.include_router(playbook.router)
app.include_router(founder.router)
app.include_router(linked_accounts.router)
app.include_router(voice_ai.router)
app.include_router(daily_brief.router)
app.include_router(deposit_match.router)
app.include_router(referral.router)
app.include_router(learn_earn.router)
app.include_router(ipo.router)
app.include_router(cfp.router)
app.include_router(staking.router)
app.include_router(dca_baskets.router)
app.include_router(allocation_router)
app.include_router(trading_gate_router)
app.include_router(blackouts_router)
app.include_router(bots.router)
app.include_router(strategy_lab.router)
app.include_router(notification_channels_router.router)
app.include_router(strategy_library.router)
app.include_router(custom_bot.router)
app.include_router(analyst.router)
app.include_router(v2_shadow.router)
app.include_router(smart_money.router)
app.include_router(discipline.router)
app.include_router(hypotheses.router)
app.include_router(brain.router)
app.include_router(tuning.router)
app.include_router(exams.router)
app.include_router(exams.verify_router)
app.include_router(admin.router)
from app.routers.concentration import router as concentration_router
app.include_router(concentration_router)
from app.routers.allocator import router as allocator_router
app.include_router(allocator_router)
from app.routers.capital_execute import router as capital_execute_router
app.include_router(capital_execute_router)
from app.routers.friction import router as friction_router
app.include_router(friction_router)
from app.routers.cash_floor import router as cash_floor_router
app.include_router(cash_floor_router)
from app.routers.clean_slate import router as clean_slate_router
app.include_router(clean_slate_router)
app.include_router(admin_bots_router)
from app.routers.admin_quarantine import router as admin_quarantine_router
app.include_router(admin_quarantine_router)
app.include_router(sentinel_router)
app.include_router(dashboard_router)
app.include_router(scout_router)
app.include_router(forge_router)
app.include_router(performance_router)
app.include_router(markets_router)
app.include_router(symbols_router.router)
app.include_router(chart_layouts_router.router)
app.include_router(leaderboard_router)
app.include_router(candidates_router)
app.include_router(walk_forward_router)
app.include_router(cost_router)
app.include_router(ic_router)
app.include_router(fund_agents_router)
app.include_router(fund_router)
app.include_router(proposals_router)
app.include_router(budget_router)
app.include_router(research_feed_router)
app.include_router(admin_reconstruct_router)


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health():
    """Simple liveness check."""
    return {"status": "ok"}


# Serve the Vite frontend build (production only — skipped if dist/ doesn't exist)
_STATIC_DIR = Path(__file__).parent.parent / "static"
if _STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Serve real static files (logo.png, favicon.ico, manifest.json, etc.)
        candidate = _STATIC_DIR / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        # SPA index — must never be cached so chunk hashes always match
        return FileResponse(
            str(_STATIC_DIR / "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
