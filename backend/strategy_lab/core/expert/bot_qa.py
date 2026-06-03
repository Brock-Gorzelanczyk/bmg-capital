"""
Co-Pilot Q&A grounded strictly in audit log + positions + journal.

Takes natural language question about a bot's behavior.
Fetches relevant audit records, signals, positions, journal entries.
Sends to Claude API with strict grounding prompt: "Answer ONLY from
the provided data. Do not speculate. If the data doesn't show it,
say 'I don't have that information in the audit log.'"

Returns structured answer with citations (audit record IDs).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024
_CONTEXT_WINDOW_DAYS = 30


def _gather_context(bot_name: str, user_id: int, db) -> dict:
    """Fetch audit records, signals, positions, journal for context."""
    context: dict = {
        "signals": [],
        "positions": [],
        "trades": [],
        "audit_records": [],
        "signal_ids": [],
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=_CONTEXT_WINDOW_DAYS)

    try:
        from app.db.models.bots import (
            BotSignal, BotPosition, BotTrade, BotAllocation, BotProfile
        )

        # Find allocations for this user + bot_name
        allocs = (
            db.query(BotAllocation)
            .join(BotProfile, BotAllocation.profile_id == BotProfile.id)
            .filter(
                BotAllocation.user_id == user_id,
                BotProfile.name == bot_name,
            )
            .all()
        )
        alloc_ids = [a.id for a in allocs]

        if not alloc_ids:
            return context

        # Signals
        signals = (
            db.query(BotSignal)
            .filter(
                BotSignal.allocation_id.in_(alloc_ids),
                BotSignal.ts >= cutoff,
            )
            .order_by(BotSignal.ts.desc())
            .limit(50)
            .all()
        )
        context["signals"] = [
            {
                "id": s.id,
                "ts": s.ts.isoformat() if s.ts else None,
                "symbol": s.symbol,
                "side": s.side,
                "confidence": s.confidence,
                "reason": s.reason,
                "strategy": s.strategy,
            }
            for s in signals
        ]
        context["signal_ids"] = [s.id for s in signals]

        # Positions (open + recently closed)
        positions = (
            db.query(BotPosition)
            .filter(
                BotPosition.allocation_id.in_(alloc_ids),
                BotPosition.opened_at >= cutoff,
            )
            .order_by(BotPosition.opened_at.desc())
            .limit(20)
            .all()
        )
        context["positions"] = [
            {
                "id": p.id,
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_cost_cents": p.avg_cost_cents,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                "exit_reason": p.exit_reason,
                "why_opened_json": getattr(p, "why_opened_json", None),
                "post_mortem_json": getattr(p, "post_mortem_json", None),
            }
            for p in positions
        ]

        # Trades
        trades = (
            db.query(BotTrade)
            .filter(
                BotTrade.allocation_id.in_(alloc_ids),
                BotTrade.ts >= cutoff,
            )
            .order_by(BotTrade.ts.desc())
            .limit(50)
            .all()
        )
        context["trades"] = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "fill_price_cents": t.fill_price_cents,
                "ts": t.ts.isoformat() if t.ts else None,
                "slippage_bps": t.slippage_bps,
            }
            for t in trades
        ]

    except Exception as exc:
        logger.warning("[bot_qa] Error gathering context: %s", exc)

    return context


def _call_claude_qa(question: str, context: dict, bot_name: str) -> dict:
    """Call Claude API with strict grounding prompt."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        context_json = json.dumps(context, default=str, indent=2)
        system_prompt = (
            "You are a trading bot audit assistant. "
            "Answer ONLY from the provided data. "
            "Do not speculate or use prior knowledge. "
            "If the data doesn't show it, say exactly: "
            "'I don't have that information in the audit log.' "
            "When citing evidence, reference the record ID."
        )
        user_prompt = f"""Bot name: {bot_name}

Audit data (last 30 days):
{context_json}

Question: {question}

Respond with JSON: {{"answer": "...", "citations": [list of signal/trade/position IDs referenced], "confidence": 0.0-1.0}}
Return ONLY valid JSON."""

        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text if message.content else ""

        try:
            parsed = json.loads(raw)
            return {
                "answer": parsed.get("answer", raw),
                "citations": parsed.get("citations", []),
                "confidence": float(parsed.get("confidence", 0.7)),
            }
        except (json.JSONDecodeError, ValueError):
            # Try to extract JSON
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    return {
                        "answer": parsed.get("answer", raw),
                        "citations": parsed.get("citations", []),
                        "confidence": float(parsed.get("confidence", 0.7)),
                    }
                except (json.JSONDecodeError, ValueError):
                    pass
            return {"answer": raw, "citations": [], "confidence": 0.5}

    except Exception as exc:
        logger.warning("[bot_qa] Claude API call failed: %s", exc)
        return None


def answer_question(
    question: str,
    bot_name: str,
    user_id: int,
    db,
) -> dict:
    """Returns {answer: str, citations: list[int], confidence: float}."""
    context = _gather_context(bot_name, user_id, db)

    # Check if we have any data
    has_data = any(bool(v) for v in context.values())
    if not has_data:
        return {
            "answer": "I don't have that information in the audit log.",
            "citations": [],
            "confidence": 0.0,
        }

    # Try Claude API
    if os.environ.get("ANTHROPIC_API_KEY"):
        result = _call_claude_qa(question, context, bot_name)
        if result:
            return result

    # Fallback: rule-based Q&A
    question_lower = question.lower()
    answer = "I don't have that information in the audit log."
    citations = []
    confidence = 0.3

    signals = context.get("signals", [])
    trades = context.get("trades", [])
    positions = context.get("positions", [])

    if any(kw in question_lower for kw in ("last signal", "recent signal", "last trade")):
        if signals:
            s = signals[0]
            answer = (
                f"The most recent signal was {s['side'].upper()} {s['symbol']} "
                f"at {s['ts']} with confidence {s['confidence']:.2f}. "
                f"Strategy: {s['strategy']}. Reason: {s['reason']}."
            )
            citations = [s["id"]]
            confidence = 0.9

    elif any(kw in question_lower for kw in ("open position", "current position", "holding")):
        open_pos = [p for p in positions if not p.get("closed_at")]
        if open_pos:
            lines = [f"{p['symbol']} qty={p['qty']} opened={p['opened_at']}" for p in open_pos[:5]]
            answer = f"Open positions: {'; '.join(lines)}"
            citations = [p["id"] for p in open_pos[:5]]
            confidence = 0.85
        else:
            answer = "No open positions found in the audit log."
            confidence = 0.8

    elif any(kw in question_lower for kw in ("how many trade", "trade count", "number of trade")):
        answer = f"Found {len(trades)} trades in the last 30 days."
        citations = [t["id"] for t in trades[:10]]
        confidence = 0.9

    return {"answer": answer, "citations": citations, "confidence": confidence}
