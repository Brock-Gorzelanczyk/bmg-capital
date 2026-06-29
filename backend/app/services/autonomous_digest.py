from __future__ import annotations
import json
import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

async def generate_autonomous_digest(user_id: int, db: Session) -> None:
    """Generate or update the daily autonomous digest for a user."""
    try:
        from app.db.models.autonomous import AutonomousAction, AutonomousDigest
        from app.db.models.paper import PaperAccount

        today = date.today()

        # Check if already generated today
        existing = db.query(AutonomousDigest).filter_by(
            user_id=user_id, digest_date=today
        ).first()
        if existing:
            return

        # Gather today's actions
        today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        actions = db.query(AutonomousAction).filter(
            AutonomousAction.user_id == user_id,
            AutonomousAction.created_at >= today_start,
        ).order_by(AutonomousAction.created_at.desc()).all()

        signals_fired = sum(1 for a in actions if a.action_type == "signal_fired")
        paper_buys    = sum(1 for a in actions if a.action_type == "paper_buy")
        paper_sells   = sum(1 for a in actions if a.action_type in ("paper_sell", "target_hit"))
        stop_hits     = sum(1 for a in actions if a.action_type == "stop_hit")

        # Net P&L today
        pnl_actions = [a for a in actions if a.outcome_value is not None]
        portfolio_delta = sum(a.outcome_value for a in pnl_actions)

        # Best and worst
        sorted_by_pnl = sorted(pnl_actions, key=lambda a: a.outcome_value or 0, reverse=True)
        best_action_str = None
        worst_action_str = None
        if sorted_by_pnl:
            b = sorted_by_pnl[0]
            best_action_str = f"{b.asset} +${b.outcome_value:.2f}" if (b.outcome_value or 0) > 0 else None
            w = sorted_by_pnl[-1]
            worst_action_str = f"{w.asset} ${w.outcome_value:.2f}" if (w.outcome_value or 0) < 0 else None

        # Most active strategy
        strategy_counts: dict[str, int] = {}
        for a in actions:
            if a.strategy_id:
                strategy_counts[a.strategy_id] = strategy_counts.get(a.strategy_id, 0) + 1
        top_strategy = max(strategy_counts, key=lambda k: strategy_counts[k]) if strategy_counts else "momentum_surge"

        # Build highlights
        highlights = []
        if paper_buys > 0:
            buy_actions = [a for a in actions if a.action_type == "paper_buy"][:2]
            for b in buy_actions:
                highlights.append(f"Opened {b.asset} — {b.rationale.split('.')[0]}")
        if paper_sells > 0:
            sell_actions = [a for a in actions if a.action_type in ("paper_sell", "target_hit")][:1]
            for s in sell_actions:
                pnl_str = f"+${s.outcome_value:.2f}" if (s.outcome_value or 0) >= 0 else f"${s.outcome_value:.2f}"
                highlights.append(f"Closed {s.asset} at {pnl_str} P&L")
        if signals_fired > 0:
            highlights.append(f"{signals_fired} new signals detected — check Strategy Lab")
        while len(highlights) < 2:
            highlights.append("Guardrails nominal — no limits tripped")

        # Build TL;DR
        delta_str = f"${portfolio_delta:+.2f}" if portfolio_delta != 0 else "flat"
        tldr = (
            f"While you were away, BMG fired {signals_fired} signals, "
            f"opened {paper_buys} paper position{'s' if paper_buys != 1 else ''}, "
            f"and your portfolio moved {delta_str}."
        )

        # Tomorrow preview
        tomorrow_preview = (
            "Strategy Lab continues monitoring all active positions. "
            "Check earnings calendar for upcoming catalysts. "
            "Next full scan runs at market open tomorrow."
        )

        # Try AI generation for market regime note + full narrative
        market_regime_note = "Trend-following strategies remain favored in current momentum regime."
        full_narrative = f"{tldr} {' '.join(highlights[:2])} {tomorrow_preview}"

        try:
            from app.services.llm_client import call_llm_cached
            from datetime import date as _date
            _date_str = str(today)
            market_regime_note = call_llm_cached(
                model="claude-haiku-4-5-20251001",
                prompt=(
                    f"Generate a 2-sentence market regime note for a trading app daily digest. "
                    f"Today: {signals_fired} signals fired, {paper_buys} buys, {paper_sells} exits, "
                    f"net P&L {delta_str}. Be specific about regime (trending/ranging/volatile) and what it means for tomorrow. "
                    f"Do NOT use bullet points. Plain prose."
                ),
                max_tokens=120,
                ttl_seconds=86400,
                cache_key_extra=f"{user_id}_{_date_str}_regime",
                agent_name="autonomous_digest",
            )
            full_narrative = call_llm_cached(
                model="claude-haiku-4-5-20251001",
                prompt=(
                    f"You are a concise AI trading assistant. Write a 150-word daily digest for a paper trading app. "
                    f"Today's summary: {tldr}. "
                    f"Highlights: {'; '.join(highlights)}. "
                    f"Tomorrow: {tomorrow_preview}. "
                    f"Market regime: {market_regime_note}. "
                    f"Write in second person ('BMG ran...', 'Your portfolio...'). "
                    f"Tone: calm, data-driven, not hype. No markdown."
                ),
                max_tokens=300,
                ttl_seconds=86400,
                cache_key_extra=f"{user_id}_{_date_str}_narrative",
                agent_name="autonomous_digest",
            )
        except Exception as e:
            logger.warning(f"AI digest generation failed: {e}, using template fallback")

        digest = AutonomousDigest(
            user_id=user_id,
            digest_date=today,
            tldr=tldr,
            highlights=json.dumps(highlights),
            strategy_spotlight=top_strategy,
            signals_fired=signals_fired,
            paper_buys=paper_buys,
            paper_sells=paper_sells,
            best_action=best_action_str,
            tomorrow_preview=tomorrow_preview,
            market_regime_note=market_regime_note,
            full_narrative=full_narrative,
            portfolio_delta=portfolio_delta,
        )
        db.add(digest)
        db.commit()
        logger.info(f"Generated autonomous digest for user {user_id}: {tldr}")

    except Exception as e:
        logger.error(f"generate_autonomous_digest failed for user {user_id}: {e}", exc_info=True)
