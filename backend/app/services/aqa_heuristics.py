"""AQA heuristics: pure function on context dict. NO DB calls. NO LLM calls.

find_actionable_issues(context) -> list[str]

Returns a deduplicated list of issue tags indicating something worth LLM review.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def find_actionable_issues(context: dict) -> list[str]:
    """Inspect context payload from build_context(). Return list of issue tags.

    Empty list = no LLM call needed.
    Tags are deduplicated -- no duplicate strings in returned list.
    Never raises on malformed context -- returns [] and logs warning.
    """
    try:
        return _find_issues_inner(context)
    except Exception as exc:
        logger.warning("[aqa-heuristics] unexpected error: %s", exc)
        return []


def _find_issues_inner(context: dict) -> list[str]:
    bot_diagnostic = context.get("bot_diagnostic")
    if bot_diagnostic is None:
        # Cannot evaluate without bot diagnostic data
        return []

    bots: list[dict] = bot_diagnostic.get("bots") or []
    if not bots:
        return []

    # Parse built_at for time comparisons
    built_at_str = context.get("built_at", "")
    try:
        built_at = datetime.fromisoformat(built_at_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.warning("[aqa-heuristics] malformed built_at=%r, using now()", built_at_str)
        built_at = datetime.now(timezone.utc)

    tags: set[str] = set()

    for bot in bots:
        # Only evaluate enabled bots (silence is expected for disabled/paused)
        if not bot.get("enabled", False):
            continue
        if bot.get("paused_reason"):
            continue

        # -------------------------------------------------------------------
        # Tag: bot_silent_48h
        # Fires if trades_24h == 0 AND (last_trade_at is None OR > 48h ago).
        #
        # 2026-06-30 fix: previously skipped bots with last_trade_at=None
        # as "never traded" / conservative. But options_directional,
        # options_income, stock_lt, crypto_onchain, cash_floor all have
        # NULL last_trade_at AND are real broken-silent bots. The
        # never-traded case IS the worst case to flag for AQA review.
        # Skip only if the bot has no real allocation (starting_capital==0)
        # which means it's not actually in the fund.
        # -------------------------------------------------------------------
        trades_24h = bot.get("trades_24h", 0)
        last_trade_at_str = bot.get("last_trade_at")
        starting_capital = bot.get("starting_capital_cents", 0)

        if trades_24h == 0 and starting_capital > 0:
            if last_trade_at_str is None:
                # Never traded with real allocation — flag for AQA review.
                tags.add("bot_silent_48h")
            else:
                try:
                    last_trade_at = datetime.fromisoformat(
                        last_trade_at_str.replace("Z", "+00:00")
                    )
                    silence_duration = built_at - last_trade_at
                    if silence_duration > timedelta(hours=48):
                        tags.add("bot_silent_48h")
                except (ValueError, AttributeError):
                    logger.warning(
                        "[aqa-heuristics] cannot parse last_trade_at=%r for bot=%r",
                        last_trade_at_str,
                        bot.get("bot_id"),
                    )

        # -------------------------------------------------------------------
        # Tag: deployment_low
        # Fires if open_positions_notional_cents / starting_capital_cents < 30%.
        # Fields may not be present in current bot_diagnostic shape -- skip conservatively.
        # TODO Phase A.5: add open_positions_notional_cents to bot_diagnostic handler.
        # -------------------------------------------------------------------
        notional = bot.get("open_positions_notional_cents")
        starting = bot.get("starting_capital_cents")

        if notional is None or starting is None:
            # Fields not exposed in current bot_diagnostic -- skip, log once at debug level
            logger.debug(
                "[aqa-heuristics] deployment_pct unavailable for bot=%r "
                "(open_positions_notional_cents or starting_capital_cents missing)",
                bot.get("bot_id"),
            )
        elif starting > 0:
            deployment_pct = notional / starting
            if deployment_pct < 0.30:
                tags.add("deployment_low")

    # TODO Phase A.5: "test_failure_rising" -- needs Sentry query API
    # TODO Phase 5: "promotion_candidate_ready" -- needs Phase 5 promotion engine

    return list(tags)
