"""
Strategy Lifecycle Gates — Weekend 2, Module 5.

Manages the promotion and demotion pipeline:
  research → backtest → paper → live_small → live_full

Promotion rules:
  research → backtest:   CPCV deflated Sharpe > 0.8
  backtest → paper:      30 days forward signals logged
  paper → live_small:    6 months paper Sharpe within 50% of backtest Sharpe
  live_small → live_full: 6 months live Sharpe within 50% of paper Sharpe

Demotion:
  Any phase: 30d rolling Sharpe drops > 50% from that phase's baseline

Permanent retirement:
  -10% lifetime drawdown (enforced by drawdown_ladder.py)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class LifecyclePhase(Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE_SMALL = "live_small"
    LIVE_FULL = "live_full"
    RETIRED = "retired"


# Capital allocation per phase (as fraction of normal allocation)
PHASE_CAPITAL_FRACTION = {
    LifecyclePhase.RESEARCH: 0.0,
    LifecyclePhase.BACKTEST: 0.0,
    LifecyclePhase.PAPER: 0.0,
    LifecyclePhase.LIVE_SMALL: 0.01,   # 1% allocation
    LifecyclePhase.LIVE_FULL: 1.0,
}

PROMOTION_THRESHOLDS = {
    # (from_phase, to_phase): rule description
    (LifecyclePhase.RESEARCH, LifecyclePhase.BACKTEST): "CPCV deflated Sharpe > 0.8",
    (LifecyclePhase.BACKTEST, LifecyclePhase.PAPER): "30 days forward signal generation",
    (LifecyclePhase.PAPER, LifecyclePhase.LIVE_SMALL): "6 months paper Sharpe within 50% of backtest",
    (LifecyclePhase.LIVE_SMALL, LifecyclePhase.LIVE_FULL): "6 months live Sharpe within 50% of paper",
}

DEMOTION_SHARPE_DROP_THRESHOLD = 0.50   # demote if live Sharpe drops > 50% vs phase baseline
MIN_PAPER_MONTHS = 6
MIN_LIVE_SMALL_MONTHS = 6
MIN_FORWARD_SIGNAL_DAYS = 30
MIN_CPCV_SHARPE = 0.8


@dataclass
class LifecycleStatus:
    strategy_id: str
    phase: LifecyclePhase
    phase_entered_at: datetime
    days_in_phase: int
    phase_baseline_sharpe: Optional[float]
    current_30d_sharpe: Optional[float]
    capital_fraction: float
    promotion_eligible: bool
    promotion_reason: Optional[str]
    demotion_risk: bool
    demotion_reason: Optional[str]


def evaluate_lifecycle(
    strategy_id: str,
    current_phase: LifecyclePhase,
    phase_entered_at: datetime,
    backtest_sharpe: Optional[float],
    paper_sharpe: Optional[float],
    live_small_sharpe: Optional[float],
    current_30d_sharpe: Optional[float],
    forward_signal_days: int,
    cpcv_deflated_sharpe: Optional[float],
) -> LifecycleStatus:
    """
    Evaluate whether a strategy should be promoted, demoted, or unchanged.

    Parameters
    ----------
    strategy_id : unique strategy identifier
    current_phase : current LifecyclePhase
    phase_entered_at : when the current phase started
    backtest_sharpe : Sharpe from backtester / CPCV
    paper_sharpe : Sharpe from paper trading period
    live_small_sharpe : Sharpe from live-small period
    current_30d_sharpe : rolling 30-day live Sharpe
    forward_signal_days : days of forward signal logs in paper/live
    cpcv_deflated_sharpe : CPCV-validated Sharpe (used for research→backtest)
    """
    now = datetime.now(timezone.utc)
    days_in_phase = (now - phase_entered_at).days

    promotion_eligible = False
    promotion_reason: Optional[str] = None
    demotion_risk = False
    demotion_reason: Optional[str] = None

    # ── Retirement is terminal ────────────────────────────────────────────
    if current_phase == LifecyclePhase.RETIRED:
        return LifecycleStatus(
            strategy_id=strategy_id,
            phase=LifecyclePhase.RETIRED,
            phase_entered_at=phase_entered_at,
            days_in_phase=days_in_phase,
            phase_baseline_sharpe=None,
            current_30d_sharpe=current_30d_sharpe,
            capital_fraction=0.0,
            promotion_eligible=False,
            promotion_reason=None,
            demotion_risk=False,
            demotion_reason=None,
        )

    # ── Demotion checks (run first — safety override) ─────────────────────
    phase_baseline = _get_phase_baseline(
        current_phase, backtest_sharpe, paper_sharpe, live_small_sharpe
    )
    if (
        current_phase in (LifecyclePhase.PAPER, LifecyclePhase.LIVE_SMALL, LifecyclePhase.LIVE_FULL)
        and current_30d_sharpe is not None
        and phase_baseline is not None
        and phase_baseline > 0
    ):
        decay = (phase_baseline - current_30d_sharpe) / phase_baseline
        if decay > DEMOTION_SHARPE_DROP_THRESHOLD:
            demotion_risk = True
            demotion_reason = (
                f"30d Sharpe {current_30d_sharpe:.2f} is {decay*100:.0f}% below "
                f"phase baseline {phase_baseline:.2f}"
            )
            logger.warning(
                "[lifecycle] %s DEMOTION RISK in %s — %s",
                strategy_id, current_phase.value, demotion_reason,
            )

    # ── Promotion checks ──────────────────────────────────────────────────
    if current_phase == LifecyclePhase.RESEARCH:
        if (
            cpcv_deflated_sharpe is not None
            and cpcv_deflated_sharpe >= MIN_CPCV_SHARPE
        ):
            promotion_eligible = True
            promotion_reason = (
                f"CPCV deflated Sharpe {cpcv_deflated_sharpe:.2f} ≥ {MIN_CPCV_SHARPE}"
            )

    elif current_phase == LifecyclePhase.BACKTEST:
        if forward_signal_days >= MIN_FORWARD_SIGNAL_DAYS:
            promotion_eligible = True
            promotion_reason = (
                f"{forward_signal_days} days of forward signal generation "
                f"(required: {MIN_FORWARD_SIGNAL_DAYS})"
            )

    elif current_phase == LifecyclePhase.PAPER:
        if (
            days_in_phase >= MIN_PAPER_MONTHS * 30
            and paper_sharpe is not None
            and backtest_sharpe is not None
            and backtest_sharpe > 0
        ):
            ratio = paper_sharpe / backtest_sharpe
            if ratio >= 0.5:
                promotion_eligible = True
                promotion_reason = (
                    f"Paper Sharpe {paper_sharpe:.2f} is {ratio*100:.0f}% of "
                    f"backtest {backtest_sharpe:.2f} (required: 50%) "
                    f"after {days_in_phase}d"
                )

    elif current_phase == LifecyclePhase.LIVE_SMALL:
        if (
            days_in_phase >= MIN_LIVE_SMALL_MONTHS * 30
            and live_small_sharpe is not None
            and paper_sharpe is not None
            and paper_sharpe > 0
        ):
            ratio = live_small_sharpe / paper_sharpe
            if ratio >= 0.5:
                promotion_eligible = True
                promotion_reason = (
                    f"Live-small Sharpe {live_small_sharpe:.2f} is {ratio*100:.0f}% of "
                    f"paper {paper_sharpe:.2f} (required: 50%) "
                    f"after {days_in_phase}d"
                )

    if promotion_eligible:
        logger.info(
            "[lifecycle] %s eligible for promotion from %s — %s",
            strategy_id, current_phase.value, promotion_reason,
        )

    return LifecycleStatus(
        strategy_id=strategy_id,
        phase=current_phase,
        phase_entered_at=phase_entered_at,
        days_in_phase=days_in_phase,
        phase_baseline_sharpe=phase_baseline,
        current_30d_sharpe=current_30d_sharpe,
        capital_fraction=PHASE_CAPITAL_FRACTION.get(current_phase, 0.0),
        promotion_eligible=promotion_eligible,
        promotion_reason=promotion_reason,
        demotion_risk=demotion_risk,
        demotion_reason=demotion_reason,
    )


def next_phase(current: LifecyclePhase) -> Optional[LifecyclePhase]:
    """Return the next phase in the pipeline, or None if already at live_full."""
    order = [
        LifecyclePhase.RESEARCH,
        LifecyclePhase.BACKTEST,
        LifecyclePhase.PAPER,
        LifecyclePhase.LIVE_SMALL,
        LifecyclePhase.LIVE_FULL,
    ]
    try:
        idx = order.index(current)
        return order[idx + 1] if idx + 1 < len(order) else None
    except ValueError:
        return None


def prev_phase(current: LifecyclePhase) -> Optional[LifecyclePhase]:
    """Return the previous phase for demotion, or None if already at research."""
    order = [
        LifecyclePhase.RESEARCH,
        LifecyclePhase.BACKTEST,
        LifecyclePhase.PAPER,
        LifecyclePhase.LIVE_SMALL,
        LifecyclePhase.LIVE_FULL,
    ]
    try:
        idx = order.index(current)
        return order[idx - 1] if idx > 0 else None
    except ValueError:
        return None


def _get_phase_baseline(
    phase: LifecyclePhase,
    backtest_sharpe: Optional[float],
    paper_sharpe: Optional[float],
    live_small_sharpe: Optional[float],
) -> Optional[float]:
    if phase == LifecyclePhase.PAPER:
        return backtest_sharpe
    if phase == LifecyclePhase.LIVE_SMALL:
        return paper_sharpe
    if phase == LifecyclePhase.LIVE_FULL:
        return live_small_sharpe
    return None
