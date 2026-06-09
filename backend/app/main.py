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
from app.routers.chart_layouts import ChartLayout  # noqa: F401
from app.db.migration import run_migrations
from app.alpaca.stream import stream_manager
from app.screener.scheduler import scheduler, setup_scheduler
from app.ws.manager import connection_manager
from app.ws.router import router as ws_router
from app.routers import bars, screener, watchlist, portfolio, alerts, market, news, earnings, strategy, auth, backtest, research, paper, screens, learn, explain, options, notifications, discovery, onboarding, journal, journal_analytics, social, tiers, chart_drawings, support, recap, crypto, db_restore, crypto_strategy, defi, security, governance, bridge, copilot, workspace, workshop, monitoring, gdpr, net_worth, tax, estate, pods, rules, tlh, engagement, robo, autonomous, autopilot, playbook, founder, linked_accounts, voice_ai, daily_brief, deposit_match, referral, learn_earn, ipo, cfp, staking, dca_baskets, bots, strategy_lab, strategy_library, custom_bot, analyst, v2_shadow, smart_money, exams, admin
from app.routers import symbols as symbols_router
from app.routers import chart_layouts as chart_layouts_router
from app.routers.learning import router as learning_router
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

    # Ensure bot_paper_accounts table + crypto_quant_aggressive $100k sub-account row
    # (non-fatal — same idempotent pattern as learning_seed)
    try:
        from app.db.migrations.m001_bot_paper_accounts import run as _run_m001
        with engine.connect() as _m001_conn:
            _run_m001(_m001_conn)
    except Exception as _m001_exc:
        logger.warning("[startup] m001_bot_paper_accounts failed (non-fatal): %s", _m001_exc)

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
                    result = await fetch_and_upsert_congress(_seed_smc_db, days_back=365)
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

    yield

    # Graceful shutdown
    await stream_manager.stop()
    scheduler.shutdown()


app = FastAPI(
    title="BMG Capital API",
    version="1.0.0",
    lifespan=lifespan,
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SecurityHeadersMiddleware)
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
app.include_router(bots.router)
app.include_router(strategy_lab.router)
app.include_router(notification_channels_router.router)
app.include_router(strategy_library.router)
app.include_router(custom_bot.router)
app.include_router(analyst.router)
app.include_router(v2_shadow.router)
app.include_router(smart_money.router)
app.include_router(exams.router)
app.include_router(exams.verify_router)
app.include_router(admin.router)
app.include_router(symbols_router.router)
app.include_router(chart_layouts_router.router)


@app.get("/health", tags=["health"])
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
        # Everything else → SPA index
        return FileResponse(str(_STATIC_DIR / "index.html"))
