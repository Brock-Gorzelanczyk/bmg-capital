"""Discipline filter — 3 gates every signal must pass before execution.

Gates:
  1. Regime mismatch — strategy.regime_preference vs current regime
  2. Composite score < threshold — weighted blend of factors
  3. Insufficient confluence — < 3 of 5 factors aligned

Used by strategy_lab.runner. One SignalGate row per BotSignal so
"why didn't this fire?" is answerable from the DB alone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Map our internal regime words to a normalized set that strategies can declare.
# RegimeSnapshot has trend_regime ∈ {bull,bear,chop} and vix_regime ∈ {low,mid,high,panic}.
_REGIME_NAMES = {"bull_trending", "bear_trending", "choppy", "low_vol", "crisis", "any"}


@dataclass
class GateResult:
    # Gate 1 — regime
    regime_passed: bool = True
    regime_current: Optional[str] = None
    regime_required: Optional[str] = None
    # Gate 2 — score
    composite_score: int = 0
    composite_threshold: int = 60
    score_passed: bool = True
    # Gate 3 — confluence
    confluence_factors_passed: int = 0
    confluence_required: int = 3
    confluence_passed: bool = True
    # Per-factor diagnostics (not persisted; useful for tracing)
    factor_breakdown: dict[str, bool] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return self.regime_passed and self.score_passed and self.confluence_passed

    @property
    def filter_reason(self) -> Optional[str]:
        if self.all_passed:
            return None
        failed = []
        if not self.regime_passed:
            failed.append("regime_mismatch")
        if not self.score_passed:
            failed.append("score_below_threshold")
        if not self.confluence_passed:
            failed.append("insufficient_confluence")
        return failed[0] if len(failed) == 1 else "multiple"


def _current_regime(db) -> str:
    """Returns one of: bull_trending | bear_trending | choppy | low_vol | crisis | unknown.

    Reads the latest RegimeSnapshot. Maps:
      vix=panic            → crisis
      vix=low + trend=chop → low_vol
      trend=bull           → bull_trending
      trend=bear           → bear_trending
      trend=chop           → choppy
      anything else        → unknown (treated as "any" for matching purposes)
    """
    try:
        from app.db.models.bots import RegimeSnapshot
        snap = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).first()
        if not snap:
            return "unknown"
        vix = (snap.vix_regime or "").lower()
        trend = (snap.trend_regime or "").lower()
        if vix == "panic":
            return "crisis"
        if vix == "low" and trend == "chop":
            return "low_vol"
        if trend == "bull":
            return "bull_trending"
        if trend == "bear":
            return "bear_trending"
        if trend == "chop":
            return "choppy"
    except Exception as exc:
        logger.debug("[discipline] regime fetch failed: %s", exc)
    return "unknown"


def _regime_gate(profile: dict, current_regime: str) -> tuple[bool, str]:
    """Gate 1. Returns (passed, required_regime).

    profile may carry `regime_preference` either at top-level or under
    `discipline.regime_preference`. If absent, default to "any" (always pass).
    """
    pref = (
        profile.get("regime_preference")
        or (profile.get("discipline") or {}).get("regime_preference")
        or "any"
    )
    pref = str(pref).lower().strip()
    if pref not in _REGIME_NAMES:
        pref = "any"
    if pref == "any" or current_regime == "unknown":
        return True, pref
    return (pref == current_regime), pref


def _recent_strategy_win_rate(db, allocation_id: int, strategy: str | None) -> float:
    """Win rate over last 20 closed BotTrades for this allocation+strategy.

    Returns 0.5 if no history (neutral baseline so new strategies aren't penalized).
    """
    if not strategy:
        return 0.5
    try:
        from app.db.models.bots import BotTrade
        # Closed trades (side in sell/cover) over last 20 for this allocation
        recent = (
            db.query(BotTrade)
            .filter(
                BotTrade.allocation_id == allocation_id,
                BotTrade.side.in_(("sell", "cover")),
                BotTrade.realized_pnl_cents.isnot(None),
            )
            .order_by(BotTrade.id.desc())
            .limit(20)
            .all()
        )
        if not recent:
            return 0.5
        wins = sum(1 for t in recent if (t.realized_pnl_cents or 0) > 0)
        return wins / len(recent)
    except Exception:
        return 0.5


def _composite_score(
    sig: Any,
    profile: dict,
    current_regime: str,
    regime_passed: bool,
    db,
    allocation_id: int,
) -> int:
    """Gate 2 score 0-100. Weighted blend of factors available on the Signal.

    Weights (sum to 1.0):
      confidence:       0.35   raw strategy confidence (0..1)
      regime_fit:       0.20   1.0 if matched, 0.6 if "any" declared, 0.3 otherwise
      volume_agreement: 0.15   from sig.reason JSON if present, else 0.5
      mtf_alignment:    0.15   from sig.reason JSON if present, else 0.5
      recent_win_rate:  0.15   last 20 trades on this allocation+strategy
    """
    confidence = float(getattr(sig, "confidence", 0.0) or 0.0)

    pref = (
        profile.get("regime_preference")
        or (profile.get("discipline") or {}).get("regime_preference")
        or "any"
    )
    if pref == "any":
        regime_fit = 0.6
    elif regime_passed:
        regime_fit = 1.0
    else:
        regime_fit = 0.3

    # Pull optional features from sig.reason JSON (strategies that emit it get a real boost)
    vol_agree = 0.5
    mtf_align = 0.5
    try:
        import json as _json
        reason = getattr(sig, "reason", None)
        if reason:
            r = _json.loads(reason) if isinstance(reason, str) else reason
            if isinstance(r, dict):
                vol_agree = float(r.get("volume_agreement", r.get("vol_agreement", 0.5)))
                mtf_align = float(r.get("mtf_alignment", r.get("mtf", 0.5)))
                vol_agree = max(0.0, min(1.0, vol_agree))
                mtf_align = max(0.0, min(1.0, mtf_align))
    except Exception:
        pass

    win_rate = _recent_strategy_win_rate(db, allocation_id, getattr(sig, "strategy", None))

    score = (
        0.35 * confidence
        + 0.20 * regime_fit
        + 0.15 * vol_agree
        + 0.15 * mtf_align
        + 0.15 * win_rate
    )
    return int(round(score * 100))


def _confluence_factors(
    sig: Any,
    profile: dict,
    current_regime: str,
    regime_passed: bool,
) -> dict[str, bool]:
    """Gate 3 — returns 5 boolean factors. Need >= 3 True to pass.

    Factors:
      trend_agreement: profile regime_preference matches current
      volume_confirmation: vol_agreement >= 0.5 from reason JSON
      time_of_day_favorable: within profile.active_hours (or always true if unset)
      volatility_regime: current VIX regime != panic
      cross_asset_agreement: sig.reason JSON had cross_asset_agree=True
    """
    import json as _json

    factors: dict[str, bool] = {}

    # 1. trend_agreement (uses regime gate's matched/any logic; "any" still counts as aligned)
    pref = (
        profile.get("regime_preference")
        or (profile.get("discipline") or {}).get("regime_preference")
        or "any"
    )
    factors["trend_agreement"] = bool(pref == "any" or regime_passed)

    # Parse reason JSON once
    reason_data: dict = {}
    try:
        reason = getattr(sig, "reason", None)
        if reason:
            r = _json.loads(reason) if isinstance(reason, str) else reason
            if isinstance(r, dict):
                reason_data = r
    except Exception:
        pass

    # 2. volume_confirmation
    factors["volume_confirmation"] = float(
        reason_data.get("volume_agreement", reason_data.get("vol_agreement", 0.5)) or 0.5
    ) >= 0.5

    # 3. time_of_day_favorable
    active = profile.get("active_hours_et") or (profile.get("discipline") or {}).get("active_hours_et")
    if not active:
        factors["time_of_day_favorable"] = True
    else:
        try:
            start_s, end_s = active.split("-")
            now_et = datetime.now(timezone(timedelta(hours=-4)))  # rough ET; bot schedules use ET
            now_min = now_et.hour * 60 + now_et.minute
            sh, sm = [int(x) for x in start_s.split(":")]
            eh, em = [int(x) for x in end_s.split(":")]
            factors["time_of_day_favorable"] = (sh * 60 + sm) <= now_min <= (eh * 60 + em)
        except Exception:
            factors["time_of_day_favorable"] = True

    # 4. volatility_regime — non-crisis is acceptable
    factors["volatility_regime"] = current_regime != "crisis"

    # 5. cross_asset_agreement — true if strategy reported it, else default false (conservative)
    factors["cross_asset_agreement"] = bool(reason_data.get("cross_asset_agree", False))

    return factors


def evaluate_gates(
    db,
    sig: Any,
    profile: dict,
    allocation_id: int,
) -> GateResult:
    """Run all 3 gates on a signal. Pure function — does not persist."""
    threshold = int(
        profile.get("composite_threshold")
        or (profile.get("discipline") or {}).get("composite_threshold")
        or 60
    )
    confluence_required = int(
        profile.get("confluence_required")
        or (profile.get("discipline") or {}).get("confluence_required")
        or 3
    )

    current_regime = _current_regime(db)
    regime_passed, regime_required = _regime_gate(profile, current_regime)
    score = _composite_score(sig, profile, current_regime, regime_passed, db, allocation_id)
    factors = _confluence_factors(sig, profile, current_regime, regime_passed)
    factors_passed = sum(1 for v in factors.values() if v)

    return GateResult(
        regime_passed=regime_passed,
        regime_current=current_regime,
        regime_required=regime_required,
        composite_score=score,
        composite_threshold=threshold,
        score_passed=score >= threshold,
        confluence_factors_passed=factors_passed,
        confluence_required=confluence_required,
        confluence_passed=factors_passed >= confluence_required,
        factor_breakdown=factors,
    )


def persist_gate(
    db,
    signal_id: Optional[int],
    bot_name: str,
    sig: Any,
    result: GateResult,
) -> None:
    """Write one SignalGate row. Best-effort — never raises."""
    try:
        from app.db.models.signal_gates import SignalGate
        row = SignalGate(
            signal_id=signal_id,
            bot_name=bot_name,
            strategy=getattr(sig, "strategy", None),
            symbol=getattr(sig, "symbol", "") or "",
            side=getattr(sig, "side", None),
            regime_gate_passed=result.regime_passed,
            regime_current=result.regime_current,
            regime_required=result.regime_required,
            composite_score=result.composite_score,
            composite_threshold=result.composite_threshold,
            score_gate_passed=result.score_passed,
            confluence_factors_passed=result.confluence_factors_passed,
            confluence_required=result.confluence_required,
            confluence_gate_passed=result.confluence_passed,
            final_decision="executed" if result.all_passed else "filtered",
            filter_reason=result.filter_reason,
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("[discipline] persist_gate failed: %s", exc)
