"""
Claude API writes structured rationale for every entry and exit.

Entry rationale:
  - strategy that fired + confidence
  - regime at entry
  - confluence score + timeframe votes
  - stop placement + why
  - expected hold period

Exit post-mortem:
  - exit reason (target/stop/time/manual)
  - actual vs expected return
  - what worked / what didn't
  - strategy weight adjustment recommendation

Uses ANTHROPIC_API_KEY. Falls back to structured template if no API key.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 512


def _has_anthropic_client() -> bool:
    # SHIP 3 R8: always return False — LLM replaced by template
    return False


def write_entry_journal(
    symbol: str,
    signal: "Signal",
    regime: dict,
    confluence_score: float,
    stop_info: dict,
    profile_config: dict,
) -> str:
    """Returns JSON string stored in BotPosition.why_opened_json."""
    execution_cfg = profile_config.get("execution", {}) if profile_config else {}
    hold_period = execution_cfg.get("hold_max_days", "N/A")

    if _has_anthropic_client():
        prompt = f"""You are a trading analyst. Write a concise JSON rationale for this trade entry.
Return ONLY valid JSON with these exact keys: strategy, confidence, regime_summary, confluence_note, stop_rationale, expected_hold.

Trade details:
- Symbol: {symbol}
- Side: {signal.side}
- Strategy: {signal.strategy}
- Confidence: {signal.confidence:.2f}
- Signal reason: {signal.reason}
- Regime: {json.dumps(regime)}
- Confluence score: {confluence_score:.2f} (threshold 0.66)
- Stop info: {json.dumps(stop_info)}
- Expected hold: {hold_period} days

Write a tight 1-sentence value per key. Return only JSON."""

        result = _call_claude(prompt)
        if result:
            try:
                # Validate it's parseable JSON
                parsed = json.loads(result)
                return json.dumps(parsed)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                import re
                match = re.search(r'\{.*\}', result, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                        return json.dumps(parsed)
                    except json.JSONDecodeError:
                        pass

    # Fallback: structured template
    rationale = {
        "strategy": signal.strategy,
        "confidence": round(signal.confidence, 4),
        "regime_summary": f"vix={regime.get('vix_regime','?')} trend={regime.get('trend_regime','?')}",
        "confluence_note": f"score={confluence_score:.2f} ({'pass' if confluence_score >= 0.66 else 'fail'})",
        "stop_rationale": f"method={stop_info.get('method','?')} stop={stop_info.get('stop_price','?')} ({stop_info.get('stop_pct','?'):.2f}%)" if stop_info else "n/a",
        "expected_hold": str(hold_period),
        "signal_reason": signal.reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(rationale)


def write_exit_journal(
    symbol: str,
    position: dict,
    exit_reason: str,
    pnl_pct: float,
    regime: dict,
) -> str:
    """Returns JSON string stored in BotPosition.post_mortem_json."""
    avg_cost_cents = position.get("avg_cost_cents", 0)
    avg_cost = avg_cost_cents / 100.0 if avg_cost_cents else 0
    opened_at = position.get("opened_at", "unknown")

    if _has_anthropic_client():
        prompt = f"""You are a trading analyst. Write a concise JSON post-mortem for this trade exit.
Return ONLY valid JSON with these exact keys: exit_reason, actual_return, what_worked, what_didnt, weight_recommendation.

Trade details:
- Symbol: {symbol}
- Exit reason: {exit_reason}
- P&L: {pnl_pct:.2f}%
- Avg cost: ${avg_cost:.2f}
- Opened at: {opened_at}
- Exit regime: {json.dumps(regime)}

Write a tight 1-sentence value per key. weight_recommendation must be one of: increase, decrease, hold.
Return only JSON."""

        result = _call_claude(prompt)
        if result:
            try:
                parsed = json.loads(result)
                return json.dumps(parsed)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{.*\}', result, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                        return json.dumps(parsed)
                    except json.JSONDecodeError:
                        pass

    # Fallback: structured template
    won = pnl_pct > 0
    post_mortem = {
        "exit_reason": exit_reason,
        "actual_return_pct": round(pnl_pct, 4),
        "what_worked": "Signal and regime aligned" if won else "Risk management limited loss",
        "what_didnt": "n/a" if won else "Signal did not play out as expected",
        "weight_recommendation": "increase" if pnl_pct >= 2.0 else ("decrease" if pnl_pct < -1.0 else "hold"),
        "exit_regime": f"vix={regime.get('vix_regime','?')} trend={regime.get('trend_regime','?')}",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(post_mortem)
