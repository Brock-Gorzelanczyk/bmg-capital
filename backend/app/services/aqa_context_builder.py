"""AQA context builder: assembles the full context payload for each AQA cycle.

build_context(db) -> dict with 8 keys:
  bot_diagnostic, bot_journals, sentry_issues_24h, recent_aqa_actions,
  regime_matrix, cio_weekly_reviews, data_gaps, built_at

Never raises. All per-source failures go into data_gaps.

Phase A stubs:
  - sentry_issues_24h: always [] (Sentry API not wired)
  - regime_matrix: always None (Phase 2 not shipped)
  - cio_weekly_reviews: always [] (Phase 3 not shipped)

DO NOT make HTTP calls to localhost -- all handlers called in-process.
DO NOT call call_llm() from here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# TODO PHASE B: wire Sentry query API for sentry_issues_24h
# TODO PHASE 2: wire regime_matrix from Phase 2 tagging system
# TODO PHASE 3: wire cio_weekly_reviews from Phase 3 CIO review system


def build_context(db: Session) -> dict:
    """Builds AQA context payload. Returns dict with 8 keys.

    Never raises. On per-source failure, logs warning and sets that field to
    None/[] plus appends to data_gaps.
    """
    data_gaps: list[str] = []
    built_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # -----------------------------------------------------------------------
    # 1. bot_diagnostic -- call handler directly (in-process, no HTTP)
    # -----------------------------------------------------------------------
    bot_diagnostic: Any = None
    try:
        from app.routers.admin import get_bot_diagnostic_singular

        fake_user = SimpleNamespace(id=1)
        bot_diagnostic = get_bot_diagnostic_singular(db=db, current_user=fake_user)
    except Exception as exc:
        logger.warning("[aqa-context] bot_diagnostic failed: %s", exc)
        data_gaps.append("bot_diagnostic_failed")

    # -----------------------------------------------------------------------
    # 2. bot_journals -- last 7 days from bot_daily_journals
    # -----------------------------------------------------------------------
    bot_journals: list[dict] = []
    try:
        rows = db.execute(
            text(
                "SELECT * FROM bot_daily_journals "
                "WHERE journal_date >= date('now', '-7 days') "
                "ORDER BY bot_id, journal_date DESC"
            )
        ).fetchall()
        bot_journals = [dict(row._mapping) for row in rows]
    except Exception as exc:
        logger.warning("[aqa-context] bot_journals failed: %s", exc)
        data_gaps.append("bot_journals_missing")

    # -----------------------------------------------------------------------
    # 3. sentry_issues_24h -- Phase A stub, always []
    # -----------------------------------------------------------------------
    # TODO Phase A.5: wire Sentry query API for test_failure_rising heuristic
    sentry_issues_24h: list = []
    data_gaps.append("sentry_issues_query")

    # -----------------------------------------------------------------------
    # 4. recent_aqa_actions -- last 7 days from aqa_proposals
    # -----------------------------------------------------------------------
    recent_aqa_actions: list[dict] = []
    try:
        rows = db.execute(
            text(
                "SELECT id, cycle_id, created_at, issue_tags, outcome "
                "FROM aqa_proposals "
                "WHERE created_at >= datetime('now', '-7 days') "
                "ORDER BY created_at DESC "
                "LIMIT 50"
            )
        ).fetchall()
        for row in rows:
            d = dict(row._mapping)
            try:
                d["issue_tags"] = json.loads(d["issue_tags"]) if d.get("issue_tags") else []
            except (json.JSONDecodeError, TypeError):
                d["issue_tags"] = []
            recent_aqa_actions.append(d)
    except Exception as exc:
        logger.warning("[aqa-context] recent_aqa_actions failed: %s", exc)
        # Not a data gap if aqa_proposals is just empty on first cycle

    # -----------------------------------------------------------------------
    # 5. regime_matrix -- Phase 2 stub, always None
    # -----------------------------------------------------------------------
    # TODO Phase 2: wire regime tagging system
    regime_matrix = None
    data_gaps.append("regime_matrix_phase2")

    # -----------------------------------------------------------------------
    # 6. cio_weekly_reviews -- Phase 3 stub, always []
    # -----------------------------------------------------------------------
    # TODO Phase 3: wire CIO weekly review consumption
    cio_weekly_reviews: list = []
    data_gaps.append("cio_weekly_reviews_phase3")

    return {
        "bot_diagnostic": bot_diagnostic,
        "bot_journals": bot_journals,
        "sentry_issues_24h": sentry_issues_24h,
        "recent_aqa_actions": recent_aqa_actions,
        "regime_matrix": regime_matrix,
        "cio_weekly_reviews": cio_weekly_reviews,
        "data_gaps": data_gaps,
        "built_at": built_at,
    }
