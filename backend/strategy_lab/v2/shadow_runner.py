"""Entry point for running v2 bots in shadow mode alongside the v1 runner.

Called by APScheduler on the same schedule as the v1 crypto_lt job.
Writes results to v2_shadow_runs — does NOT execute any trades.

Usage (from bot_scheduler.py):
    from strategy_lab.v2.shadow_runner import run_v2_shadow
    scheduler.add_job(lambda: run_v2_shadow("crypto_lt"), ...)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Any] = {}


def _load_registry() -> None:
    """Lazy-load bot definitions so import order doesn't matter."""
    global _REGISTRY
    if _REGISTRY:
        return
    try:
        from strategy_lab.v2.profiles.crypto_lt import crypto_lt_definition
        _REGISTRY["crypto_lt"] = crypto_lt_definition
    except Exception as exc:
        logger.warning("v2: failed to load crypto_lt definition: %s", exc)


def _to_json(objs: list) -> str:
    """Serialize dataclass list to JSON string for storage."""
    try:
        out = []
        for o in objs:
            try:
                d = asdict(o)
                # datetime → isoformat for JSON
                for k, v in d.items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                out.append(d)
            except Exception:
                out.append(str(o))
        return json.dumps(out)
    except Exception:
        return "[]"


def run_v2_shadow(bot_id: str) -> dict:
    """Synchronous wrapper: run one v2 iteration and persist results.

    Returns a summary dict.  Designed to be called by APScheduler.
    """
    import os
    if not os.getenv("ENABLE_V2_SHADOW"):
        logger.debug("v2: ENABLE_V2_SHADOW not set — skipping shadow run for %s", bot_id)
        return {"skipped": True, "reason": "ENABLE_V2_SHADOW not set"}
    _load_registry()
    definition = _REGISTRY.get(bot_id)
    if definition is None:
        logger.warning("v2: no definition registered for '%s'", bot_id)
        return {"error": f"no definition for {bot_id}"}

    try:
        return asyncio.run(_run_async(bot_id, definition))
    except Exception as exc:
        logger.error("v2: shadow run failed for %s: %s", bot_id, exc, exc_info=True)
        return {"error": str(exc)}


async def _run_async(bot_id: str, definition) -> dict:
    """Async implementation — builds context, runs the pipeline, persists."""
    from app.db.session import SessionLocal
    from app.db.models.bots import BotAllocation, BotProfile
    from app.db.models.v2_shadow import V2ShadowRun
    from strategy_lab.v2.context import AlgorithmContext, BarCache, PaperBrokerAdapter
    from strategy_lab.v2.runner import AlgorithmRunner

    db = SessionLocal()
    result = None
    try:
        # Find any enabled allocation for this bot profile to get user_id
        bp = db.query(BotProfile).filter_by(name=bot_id).first()
        if not bp:
            logger.warning("v2: BotProfile '%s' not in DB", bot_id)
            return {"skipped": True, "reason": "profile not found"}

        alloc = (
            db.query(BotAllocation)
            .filter_by(profile_id=bp.id, enabled=True, paper_mode=True)
            .first()
        )
        if not alloc:
            logger.info("v2: no enabled allocation for '%s' — skip", bot_id)
            return {"skipped": True, "reason": "no enabled allocation"}

        # Build context
        regime: dict = {}
        try:
            from strategy_lab.core.regime_detector import detect_regime
            regime = detect_regime(bot_id, {}) or {}
        except Exception:
            pass

        broker = PaperBrokerAdapter(
            user_id=alloc.user_id, db=db, shadow_mode=True
        )
        ctx = AlgorithmContext(
            bot_id=bot_id,
            portfolio_id=str(alloc.portfolio_id) if alloc.portfolio_id else None,
            asset_class="crypto",
            regime=regime,
            catalysts=[],
            broker=broker,
            cache=BarCache(),
        )

        runner = AlgorithmRunner(definition)
        result = await runner.run_iteration(ctx)

        # Persist shadow run record
        row = V2ShadowRun(
            bot_id=bot_id,
            run_ts=result.ts,
            universe_size=result.universe_size,
            insights_count=len(result.insights),
            targets_count=len(result.targets),
            orders_count=len(result.orders),
            shadow_mode=result.shadow_mode,
            duration_ms=result.duration_ms,
            insights_json=_to_json(result.insights),
            targets_json=_to_json(result.targets),
            orders_json=_to_json(result.orders),
            events_json=json.dumps(ctx.events),
            error=result.error,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        logger.info(
            "v2[%s] shadow run complete: universe=%d insights=%d targets=%d orders=%d (%dms)",
            bot_id, result.universe_size, len(result.insights),
            len(result.targets), len(result.orders), result.duration_ms,
        )
        return {
            "ok": result.ok,
            "shadow_run_id": row.id,
            "bot_id": bot_id,
            "universe_size": result.universe_size,
            "insights": len(result.insights),
            "targets": len(result.targets),
            "orders": len(result.orders),
            "duration_ms": result.duration_ms,
            "error": result.error,
        }

    except Exception as exc:
        logger.error("v2: _run_async failed for %s: %s", bot_id, exc, exc_info=True)
        if result is None:
            # Persist error record
            try:
                row = V2ShadowRun(bot_id=bot_id, error=str(exc))
                db.add(row)
                db.commit()
            except Exception:
                pass
        return {"error": str(exc)}
    finally:
        db.close()
