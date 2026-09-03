"""Multi-agent debate wrapper for Confluence picks.

Pattern (from research/43-vibe-trading-agent.md):
  analyst (call_llm_for_picks — already exists in confluence_hunter.py)
    → bull_agent (steelmans the trade)
    → bear_agent (steelmans the SKIP)
    → risk_officer (adjudicates, may downgrade or veto)

The debate runs ONCE per pick, in serial (bull → bear → risk_officer sees both).
Rejected picks are logged with reason so the vault trail explains WHY it was killed.

Cost: ~3× a single scoring pass (each agent gets the same context + prior turns).
Kept small by capping context per turn and using haiku for bull/bear + sonnet only for risk officer.

Kill switch:
  CONFLUENCE_DEBATE_ENABLED=false        # falls back to hunter's raw picks
  CONFLUENCE_DEBATE_STRICT=true          # risk_officer VETO = drop pick (default)
  CONFLUENCE_DEBATE_STRICT=false         # log veto but still arm at reduced size

This is the "structural discipline" version of what a human PM would do
before greenlighting each trade — the debate forces the bear case to be
made explicitly instead of assumed away.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Cheap model for bull/bear (they're pattern-generators, not judges)
BULL_BEAR_MODEL = "claude-haiku-4-5-20251001"
# Higher-judgment model for the risk officer (final call)
RISK_OFFICER_MODEL = "claude-sonnet-4-6"

MAX_TOKENS_PER_AGENT = 800


@dataclass
class DebateVerdict:
    ticker: str
    original_conviction: str  # "APPROVE" from hunter
    bull_case: str
    bear_case: str
    risk_officer_verdict: str  # "APPROVE" / "APPROVE_REDUCED" / "VETO"
    risk_officer_reason: str
    size_multiplier: float  # 1.0 = full size, 0.5 = half, 0.0 = vetoed
    audit_json: Dict[str, Any]


def _call_agent(model: str, system: str, prompt: str, max_tokens: int) -> str:
    """Direct Anthropic SDK call — mirrors hunter's approach for consistency."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot run confluence debate")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


_BULL_SYSTEM = """You are the BULL analyst on BMG Capital's confluence framework.
The hunter has already scored this ticker 3+/5 and wants to arm it.
Your job: STEELMAN why this is a great trade. Be specific.
- Name the insiders and what makes their buy meaningful (role, size, timing)
- Name a concrete catalyst likely to hit within horizon_months
- Cite comparable historical setups that worked
Keep it under 200 words. This is one voice in a 3-way debate — the bear
will get to attack right after."""

_BEAR_SYSTEM = """You are the BEAR analyst on BMG Capital's confluence framework.
The hunter wants to arm this pick. Your job: STEELMAN why we should SKIP.
- What's the specific risk that kills this trade in the next 3-6 months?
- Is the insider signal actually meaningful or noise (e.g., 10b5-1 program, tiny for their net worth)?
- What's happening in the sector that makes this the wrong time?
- Is there a hidden setup weakness the hunter missed (crowded short, catalyst
  already priced in, technical breakdown risk)?
Keep it under 200 words. Do NOT be contrarian for the sake of it — if the
trade really is clean, say so briefly. But if you see a genuine reason to
skip, make it hard for the risk officer to override."""

_RISK_OFFICER_SYSTEM = """You are the RISK OFFICER on BMG Capital.
You've been handed a confluence pick + a bull case + a bear case. Your job:
- Weigh bull vs bear like a PM about to commit real capital
- Adjudicate: APPROVE (full size) / APPROVE_REDUCED (half size) / VETO (skip)
- Consider: has the bear case identified an asymmetric risk the bull didn't address?
  Or is the bear cargo-culting standard risks that apply to every trade?

Return JSON:
{
  "verdict": "APPROVE" | "APPROVE_REDUCED" | "VETO",
  "size_multiplier": 1.0 | 0.5 | 0.0,
  "reason": "one-sentence why",
  "key_risk_to_monitor": "one concrete thing to watch post-entry"
}

Rules:
- APPROVE only if bull case is materially stronger than bear case, or bear
  case cites only generic risks.
- APPROVE_REDUCED if bull case is real but bear identifies a specific
  asymmetric downside (e.g., binary event, concentration risk, execution risk).
- VETO if bear identifies a REAL disqualifier the hunter missed (e.g., known
  fundamental problem, activist bear campaign, imminent negative catalyst,
  insider was a required 10b5-1 program buy).

Bias: err toward APPROVE_REDUCED over VETO — the point of the debate is to
size-adjust for real risks, not to eliminate every trade. VETO is for cases
where committing capital is objectively wrong, not merely uncertain."""


def _run_bull_agent(pick: Dict[str, Any]) -> str:
    prompt = _pick_context(pick) + "\n\nWrite the bull case. Under 200 words."
    return _call_agent(BULL_BEAR_MODEL, _BULL_SYSTEM, prompt, MAX_TOKENS_PER_AGENT)


def _run_bear_agent(pick: Dict[str, Any]) -> str:
    prompt = _pick_context(pick) + "\n\nWrite the bear case. Under 200 words."
    return _call_agent(BULL_BEAR_MODEL, _BEAR_SYSTEM, prompt, MAX_TOKENS_PER_AGENT)


def _run_risk_officer(pick: Dict[str, Any], bull: str, bear: str) -> Dict[str, Any]:
    prompt = (
        _pick_context(pick)
        + "\n\n=== BULL CASE ===\n" + bull
        + "\n\n=== BEAR CASE ===\n" + bear
        + "\n\nAdjudicate. Return JSON only."
    )
    resp = _call_agent(RISK_OFFICER_MODEL, _RISK_OFFICER_SYSTEM, prompt, MAX_TOKENS_PER_AGENT)
    # Extract JSON
    m = re.search(r'\{.*?"verdict".*?\}', resp, re.DOTALL)
    if not m:
        logger.warning("[confluence_debate] risk officer returned no JSON: %s", resp[:300])
        return {
            "verdict": "APPROVE_REDUCED",
            "size_multiplier": 0.5,
            "reason": "risk_officer response unparseable — defaulted to reduced size",
            "key_risk_to_monitor": "verify pick manually before scaling",
        }
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {
            "verdict": "APPROVE_REDUCED",
            "size_multiplier": 0.5,
            "reason": "risk_officer JSON malformed — defaulted to reduced size",
            "key_risk_to_monitor": "verify pick manually before scaling",
        }

    # Clamp size_multiplier to valid values
    sm = float(parsed.get("size_multiplier", 1.0))
    if sm not in (0.0, 0.5, 1.0):
        sm = 0.5 if sm > 0 else 0.0
    parsed["size_multiplier"] = sm

    v = parsed.get("verdict", "APPROVE_REDUCED")
    if v not in ("APPROVE", "APPROVE_REDUCED", "VETO"):
        v = "APPROVE_REDUCED"
    parsed["verdict"] = v
    return parsed


def _pick_context(pick: Dict[str, Any]) -> str:
    """Format one pick as debate context."""
    signals = pick.get("signals", {})
    return (
        f"TICKER: {pick.get('ticker', '?')}\n"
        f"Entry: ${pick.get('entry_price', '?')}\n"
        f"Target: ${pick.get('target_price', '?')}\n"
        f"Invalidation: ${pick.get('invalidation_price', '?')}\n"
        f"Horizon: {pick.get('horizon_months', 6)} months\n"
        f"Signals: {json.dumps(signals)}\n"
        f"Thesis (from hunter): {pick.get('thesis_text', 'n/a')}\n"
    )


def run_debate(pick: Dict[str, Any]) -> DebateVerdict:
    """Run the full bull → bear → risk_officer debate for one pick.

    Returns DebateVerdict with the risk officer's verdict + size multiplier.
    Errors default to APPROVE_REDUCED (0.5×) — never VETO on infrastructure failure.
    """
    ticker = pick.get("ticker", "?")
    audit: Dict[str, Any] = {"ticker": ticker}

    try:
        bull = _run_bull_agent(pick)
        audit["bull"] = bull
    except Exception as e:
        logger.exception("[confluence_debate] bull agent failed for %s: %s", ticker, e)
        return DebateVerdict(
            ticker=ticker, original_conviction="APPROVE",
            bull_case=f"[failed: {e}]", bear_case="[not run]",
            risk_officer_verdict="APPROVE_REDUCED",
            risk_officer_reason="bull agent infrastructure failure — default reduced size",
            size_multiplier=0.5, audit_json=audit,
        )

    try:
        bear = _run_bear_agent(pick)
        audit["bear"] = bear
    except Exception as e:
        logger.exception("[confluence_debate] bear agent failed for %s: %s", ticker, e)
        return DebateVerdict(
            ticker=ticker, original_conviction="APPROVE",
            bull_case=bull, bear_case=f"[failed: {e}]",
            risk_officer_verdict="APPROVE_REDUCED",
            risk_officer_reason="bear agent infrastructure failure — default reduced size",
            size_multiplier=0.5, audit_json=audit,
        )

    try:
        ro = _run_risk_officer(pick, bull, bear)
        audit["risk_officer"] = ro
    except Exception as e:
        logger.exception("[confluence_debate] risk officer failed for %s: %s", ticker, e)
        return DebateVerdict(
            ticker=ticker, original_conviction="APPROVE",
            bull_case=bull, bear_case=bear,
            risk_officer_verdict="APPROVE_REDUCED",
            risk_officer_reason="risk officer infrastructure failure — default reduced size",
            size_multiplier=0.5, audit_json=audit,
        )

    return DebateVerdict(
        ticker=ticker,
        original_conviction="APPROVE",
        bull_case=bull,
        bear_case=bear,
        risk_officer_verdict=ro["verdict"],
        risk_officer_reason=ro.get("reason", ""),
        size_multiplier=ro["size_multiplier"],
        audit_json=audit,
    )


def debate_batch(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run the debate over a batch of picks. Returns the filtered/resized list.

    - VETO'd picks are removed entirely.
    - APPROVE_REDUCED picks get pick["size_multiplier"] = 0.5.
    - APPROVE picks pass through with size_multiplier = 1.0.

    Each pick gains pick["debate"] = {bull, bear, risk_officer} for audit trail.
    """
    if os.environ.get("CONFLUENCE_DEBATE_ENABLED", "true").lower() == "false":
        logger.info("[confluence_debate] disabled via env — passing picks through unchanged")
        for p in picks:
            p["size_multiplier"] = 1.0
        return picks

    strict = os.environ.get("CONFLUENCE_DEBATE_STRICT", "true").lower() != "false"
    survivors: List[Dict[str, Any]] = []
    for pick in picks:
        verdict = run_debate(pick)
        pick["size_multiplier"] = verdict.size_multiplier
        pick["debate"] = {
            "bull": verdict.bull_case,
            "bear": verdict.bear_case,
            "risk_officer_verdict": verdict.risk_officer_verdict,
            "risk_officer_reason": verdict.risk_officer_reason,
        }

        if verdict.risk_officer_verdict == "VETO":
            if strict:
                logger.info(
                    "[confluence_debate] VETO %s — %s (dropped, strict mode)",
                    verdict.ticker, verdict.risk_officer_reason,
                )
                continue  # drop
            else:
                logger.info(
                    "[confluence_debate] VETO %s — %s (non-strict: armed at 0.5×)",
                    verdict.ticker, verdict.risk_officer_reason,
                )
                pick["size_multiplier"] = 0.5
                survivors.append(pick)
        else:
            logger.info(
                "[confluence_debate] %s %s (%.1f×) — %s",
                verdict.risk_officer_verdict, verdict.ticker,
                verdict.size_multiplier, verdict.risk_officer_reason,
            )
            survivors.append(pick)

    return survivors
