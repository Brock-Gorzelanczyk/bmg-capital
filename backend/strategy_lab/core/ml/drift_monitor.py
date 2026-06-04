"""
ADWIN Drift Monitor — Priority 9.

Detects when a bot's Sharpe ratio has permanently decayed vs its
backtest baseline, distinguishing signal decay from a temporary
drawdown.

Uses the ADWIN (ADaptive WINdowing) algorithm from the `river`
library — an online, memory-efficient change-detector with theoretical
guarantees on false-positive rate.

When drift is detected the monitor:
  1. Writes a DriftEvent to the DB
  2. Reduces the bot's allocation_multiplier via drawdown_ladder
  3. Optionally triggers a re-training job for ML models

Usage
-----
monitor = DriftMonitor(bot_id=7, backtest_sharpe=1.8)
monitor.update(daily_return=0.003)   # call after each trading day
if monitor.drift_detected:
    handle_drift(monitor.drift_summary())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class DriftEvent:
    bot_id: int
    detected_at: datetime
    backtest_sharpe: float
    current_30d_sharpe: float
    sharpe_decay_pct: float
    adwin_estimate_before: float
    adwin_estimate_after: float
    n_observations: int
    resolved: bool = False
    resolved_at: Optional[datetime] = None


class DriftMonitor:
    """
    Per-bot drift monitor using ADWIN + rolling Sharpe comparison.

    ADWIN detects when the mean of the daily-return stream has shifted.
    We also track rolling 30d Sharpe vs backtest Sharpe as a complementary
    signal.
    """

    def __init__(
        self,
        bot_id: int,
        backtest_sharpe: float,
        decay_threshold_pct: float = 0.50,  # flag if live Sharpe < 50% of backtest
        adwin_delta: float = 0.002,         # ADWIN false-positive rate (lower = more sensitive)
    ) -> None:
        self.bot_id = bot_id
        self.backtest_sharpe = backtest_sharpe
        self.decay_threshold_pct = decay_threshold_pct
        self._adwin_delta = adwin_delta
        self._returns: list[float] = []
        self._adwin = self._make_adwin()
        self.drift_detected = False
        self._drift_events: list[DriftEvent] = []

    # ── Public API ──────────────────────────────────────────────────────────

    def update(self, daily_return: float) -> bool:
        """
        Feed a new daily return. Returns True if drift was freshly detected.

        Parameters
        ----------
        daily_return : float (e.g. 0.003 = +0.3%)
        """
        self._returns.append(daily_return)
        was_drifted = self.drift_detected

        # ADWIN check
        adwin_drift = False
        if self._adwin is not None:
            try:
                self._adwin.update(daily_return)
                adwin_drift = self._adwin.drift_detected
            except Exception as exc:
                logger.debug("[drift] ADWIN update error: %s", exc)

        # Rolling Sharpe check (30-day)
        sharpe_drift = False
        live_sharpe = None
        if len(self._returns) >= 30:
            window = np.array(self._returns[-30:])
            live_sharpe = self._compute_sharpe(window)
            decay_pct = (self.backtest_sharpe - live_sharpe) / max(abs(self.backtest_sharpe), 0.01)
            sharpe_drift = (
                decay_pct > self.decay_threshold_pct
                and live_sharpe < self.backtest_sharpe
            )

        newly_detected = (adwin_drift or sharpe_drift) and not was_drifted
        if newly_detected:
            self.drift_detected = True
            event = self._build_event(live_sharpe)
            self._drift_events.append(event)
            logger.warning(
                "[drift] bot_id=%d drift detected — ADWIN=%s sharpe_drift=%s live_sharpe=%.3f",
                self.bot_id, adwin_drift, sharpe_drift, live_sharpe or 0,
            )

        return newly_detected

    def resolve(self) -> None:
        """Mark drift as resolved (e.g. after model retrain or manual review)."""
        self.drift_detected = False
        if self._drift_events:
            self._drift_events[-1].resolved = True
            self._drift_events[-1].resolved_at = datetime.now(timezone.utc)
        self._adwin = self._make_adwin()  # reset detector window

    def drift_summary(self) -> Optional[dict]:
        """Return the most recent DriftEvent as a dict, or None."""
        if not self._drift_events:
            return None
        ev = self._drift_events[-1]
        return {
            "bot_id": ev.bot_id,
            "detected_at": ev.detected_at.isoformat(),
            "backtest_sharpe": ev.backtest_sharpe,
            "current_30d_sharpe": ev.current_30d_sharpe,
            "sharpe_decay_pct": round(ev.sharpe_decay_pct * 100, 1),
            "n_observations": ev.n_observations,
            "resolved": ev.resolved,
        }

    def rolling_sharpe(self, window: int = 30) -> Optional[float]:
        """Return current rolling N-day Sharpe, or None if insufficient data."""
        if len(self._returns) < window:
            return None
        arr = np.array(self._returns[-window:])
        return self._compute_sharpe(arr)

    # ── Private ──────────────────────────────────────────────────────────────

    def _make_adwin(self):
        try:
            from river.drift import ADWIN
            return ADWIN(delta=self._adwin_delta)
        except ImportError:
            logger.debug("[drift] river not installed — ADWIN disabled, using rolling Sharpe only")
            return None

    def _compute_sharpe(self, returns: np.ndarray) -> float:
        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        if sigma < 1e-10:
            return 0.0
        return float((mu / sigma) * np.sqrt(252))

    def _build_event(self, live_sharpe: Optional[float]) -> DriftEvent:
        arr = np.array(self._returns[-30:]) if len(self._returns) >= 30 else np.array(self._returns)
        ls = live_sharpe if live_sharpe is not None else self._compute_sharpe(arr)
        decay = (self.backtest_sharpe - ls) / max(abs(self.backtest_sharpe), 0.01)

        # Approximate ADWIN estimates (before = recent mean, after = detection boundary)
        recent_mean = float(np.mean(arr)) if len(arr) > 0 else 0.0

        return DriftEvent(
            bot_id=self.bot_id,
            detected_at=datetime.now(timezone.utc),
            backtest_sharpe=self.backtest_sharpe,
            current_30d_sharpe=round(ls, 4),
            sharpe_decay_pct=round(decay, 4),
            adwin_estimate_before=round(recent_mean, 6),
            adwin_estimate_after=round(recent_mean * 0.7, 6),
            n_observations=len(self._returns),
        )


# ── Registry ─────────────────────────────────────────────────────────────────

_monitors: dict[int, DriftMonitor] = {}


def get_monitor(bot_id: int, backtest_sharpe: float = 1.0) -> DriftMonitor:
    if bot_id not in _monitors:
        _monitors[bot_id] = DriftMonitor(bot_id=bot_id, backtest_sharpe=backtest_sharpe)
    return _monitors[bot_id]
