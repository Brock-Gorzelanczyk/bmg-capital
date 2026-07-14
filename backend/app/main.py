from __future__ import annotations

import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

if os.environ.get("SENTRY_DSN_BACKEND"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN_BACKEND"],
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.05,
        environment=os.environ.get("RAILWAY_ENVIRONMENT", "production"),
        release=os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown"),
        before_send=lambda event, hint: None if (
            event.get("transaction", "").startswith("/api/admin/")
            and event.get("contexts", {}).get("response", {}).get("status_code") == 401
        ) else event,
    )

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
from app.db.models.bot_daily_journal import BotDailyJournal  # noqa: F401
from app.db.models.daily_audit import DailyAuditLog  # noqa: F401
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
from app.routers.pnl import router as pnl_router
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

    # SHIP 4: m031 anthropic_call_cache (cost-tracking cache table).
    try:
        from app.db.migrations.m031_anthropic_call_cache import run as _run_m031
        with engine.connect() as _m031_conn:
            _m031_result = _run_m031(_m031_conn)
        logger.warning("[startup] m031 OK: %s", _m031_result)
    except Exception as _m031_exc:
        logger.error("[startup] m031_anthropic_call_cache FAILED: %s", _m031_exc, exc_info=True)

    # SHIP 4: m032 llm_call_log (per-callsite cost ledger).
    try:
        from app.db.migrations.m032_llm_call_log import run as _run_m032
        with engine.connect() as _m032_conn:
            _m032_result = _run_m032(_m032_conn)
        logger.warning("[startup] m032 OK: %s", _m032_result)
    except Exception as _m032_exc:
        logger.error("[startup] m032_llm_call_log FAILED: %s", _m032_exc, exc_info=True)

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

    # SHIP 6: m038 bot_symbol_cooldown table (24h clamp per bot+symbol).
    try:
        from app.db.migrations.m038_bot_symbol_cooldown import run as _run_m038
        with engine.connect() as _m038_conn:
            _m038_result = _run_m038(_m038_conn)
        logger.warning("[startup] m038 OK: %s", _m038_result)
    except Exception as _m038_exc:
        logger.error("[startup] m038_bot_symbol_cooldown FAILED: %s", _m038_exc, exc_info=True)

    # m044: close LEGACY equity positions on crypto bots that survived
    # m027 (no position close) and m033 (options-bot scope only). Companion
    # to m033 — same close + quarantine + exit BotTrade pattern.
    try:
        from app.db.migrations.m044_close_crypto_bot_equity_violations import run as _run_m044
        with engine.connect() as _m044_conn:
            _m044_result = _run_m044(_m044_conn)
        logger.warning("[startup] m044 OK: %s", _m044_result)
    except Exception as _m044_exc:
        logger.error("[startup] m044_close_crypto_bot_equity_violations FAILED: %s", _m044_exc, exc_info=True)

    # m045: close LEGACY crypto-bot equity violations that m044 left behind
    # (m044's WHERE a.user_id = :uid filter missed positions owned by
    # user_id != 1). Uses engine.begin() for explicit transaction semantics
    # and verifies post-run that zero violations remain.
    try:
        from app.db.migrations.m045_close_remaining_crypto_equity_violations import run as _run_m045
        with engine.begin() as _m045_conn:
            _m045_result = _run_m045(_m045_conn)
        logger.warning("[startup] m045 OK: %s", _m045_result)
    except Exception as _m045_exc:
        logger.error(
            "[startup] m045_close_remaining_crypto_equity_violations FAILED: %s",
            _m045_exc,
            exc_info=True,
        )

    # m046: force-close fund_meetings rows stuck in status='running' for >30 minutes.
    # NO _gate; runs every boot. Catches pre-PR-#25 sync-orphan rows that the
    # asyncio watchdog in cio_meeting_runner cannot reach.
    try:
        from app.db.migrations.m046_force_kill_stuck_running_meetings import run as _run_m046
        with engine.begin() as _m046_conn:
            _m046_result = _run_m046(_m046_conn)
        logger.warning("[startup] m046 OK: %s", _m046_result)
    except Exception as _m046_exc:
        logger.error(
            "[startup] m046_force_kill_stuck_running_meetings FAILED: %s",
            _m046_exc,
            exc_info=True,
        )

    # m047: create bot_daily_journals table (Phase 1 closed-loop learning system).
    # Idempotent CREATE TABLE IF NOT EXISTS — safe to run every boot.
    try:
        from app.db.migrations.m047_bot_daily_journals import run as _run_m047
        with engine.begin() as _m047_conn:
            _m047_result = _run_m047(_m047_conn)
        logger.warning("[startup] m047 OK: %s", _m047_result)
    except Exception as _m047_exc:
        logger.error(
            "[startup] m047_bot_daily_journals FAILED: %s",
            _m047_exc,
            exc_info=True,
        )

    # m048: create aqa_state + aqa_proposals tables (Phase A autonomous quant agent).
    # Idempotent CREATE TABLE IF NOT EXISTS — safe to run every boot.
    try:
        from app.db.migrations.m048_aqa_state import run as _run_m048
        with engine.begin() as _m048_conn:
            _m048_result = _run_m048(_m048_conn)
        logger.warning("[startup] m048 OK: %s", _m048_result)
    except Exception as _m048_exc:
        logger.error(
            "[startup] m048_aqa_state FAILED: %s",
            _m048_exc,
            exc_info=True,
        )

    # m049: add regime tagging columns to bot_trades (Phase 2 closed-loop learning).
    # Idempotent ALTER + CREATE INDEX. Safe to run every boot.
    try:
        from app.db.migrations.m049_regime_tagging import run as _run_m049
        with engine.begin() as _m049_conn:
            _m049_result = _run_m049(_m049_conn)
        logger.warning("[startup] m049 OK: %s", _m049_result)
    except Exception as _m049_exc:
        logger.error("[startup] m049_regime_tagging FAILED: %s", _m049_exc, exc_info=True)

    # m050: create daily_audit_log table (daily Strategy Lab audit job).
    # Idempotent CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS. Safe to run every boot.
    try:
        from app.db.migrations.m050_daily_audit_log import upgrade as m050_upgrade
        _m050_db = SessionLocal()
        try:
            m050_upgrade(_m050_db)
        finally:
            _m050_db.close()
    except Exception as _m050_exc:
        logger.error("[startup] m050_daily_audit_log FAILED: %s", _m050_exc, exc_info=True)

    # m051: halt scanners for confirmed-loser Quant bots (Mean Rev + Scalper).
    # Gated via _gate.already_ran so operators can re-enable later without
    # this migration silently re-disabling them on the next boot.
    try:
        from app.db.migrations.m051_halt_quant_losers import run as _run_m051
        with engine.begin() as _m051_conn:
            _m051_result = _run_m051(_m051_conn)
        logger.warning("[startup] m051 OK: %s", _m051_result)
    except Exception as _m051_exc:
        logger.error("[startup] m051_halt_quant_losers FAILED: %s", _m051_exc, exc_info=True)

    # m052: reallocate $100k from halted quant bots to 3 new bots (alt_focus,
    # scalp_1m, dca_btc_eth). Must run AFTER seed_bot_profiles (line 154 above)
    # so the new BotProfile rows exist before we allocate against them.
    # Gated via _gate — one-shot per DB.
    try:
        from app.db.migrations.m052_reallocate_to_new_quant_bots import run as _run_m052
        with engine.begin() as _m052_conn:
            _m052_result = _run_m052(_m052_conn)
        logger.warning("[startup] m052 OK: %s", _m052_result)
    except Exception as _m052_exc:
        logger.error("[startup] m052_reallocate_to_new_quant_bots FAILED: %s", _m052_exc, exc_info=True)

    # m053: allocate 5 more quant bots (universe_top6, defi_l2, meme_tier,
    # 10m, 15m). Same self-balancing pattern as m052 — invariant pulled from
    # crypto_quant_aggressive so total stays at $1M exactly. Runs AFTER m052
    # so the aggregate has the latest state.
    try:
        from app.db.migrations.m053_seed_five_more_quant_bots import run as _run_m053
        with engine.begin() as _m053_conn:
            _m053_result = _run_m053(_m053_conn)
        logger.warning("[startup] m053 OK: %s", _m053_result)
    except Exception as _m053_exc:
        logger.error("[startup] m053_seed_five_more_quant_bots FAILED: %s", _m053_exc, exc_info=True)

    # m054: rescue crypto_quant_aggressive from the $10k m053 left it at.
    # Drains $90k from idle cash_floor (which needs CAPITAL_EXECUTE_ENABLED
    # env var Brock hasn't set) and pushes it into the only profitable bot.
    # Gated + safety-checked so it can't run if someone manually rebalanced.
    try:
        from app.db.migrations.m054_restore_aggressive_from_cash_floor import run as _run_m054
        with engine.begin() as _m054_conn:
            _m054_result = _run_m054(_m054_conn)
        logger.warning("[startup] m054 OK: %s", _m054_result)
    except Exception as _m054_exc:
        logger.error("[startup] m054_restore_aggressive_from_cash_floor FAILED: %s", _m054_exc, exc_info=True)

    # m055: undo m026's damage to the m052/m053 batches. m026 disabled all 8
    # new bots because they weren't in SPEC_BOT_NAMES; m055 flips them back
    # on. Must run AFTER m026 (which is called from run_migrations line 140
    # above) so m055 sees the damage and undoes it. Not gated — m026 keeps
    # trying to re-disable so m055 keeps flipping back on. Idempotent no-op
    # once m026's spec list is updated (same commit).
    try:
        from app.db.migrations.m055_reenable_new_quant_bots import run as _run_m055
        with engine.begin() as _m055_conn:
            _m055_result = _run_m055(_m055_conn)
        logger.warning("[startup] m055 OK: %s", _m055_result)
    except Exception as _m055_exc:
        logger.error("[startup] m055_reenable_new_quant_bots FAILED: %s", _m055_exc, exc_info=True)

    # m056: seed 4 new quant stock bots (day_momentum, day_meanrev,
    # swing_growth, swing_value) + reallocate $60k from halted scalper +
    # trim dca_btc_eth. Same self-balancing pattern as m052/m053.
    try:
        from app.db.migrations.m056_seed_stock_quant_bots import run as _run_m056
        with engine.begin() as _m056_conn:
            _m056_result = _run_m056(_m056_conn)
        logger.warning("[startup] m056 OK: %s", _m056_result)
    except Exception as _m056_exc:
        logger.error("[startup] m056_seed_stock_quant_bots FAILED: %s", _m056_exc, exc_info=True)

    # m057: Brock's spec reallocation table ($1M + $10k real profits).
    # GATED behind env var BMG_APPROVE_M057=true per Brock's autonomy rule
    # about explicit approval for capital moves. If not set, this is a
    # no-op that returns awaiting_approval — safe to leave in main.py.
    try:
        from app.db.migrations.m057_brock_reallocation_table import run as _run_m057
        with engine.begin() as _m057_conn:
            _m057_result = _run_m057(_m057_conn)
        logger.warning("[startup] m057 status: %s", _m057_result)
    except Exception as _m057_exc:
        logger.error("[startup] m057_brock_reallocation_table FAILED: %s", _m057_exc, exc_info=True)

    # m058: Brock's 2026-07-02 green-light redistribution — halted $120k
    # spread across 4 new stock bots (doubled to $40k each) + 4 crypto quant
    # bots (+$10k each). Gated by BMG_APPROVE_M058=true.
    try:
        from app.db.migrations.m058_brock_greenlight_reallocation import run as _run_m058
        with engine.begin() as _m058_conn:
            _m058_result = _run_m058(_m058_conn)
        logger.warning("[startup] m058 status: %s", _m058_result)
    except Exception as _m058_exc:
        logger.error("[startup] m058_brock_greenlight_reallocation FAILED: %s", _m058_exc, exc_info=True)

    # m059: fix m058's phantom — halted bots had duplicate rows the .fetchone()
    # in m058 missed. Zeros ALL rows for crypto_quant_mean_reversion + scalper.
    # No env-var gate — this only zeros capital that Brock already zeroed via
    # m058 approval; it's a bug-fix on m058, not a new capital move.
    try:
        from app.db.migrations.m059_zero_all_halted_rows import run as _run_m059
        with engine.begin() as _m059_conn:
            _m059_result = _run_m059(_m059_conn)
        logger.warning("[startup] m059 status: %s", _m059_result)
    except Exception as _m059_exc:
        logger.error("[startup] m059_zero_all_halted_rows FAILED: %s", _m059_exc, exc_info=True)

    # m060: close phantom NULL-option_type positions on options bots that
    # were filling position_cap slots and blocking all new signals.
    # No env-var gate — pure phantom cleanup, no capital moved.
    try:
        from app.db.migrations.m060_close_options_phantoms import run as _run_m060
        with engine.begin() as _m060_conn:
            _m060_result = _run_m060(_m060_conn)
        logger.warning("[startup] m060 status: %s", _m060_result)
    except Exception as _m060_exc:
        logger.error("[startup] m060_close_options_phantoms FAILED: %s", _m060_exc, exc_info=True)

    # m061: kill crypto_onchain (dead capital — no on-chain API keys), redirect
    # $30k to crypto_quant_aggressive. Brock's paste-ready 2026-07-03.
    try:
        from app.db.migrations.m061_kill_onchain_reallocate import run as _run_m061
        with engine.begin() as _m061_conn:
            _m061_result = _run_m061(_m061_conn)
        logger.warning("[startup] m061 status: %s", _m061_result)
    except Exception as _m061_exc:
        logger.error("[startup] m061_kill_onchain_reallocate FAILED: %s", _m061_exc, exc_info=True)

    # m062: normalize Perk (user_id=7) to Brock's same $1M spec. Approved 2026-07-03.
    try:
        from app.db.migrations.m062_normalize_perk_to_spec import run as _run_m062
        with engine.begin() as _m062_conn:
            _m062_result = _run_m062(_m062_conn)
        logger.warning("[startup] m062 status: %s", _m062_result)
    except Exception as _m062_exc:
        logger.error("[startup] m062_normalize_perk_to_spec FAILED: %s", _m062_exc, exc_info=True)

    # m063: signal_conclave_verdicts table for the Agent Conclave feature.
    # Table is created empty; the feature itself is gated by CONCLAVE_ENABLED
    # env var (default false) so this ships as a no-op.
    try:
        from app.db.migrations.m063_signal_conclave_verdicts import run as _run_m063
        with engine.begin() as _m063_conn:
            _m063_result = _run_m063(_m063_conn)
        logger.warning("[startup] m063 status: %s", _m063_result)
    except Exception as _m063_exc:
        logger.error("[startup] m063_signal_conclave_verdicts FAILED: %s", _m063_exc, exc_info=True)

    # m064: Strategy Farm Phase 1 — strategy_templates + farm_candidates.
    # Seeds 10 templates. Generator endpoint is gated by
    # BMG_STRATEGY_FARM_ENABLED (default false).
    try:
        from app.db.migrations.m064_strategy_farm_phase1 import run as _run_m064
        with engine.begin() as _m064_conn:
            _m064_result = _run_m064(_m064_conn)
        logger.warning("[startup] m064 status: %s", _m064_result)
    except Exception as _m064_exc:
        logger.error("[startup] m064_strategy_farm_phase1 FAILED: %s", _m064_exc, exc_info=True)

    # m065: Portfolio-Rank Bot Framework Phase 1 — tables + dummy bot.
    # Feature flag BMG_PORTFOLIO_RANK_BOTS_ENABLED gates the rebalance
    # endpoint. Read endpoints work regardless so the leaderboard can
    # render state.
    try:
        from app.db.migrations.m065_portfolio_rank_framework import run as _run_m065
        with engine.begin() as _m065_conn:
            _m065_result = _run_m065(_m065_conn)
        logger.warning("[startup] m065 status: %s", _m065_result)
    except Exception as _m065_exc:
        logger.error("[startup] m065_portfolio_rank_framework FAILED: %s", _m065_exc, exc_info=True)

    # m066: Portfolio-Rank Phase 2 — momentum_umd + quality_gross_profitability
    # seeded with starting_capital=0 (funding source deferred to Brock).
    # Both bots ship enabled=false so nothing runs until the master flag flips.
    try:
        from app.db.migrations.m066_portfolio_rank_phase2 import run as _run_m066
        with engine.begin() as _m066_conn:
            _m066_result = _run_m066(_m066_conn)
        logger.warning("[startup] m066 status: %s", _m066_result)
    except Exception as _m066_exc:
        logger.error("[startup] m066_portfolio_rank_phase2 FAILED: %s", _m066_exc, exc_info=True)

    # m067: Portfolio-Rank Phase 2 funding (Brock's Option D — spread
    # $100K trim across 3 existing bots). Fund invariant asserted pre and
    # post; on invariant break, transaction rolls back and gate does NOT
    # record so a clean retry is possible.
    try:
        from app.db.migrations.m067_portfolio_rank_phase2_funding import run as _run_m067
        with engine.begin() as _m067_conn:
            _m067_result = _run_m067(_m067_conn)
        logger.warning("[startup] m067 status: %s", _m067_result)
    except Exception as _m067_exc:
        logger.error("[startup] m067_portfolio_rank_phase2_funding FAILED: %s",
                     _m067_exc, exc_info=True)

    # m068: disable the 4 orphan stock_quant bot allocations (Bug 3 Option B).
    # They sit at starting_capital=0 AND enabled=true — visible garbage in
    # Patrick's fleet audit. Migration sets enabled=false. Preserves history.
    # Fund invariant asserted post-mutation.
    try:
        from app.db.migrations.m068_disable_orphan_stock_quant import run as _run_m068
        with engine.begin() as _m068_conn:
            _m068_result = _run_m068(_m068_conn)
        logger.warning("[startup] m068 status: %s", _m068_result)
    except Exception as _m068_exc:
        logger.error("[startup] m068_disable_orphan_stock_quant FAILED: %s",
                     _m068_exc, exc_info=True)

    # m069: seed 3 SSRN-cited stock factor bots at $0 capital.
    # Vault Tier A/B additions: low_volatility, value_hml,
    # net_stock_issuance. All ship enabled=false and $0 capital so a
    # later migration can fund from a specific source.
    try:
        from app.db.migrations.m069_ssrn_stock_factors_batch import run as _run_m069
        with engine.begin() as _m069_conn:
            _m069_result = _run_m069(_m069_conn)
        logger.warning("[startup] m069 status: %s", _m069_result)
    except Exception as _m069_exc:
        logger.error("[startup] m069_ssrn_stock_factors_batch FAILED: %s",
                     _m069_exc, exc_info=True)

    # m070: enable the 3 SSRN factor bots so their crons will fire.
    # Capital stays at $0 (dry-run only); a follow-up migration allocates
    # real capital when Brock decides the source.
    try:
        from app.db.migrations.m070_enable_ssrn_bots import run as _run_m070
        with engine.begin() as _m070_conn:
            _m070_result = _run_m070(_m070_conn)
        logger.warning("[startup] m070 status: %s", _m070_result)
    except Exception as _m070_exc:
        logger.error("[startup] m070_enable_ssrn_bots FAILED: %s",
                     _m070_exc, exc_info=True)

    # m071: stock sleeve rebalance. Spreads the $400K stock sleeve across
    # 11 strategies (7 existing bots trimmed, 4 dormant stock_quant bots
    # funded + re-enabled). Fund invariant preserved. Guard-gated.
    try:
        from app.db.migrations.m071_stock_sleeve_rebalance import run as _run_m071
        with engine.begin() as _m071_conn:
            _m071_result = _run_m071(_m071_conn)
        logger.warning("[startup] m071 status: %s", _m071_result)
    except Exception as _m071_exc:
        logger.error("[startup] m071_stock_sleeve_rebalance FAILED: %s",
                     _m071_exc, exc_info=True)

    # m072: seed 2 fleet-gap-filler portfolio-rank bots at $0 capital.
    # Fills trend-following gap (tsm_12m over 30 liquid ETFs) and
    # idiosyncratic-vol gap (idio_volatility, market-residual std over
    # S&P 500). Both dormant until funded via follow-up migration.
    try:
        from app.db.migrations.m072_fleet_gap_fillers import run as _run_m072
        with engine.begin() as _m072_conn:
            _m072_result = _run_m072(_m072_conn)
        logger.warning("[startup] m072 status: %s", _m072_result)
    except Exception as _m072_exc:
        logger.error("[startup] m072_fleet_gap_fillers FAILED: %s",
                     _m072_exc, exc_info=True)

    # m073: activate 3 SSRN factor bots + clean 2 zombies.
    # Trims momentum_umd + quality by $15k each to fund low_volatility,
    # value_hml, net_stock_issuance at $10k each. Also disables
    # crypto_onchain (m061 zombie) and dummy_alpha_rank (Phase 1 dev bot).
    # Fund invariant $1M preserved. Guard-gated.
    try:
        from app.db.migrations.m073_activate_ssrn_and_zombie_cleanup import run as _run_m073
        with engine.begin() as _m073_conn:
            _m073_result = _run_m073(_m073_conn)
        logger.warning("[startup] m073 status: %s", _m073_result)
    except Exception as _m073_exc:
        logger.error("[startup] m073_activate_ssrn_and_zombie_cleanup FAILED: %s",
                     _m073_exc, exc_info=True)

    # m074: seed 2 more SSRN factor bots. Trims momentum_umd + quality
    # each 35k -> 25k to fund residual_momentum + bab at 10k each.
    # Enabled on insert; first rebalance next 03:00 CT cron.
    try:
        from app.db.migrations.m074_ssrn_batch_2 import run as _run_m074
        with engine.begin() as _m074_conn:
            _m074_result = _run_m074(_m074_conn)
        logger.warning("[startup] m074 status: %s", _m074_result)
    except Exception as _m074_exc:
        logger.error("[startup] m074_ssrn_batch_2 FAILED: %s",
                     _m074_exc, exc_info=True)

    # m075: SSRN batch 3. Seeds 3 new portfolio-rank factor bots
    # (pead, insider_cluster_buys, crypto_xs_momentum) at $10k each
    # AND creates 2 new signal-trigger bots (macro_faber_gtaa,
    # spy_iron_condor_weekly) at $15k each. Trims existing PR + ST
    # bots to preserve $1M fund invariant.
    try:
        from app.db.migrations.m075_ssrn_batch_3 import run as _run_m075
        with engine.begin() as _m075_conn:
            _m075_result = _run_m075(_m075_conn)
        logger.warning("[startup] m075 status: %s", _m075_result)
    except Exception as _m075_exc:
        logger.error("[startup] m075_ssrn_batch_3 FAILED: %s",
                     _m075_exc, exc_info=True)

    # m076: emergency halt of options bots after credit-side sign flip
    # exhausted Alpaca margin. Fix in same commit; halt is precautionary.
    try:
        from app.db.migrations.m076_halt_options_bots import run as _run_m076
        with engine.begin() as _m076_conn:
            _m076_result = _run_m076(_m076_conn)
        logger.warning("[startup] m076 status: %s", _m076_result)
    except Exception as _m076_exc:
        logger.error("[startup] m076_halt_options_bots FAILED: %s",
                     _m076_exc, exc_info=True)

    # m077: mirror BMG fund invariant to Alpaca equity ($97,340). Scales
    # every bot proportionally 1M -> 97,340 and re-enables the 2 options
    # bots that m076 halted (safe now that sell-side fix is deployed).
    try:
        from app.db.migrations.m077_mirror_alpaca_97k import run as _run_m077
        with engine.begin() as _m077_conn:
            _m077_result = _run_m077(_m077_conn)
        logger.warning("[startup] m077 status: %s", _m077_result)
    except Exception as _m077_exc:
        logger.error("[startup] m077_mirror_alpaca_97k FAILED: %s",
                     _m077_exc, exc_info=True)

    # m078: purge all sim-fallback trades + positions. App now contains
    # only Alpaca-verified data. Companion to the runner.py change that
    # removes the DB-write fallback on Alpaca rejection.
    try:
        from app.db.migrations.m078_purge_sim_data import run as _run_m078
        with engine.begin() as _m078_conn:
            _m078_result = _run_m078(_m078_conn)
        logger.warning("[startup] m078 status: %s", _m078_result)
    except Exception as _m078_exc:
        logger.error("[startup] m078_purge_sim_data FAILED: %s",
                     _m078_exc, exc_info=True)

    # m079: purge pre-m077 daily snapshots so all-time / MTD / WTD
    # anchor at the $97,340 rebase point instead of the phantom $1M
    # baseline. Kills the fake -$903K loss on /strategy header.
    try:
        from app.db.migrations.m079_rebase_pnl_snapshots import run as _run_m079
        with engine.begin() as _m079_conn:
            _m079_result = _run_m079(_m079_conn)
        logger.warning("[startup] m079 status: %s", _m079_result)
    except Exception as _m079_exc:
        logger.error("[startup] m079_rebase_pnl_snapshots FAILED: %s",
                     _m079_exc, exc_info=True)

    # m080: cap any bot_allocation over $15k, redistribute excess so
    # invariant holds. Kills the 1.42x leverage bug where one bot's
    # allocation slipped past m077's rescale and it was buying $23k
    # per-position baskets on a $97k fund (GOOGL alone at 24%
    # concentration). Runs BEFORE market open so today's scans see the
    # capped values, not the stale big-capital ones.
    try:
        from app.db.migrations.m080_cap_outlier_allocations import run as _run_m080
        with engine.begin() as _m080_conn:
            _m080_result = _run_m080(_m080_conn)
        logger.warning("[startup] m080 status: %s", _m080_result)
    except Exception as _m080_exc:
        logger.error("[startup] m080_cap_outlier_allocations FAILED: %s",
                     _m080_exc, exc_info=True)

    # m081: SSRN batch 4 — Sloan accruals PR bot + promote tsmom_multi_asset
    # to production + wire vrp_put_write into options_income (Israelov 2019).
    try:
        from app.db.migrations.m081_ssrn_batch_4 import run as _run_m081
        with engine.begin() as _m081_conn:
            _m081_result = _run_m081(_m081_conn)
        logger.warning("[startup] m081 status: %s", _m081_result)
    except Exception as _m081_exc:
        logger.error("[startup] m081_ssrn_batch_4 FAILED: %s",
                     _m081_exc, exc_info=True)

    # m082: restore crypto_onchain to $486.70 tier (was $0 after m080 skip)
    # so capital-invariant returns to ok status. Also rebases EXPECTED_SUM_CENTS
    # to $96,826.70 in capital_invariant.py constant.
    try:
        from app.db.migrations.m082_repair_crypto_onchain_capital import run as _run_m082
        with engine.begin() as _m082_conn:
            _m082_result = _run_m082(_m082_conn)
        logger.warning("[startup] m082 status: %s", _m082_result)
    except Exception as _m082_exc:
        logger.error("[startup] m082_repair_crypto_onchain_capital FAILED: %s",
                     _m082_exc, exc_info=True)

    # m084: close 10 phantom bot_positions surfaced by 2026-07-09 audit —
    # DB rows that Alpaca has no matching position for (~$4K in stocks +
    # 2 worthless options). Companion to per-leg mleg BotPosition write
    # and portfolio_rank_holdings reconciler inclusion.
    try:
        from app.db.migrations.m084_close_phantom_positions import run as _run_m084
        with engine.begin() as _m084_conn:
            _m084_result = _run_m084(_m084_conn)
        logger.warning("[startup] m084 status: %s", _m084_result)
    except Exception as _m084_exc:
        logger.error("[startup] m084_close_phantom_positions FAILED: %s",
                     _m084_exc, exc_info=True)

    # ── SSRN batch 5 (2026-07-09) ──────────────────────────────────────
    # m085: halt crypto_quant_scalp_1m + crypto_quant_meme_tier (bleeders,
    #       frees $2,920.20 pool)
    # m086: seed short_term_momentum PR bot ($1,000) — Medhat-Schmeling 2022
    # m087: seed cw_vol_spread PR bot ($1,000) — Cremers-Weinbaum 2010
    # m088: bump options_directional for earnings_straddle strategy ($920.20)
    #       — Gao-Xing-Zhang 2018 pre-earnings straddle
    # Net fund invariant delta = 0. All four MUST run in the same boot cycle.
    try:
        from app.db.migrations.m085_halt_scalp_meme_bleeders import run as _run_m085
        with engine.begin() as _m085_conn:
            _m085_result = _run_m085(_m085_conn)
        logger.warning("[startup] m085 status: %s", _m085_result)
    except Exception as _m085_exc:
        logger.error("[startup] m085_halt_scalp_meme_bleeders FAILED: %s",
                     _m085_exc, exc_info=True)

    try:
        from app.db.migrations.m086_short_term_momentum_bot import run as _run_m086
        with engine.begin() as _m086_conn:
            _m086_result = _run_m086(_m086_conn)
        logger.warning("[startup] m086 status: %s", _m086_result)
    except Exception as _m086_exc:
        logger.error("[startup] m086_short_term_momentum_bot FAILED: %s",
                     _m086_exc, exc_info=True)

    try:
        from app.db.migrations.m087_cw_vol_spread_bot import run as _run_m087
        with engine.begin() as _m087_conn:
            _m087_result = _run_m087(_m087_conn)
        logger.warning("[startup] m087 status: %s", _m087_result)
    except Exception as _m087_exc:
        logger.error("[startup] m087_cw_vol_spread_bot FAILED: %s",
                     _m087_exc, exc_info=True)

    try:
        from app.db.migrations.m088_earnings_straddle_funding import run as _run_m088
        with engine.begin() as _m088_conn:
            _m088_result = _run_m088(_m088_conn)
        logger.warning("[startup] m088 status: %s", _m088_result)
    except Exception as _m088_exc:
        logger.error("[startup] m088_earnings_straddle_funding FAILED: %s",
                     _m088_exc, exc_info=True)

    # m089: halt 4 sim-only crypto quant bleeders + redistribute the freed
    # $13,141 to the three broker-real-fill winners (options_directional,
    # options_income, stock_quant_day_momentum). Fund invariant preserved.
    try:
        from app.db.migrations.m089_halt_sim_crypto_quants import run as _run_m089
        with engine.begin() as _m089_conn:
            _m089_result = _run_m089(_m089_conn)
        logger.warning("[startup] m089 status: %s", _m089_result)
    except Exception as _m089_exc:
        logger.error("[startup] m089_halt_sim_crypto_quants FAILED: %s",
                     _m089_exc, exc_info=True)

    # m090: zero the m089 $0.20 rounding drift + backfill m084/m085 into
    # schema_migrations so they stop re-executing every boot.
    try:
        from app.db.migrations.m090_cleanup_2026_07_12 import run as _run_m090
        with engine.begin() as _m090_conn:
            _m090_result = _run_m090(_m090_conn)
        logger.warning("[startup] m090 status: %s", _m090_result)
    except Exception as _m090_exc:
        logger.error("[startup] m090_cleanup_2026_07_12 FAILED: %s",
                     _m090_exc, exc_info=True)

    # m091: reactivate the 3 bots m026 was stomping every boot.
    # Must run AFTER m026 so m026's stomp finishes first and this
    # migration has the last word.
    try:
        from app.db.migrations.m091_reactivate_stomped_bots import run as _run_m091
        with engine.begin() as _m091_conn:
            _m091_result = _run_m091(_m091_conn)
        logger.warning("[startup] m091 status: %s", _m091_result)
    except Exception as _m091_exc:
        logger.error("[startup] m091_reactivate_stomped_bots FAILED: %s",
                     _m091_exc, exc_info=True)

    # m092: SSRN batch 6 — halt crypto_quant_defi_l2 (last sim-only
    # crypto quant bleeder) and seed 3 new PR bots: os_ratio, overnight_
    # momentum, smart_money_13f. Freed $2,920.20 exactly balances new
    # allocations. Fund invariant preserved.
    try:
        from app.db.migrations.m092_ssrn_batch_6 import run as _run_m092
        with engine.begin() as _m092_conn:
            _m092_result = _run_m092(_m092_conn)
        logger.warning("[startup] m092 status: %s", _m092_result)
    except Exception as _m092_exc:
        logger.error("[startup] m092_ssrn_batch_6 FAILED: %s",
                     _m092_exc, exc_info=True)

    # m093: create smart_money_13f_holdings + cusip_symbol_cache tables so
    # the edgar_13f ingest job (registered below at scheduler setup time)
    # has somewhere to write. Companion to m092's smart_money_13f PR bot.
    try:
        from app.db.migrations.m093_smart_money_13f_tables import run as _run_m093
        with engine.begin() as _m093_conn:
            _m093_result = _run_m093(_m093_conn)
        logger.warning("[startup] m093 status: %s", _m093_result)
    except Exception as _m093_exc:
        logger.error("[startup] m093_smart_money_13f_tables FAILED: %s",
                     _m093_exc, exc_info=True)

    # m094: backfill exit_reason on historical closed bot_positions per the
    # RIA-stats spec (never null; must be canonical enum).
    try:
        from app.db.migrations.m094_backfill_exit_reasons import run as _run_m094
        with engine.begin() as _m094_conn:
            _m094_result = _run_m094(_m094_conn)
        logger.warning("[startup] m094 status: %s", _m094_result)
    except Exception as _m094_exc:
        logger.error("[startup] m094_backfill_exit_reasons FAILED: %s",
                     _m094_exc, exc_info=True)

    # m095: add composite_score_at_execution to bot_trades so the
    # time-boxed threshold experiment can tag every admitted trade.
    try:
        from app.db.migrations.m095_add_composite_score_at_execution import run as _run_m095
        with engine.begin() as _m095_conn:
            _m095_result = _run_m095(_m095_conn)
        logger.warning("[startup] m095 status: %s", _m095_result)
    except Exception as _m095_exc:
        logger.error("[startup] m095_add_composite_score_at_execution FAILED: %s",
                     _m095_exc, exc_info=True)

    # Phase 2: one-shot backfill of historical bot_trades regime tags.
    # Gated via _gate.already_ran so it runs ONCE per deploy lifetime.
    try:
        from app.db.migrations._gate import already_ran, record
        from app.jobs.backfill_regime_tags import run_backfill as _run_backfill
        from app.db.session import SessionLocal as _SessionLocal
        _BACKFILL_NAME = "backfill_regime_tags_2026_06"
        with engine.connect() as _gate_conn:
            _ran = already_ran(_gate_conn, _BACKFILL_NAME)
        if not _ran:
            _bf_db = _SessionLocal()
            try:
                _bf_result = _run_backfill(_bf_db, batch_size=500, dry_run=False)
                logger.warning("[startup] regime backfill OK: %s", _bf_result)
                if _bf_result.get("verify_null_after", 0) == 0:
                    with engine.begin() as _gate_conn2:
                        record(_gate_conn2, _BACKFILL_NAME)
                    logger.warning("[startup] regime backfill gate recorded")
                else:
                    logger.critical(
                        "[startup] regime backfill left %d NULL rows — NOT recording gate, will retry next boot",
                        _bf_result["verify_null_after"],
                    )
            finally:
                _bf_db.close()
        else:
            logger.info("[startup] regime backfill already applied, skipping")
    except Exception as _bf_exc:
        logger.error("[startup] regime backfill FAILED: %s", _bf_exc, exc_info=True)

    # SHIP 5: CIO Morning Meeting tables (m039-m043).
    try:
        from app.db.migrations.m039_fund_meetings import run as _run_m039
        with engine.connect() as _m039_conn:
            _m039_result = _run_m039(_m039_conn)
        logger.warning("[startup] m039 OK: %s", _m039_result)
    except Exception as _m039_exc:
        logger.error("[startup] m039_fund_meetings FAILED: %s", _m039_exc, exc_info=True)
    try:
        from app.db.migrations.m040_fund_briefings import run as _run_m040
        with engine.connect() as _m040_conn:
            _m040_result = _run_m040(_m040_conn)
        logger.warning("[startup] m040 OK: %s", _m040_result)
    except Exception as _m040_exc:
        logger.error("[startup] m040_fund_briefings FAILED: %s", _m040_exc, exc_info=True)
    try:
        from app.db.migrations.m041_agent_opening_reads import run as _run_m041
        with engine.connect() as _m041_conn:
            _m041_result = _run_m041(_m041_conn)
        logger.warning("[startup] m041 OK: %s", _m041_result)
    except Exception as _m041_exc:
        logger.error("[startup] m041_agent_opening_reads FAILED: %s", _m041_exc, exc_info=True)
    try:
        from app.db.migrations.m042_agent_commitments import run as _run_m042
        with engine.connect() as _m042_conn:
            _m042_result = _run_m042(_m042_conn)
        logger.warning("[startup] m042 OK: %s", _m042_result)
    except Exception as _m042_exc:
        logger.error("[startup] m042_agent_commitments FAILED: %s", _m042_exc, exc_info=True)
    try:
        from app.db.migrations.m043_veto_log import run as _run_m043
        with engine.connect() as _m043_conn:
            _m043_result = _run_m043(_m043_conn)
        logger.warning("[startup] m043 OK: %s", _m043_result)
    except Exception as _m043_exc:
        logger.error("[startup] m043_veto_log FAILED: %s", _m043_exc, exc_info=True)

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
    from app.jobs.aqa_loop import register_aqa_jobs
    register_aqa_jobs(scheduler)
    try:
        from strategy_lab.portfolio_rank_runner import setup_portfolio_rank_scheduler
        setup_portfolio_rank_scheduler(scheduler)
    except Exception as _pr_sched_exc:
        logger.error("[startup] portfolio_rank scheduler FAILED (non-fatal): %s",
                     _pr_sched_exc, exc_info=True)
    try:
        from app.services.edgar_13f import setup_edgar_13f_scheduler
        setup_edgar_13f_scheduler(scheduler)
    except Exception as _edgar_sched_exc:
        logger.error("[startup] edgar_13f scheduler FAILED (non-fatal): %s",
                     _edgar_sched_exc, exc_info=True)
    try:
        from app.services.option_close_sync import setup_option_close_sync_scheduler
        setup_option_close_sync_scheduler(scheduler)
    except Exception as _ocs_exc:
        logger.error("[startup] option_close_sync scheduler FAILED (non-fatal): %s",
                     _ocs_exc, exc_info=True)
    try:
        from app.jobs.pr_daily_mark import setup_pr_daily_mark_scheduler
        setup_pr_daily_mark_scheduler(scheduler)
    except Exception as _pr_mark_exc:
        logger.error("[startup] pr_daily_mark scheduler FAILED (non-fatal): %s",
                     _pr_mark_exc, exc_info=True)
    try:
        from app.services.threshold_experiment import setup_threshold_experiment_scheduler
        setup_threshold_experiment_scheduler(scheduler)
    except Exception as _te_exc:
        logger.error("[startup] threshold_experiment scheduler FAILED (non-fatal): %s",
                     _te_exc, exc_info=True)
    try:
        from app.services.sp500_refresh import setup_sp500_scheduler
        setup_sp500_scheduler(scheduler)
    except Exception as _sp_sched_exc:
        logger.error("[startup] sp500_refresh scheduler FAILED (non-fatal): %s",
                     _sp_sched_exc, exc_info=True)
    try:
        from app.services.buying_power_healer import setup_buying_power_healer
        setup_buying_power_healer(scheduler)
    except Exception as _bph_exc:
        logger.error("[startup] buying_power_healer scheduler FAILED (non-fatal): %s",
                     _bph_exc, exc_info=True)
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

    # One-shot pre-market book post — fires 90s after boot when
    # BMG_FIRE_PREMARKET_NOW=true. Used to verify the format overnight
    # without waiting for the 8:00 AM CT cron. Unset the env var after
    # to prevent double-posts on subsequent deploys.
    async def _maybe_fire_premarket_now():
        import asyncio as _aio
        import os as _os
        if _os.environ.get("BMG_FIRE_PREMARKET_NOW", "").strip().lower() not in ("true", "1", "yes"):
            return
        await _aio.sleep(90)
        try:
            from app.db.session import SessionLocal as _SL
            from app.jobs.pre_market_book import post_pre_market_book as _post
            _db = _SL()
            try:
                await _aio.to_thread(_post, _db)
                logger.warning("[startup] one-shot pre-market book fired")
            finally:
                _db.close()
        except Exception as _exc:
            logger.warning("[startup] one-shot pre-market book failed: %s", _exc)
    asyncio.create_task(_maybe_fire_premarket_now())

    # One-shot: or-fallback audit results post per Brock's ask.
    async def _maybe_post_or_audit():
        import asyncio as _aio
        import os as _os
        if _os.environ.get("BMG_POST_OR_AUDIT", "").strip().lower() not in ("true", "1", "yes"):
            return
        await _aio.sleep(30)
        try:
            from app.jobs.or_fallback_audit_post import post_audit
            await _aio.to_thread(post_audit)
            logger.warning("[startup] one-shot or-audit fired")
        except Exception as _exc:
            logger.warning("[startup] or-audit failed: %s", _exc)
    asyncio.create_task(_maybe_post_or_audit())

    # One-shot: pre-open readiness post (for the pre-market check tonight).
    async def _maybe_fire_readiness_now():
        import asyncio as _aio
        import os as _os
        if _os.environ.get("BMG_FIRE_READINESS_NOW", "").strip().lower() not in ("true", "1", "yes"):
            return
        await _aio.sleep(45)
        try:
            from app.db.session import SessionLocal as _SL
            from app.jobs.pre_open_readiness import post_readiness as _post
            _db = _SL()
            try:
                await _aio.to_thread(_post, _db)
                logger.warning("[startup] one-shot pre-open readiness fired")
            finally:
                _db.close()
        except Exception as _exc:
            logger.warning("[startup] one-shot readiness failed: %s", _exc)
    asyncio.create_task(_maybe_fire_readiness_now())

    async def _maybe_post_4q():
        import asyncio as _aio
        import os as _os
        if _os.environ.get("BMG_POST_4Q", "").strip().lower() not in ("true", "1", "yes"):
            return
        await _aio.sleep(20)
        try:
            from app.jobs.four_clarifications_post import post_4q
            await _aio.to_thread(post_4q)
            logger.warning("[startup] 4Q post fired")
        except Exception as _exc:
            logger.warning("[startup] 4Q post failed: %s", _exc)
    asyncio.create_task(_maybe_post_4q())

    async def _maybe_post_options_fix():
        import asyncio as _aio
        import os as _os
        if _os.environ.get("BMG_POST_OPTIONS_FIX", "").strip().lower() not in ("true", "1", "yes"):
            return
        await _aio.sleep(25)
        try:
            from app.jobs.options_fix_post import post_options_fix
            await _aio.to_thread(post_options_fix)
            logger.warning("[startup] options fix post fired")
        except Exception as _exc:
            logger.warning("[startup] options fix post failed: %s", _exc)
    asyncio.create_task(_maybe_post_options_fix())

    async def _maybe_post_audit_10block():
        import asyncio as _aio
        import os as _os
        if _os.environ.get("BMG_POST_10BLOCK", "").strip().lower() not in ("true", "1", "yes"):
            return
        await _aio.sleep(25)
        try:
            from app.jobs.audit_10block_post import post_audit
            await _aio.to_thread(post_audit)
            logger.warning("[startup] 10-block audit post fired")
        except Exception as _exc:
            logger.warning("[startup] 10-block audit post failed: %s", _exc)
    asyncio.create_task(_maybe_post_audit_10block())

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
        # Content-Security-Policy — allows same-origin JS/CSS, inline styles
        # (Tailwind + shadcn use them), data: URIs for images, and websocket
        # + https connections for the API. Blocks arbitrary third-party JS.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' wss: https:; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
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
from app.routers.options_diagnostic import router as options_diagnostic_router
app.include_router(options_diagnostic_router)
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
from app.routers.farm import router as farm_router
app.include_router(farm_router)
from app.routers.portfolio_rank import router as portfolio_rank_router
app.include_router(portfolio_rank_router)
from app.routers.clean_slate import router as clean_slate_router
app.include_router(clean_slate_router)
app.include_router(admin_bots_router)
from app.routers.admin_quarantine import router as admin_quarantine_router
app.include_router(admin_quarantine_router)
app.include_router(sentinel_router)
app.include_router(dashboard_router)
app.include_router(pnl_router)
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
from app.routers.agent_opening_reads import router as agent_opening_reads_router
app.include_router(agent_opening_reads_router)
from app.routers.cio_meeting import router as cio_meeting_router
app.include_router(cio_meeting_router)
from app.routers.fund_floor import router as fund_floor_router
app.include_router(fund_floor_router)
from app.routers.strategy_journal import router as strategy_journal_router
app.include_router(strategy_journal_router)
from app.routers import aqa_admin
app.include_router(aqa_admin.router)
from app.routers.live_activity import router as live_activity_router
app.include_router(live_activity_router)
from app.routers.risk_console import router as risk_console_router
app.include_router(risk_console_router)
from app.routers.trades_journal import router as trades_journal_router
app.include_router(trades_journal_router)


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health():
    """Liveness + LLM relay state snapshot.

    2026-07-06: extended with llm_relay derived from state in llm_client.py
    (updated on every call_llm invocation). Passive read — no active probe
    so /health stays fast for Railway ingress checks. If nothing has
    called the relay recently, status is "unknown" rather than false
    healthy.

    Never raises; always returns 200 so Railway keeps routing traffic.
    Monitoring tools should key off llm_relay.status.
    """
    import os as _os
    llm_relay: dict = {
        "status": "unknown",
        "relay_url_configured": False,
        "fallback_to_api_enabled": False,
    }
    try:
        llm_relay["relay_url_configured"] = bool(
            _os.getenv("RELAY_URL") and _os.getenv("RELAY_AUTH_TOKEN")
        )
        llm_relay["fallback_to_api_enabled"] = (
            _os.getenv("FALLBACK_TO_API", "false").strip().lower() == "true"
        )
        from app.services.llm_client import get_relay_state
        llm_relay.update(get_relay_state())
    except Exception as exc:
        llm_relay["check_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return {"status": "ok", "llm_relay": llm_relay}


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
