"""
Transaction Cost Analysis Logger — Weekend 5, Module 14.

On every fill, logs: decision_ts, arrival_mid, submit_ts, fill_ts,
fill_px, quoted_spread, effective_spread, OBI_at_submit.

Nightly: computes IS decomposition per bot/strategy/algo:
  IS = explicit_costs + delay_cost + market_impact + opportunity_cost

Weekly: regresses slippage on sqrt(qty/ADV) to recalibrate impact coefficient.

Surfaces in bot detail "Execution Quality" tab.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TCAFill:
    """Full TCA record for one fill event."""
    fill_id: str
    symbol: str
    side: str
    qty: float
    algo_used: str              # "IS" | "VWAP" | "POV" | "ICEBERG" | "MARKET"

    # Timestamps (unix seconds)
    decision_ts: float
    submit_ts: float
    fill_ts: float

    # Prices
    arrival_mid: float          # NBBO mid at decision time
    fill_px: float

    # Spread & book
    quoted_spread_usd: float    # ask - bid at submit time
    effective_spread_usd: float # 2 × |fill_px - mid_at_submit|
    obi_at_submit: float        # order book imbalance [-1,1]

    # ADV context (for normalizing impact)
    adv_shares: float = 0.0

    # Computed fields (populated by compute_is_decomposition)
    slippage_bps: float = 0.0
    delay_cost_bps: float = 0.0
    market_impact_bps: float = 0.0
    opportunity_cost_bps: float = 0.0
    total_is_bps: float = 0.0


def compute_is_decomposition(fill: TCAFill) -> TCAFill:
    """
    Decompose Implementation Shortfall into components.

    IS = (fill_px - arrival_mid) / arrival_mid × 10000  (for buys)
    Components:
      delay_cost     = (mid_at_submit - arrival_mid) approximated by quoted spread × delay_factor
      market_impact  = (fill_px - mid_at_submit) — the "alpha decay" during execution
      opportunity    = shortfall from unfilled qty (set to 0 here, requires full order context)
    """
    if fill.arrival_mid <= 0:
        return fill

    sign = 1 if fill.side == "buy" else -1

    # Total IS vs arrival
    total_is = sign * (fill.fill_px - fill.arrival_mid) / fill.arrival_mid * 10_000
    fill.slippage_bps = round(total_is, 2)

    # Delay cost: time elapsed from decision to submit (market moves against us)
    delay_seconds = fill.submit_ts - fill.decision_ts
    delay_factor = min(1.0, delay_seconds / 60.0)  # normalize to 1 minute max
    delay_cost = fill.quoted_spread_usd / fill.arrival_mid * 10_000 * delay_factor * 0.5
    fill.delay_cost_bps = round(delay_cost, 2)

    # Market impact: effective spread half (rest is market impact)
    eff_half = (fill.effective_spread_usd / 2) / fill.arrival_mid * 10_000
    fill.market_impact_bps = round(max(0, total_is - delay_cost - eff_half), 2)

    fill.opportunity_cost_bps = 0.0  # requires order-level context
    fill.total_is_bps = round(total_is, 2)

    return fill


class TCALogger:
    """
    In-memory TCA logger with nightly aggregation.
    In production, writes to TcaFill DB table.
    """

    def __init__(self) -> None:
        self._fills: list[TCAFill] = []

    def log_fill(self, fill: TCAFill) -> TCAFill:
        """Record a fill and compute IS decomposition."""
        fill = compute_is_decomposition(fill)
        self._fills.append(fill)
        logger.info(
            "[tca] %s %s %.0f @ %.4f | IS=%.1fbps delay=%.1fbps impact=%.1fbps obi=%.2f",
            fill.side, fill.symbol, fill.qty, fill.fill_px,
            fill.total_is_bps, fill.delay_cost_bps, fill.market_impact_bps, fill.obi_at_submit,
        )
        return fill

    def algo_summary(self, algo: Optional[str] = None) -> dict:
        """Aggregate IS stats by algo (or overall if algo=None)."""
        fills = [f for f in self._fills if algo is None or f.algo_used == algo]
        if not fills:
            return {"n_fills": 0}

        slippages = np.array([f.slippage_bps for f in fills])
        return {
            "n_fills": len(fills),
            "algo": algo or "all",
            "mean_is_bps": round(float(np.mean(slippages)), 2),
            "median_is_bps": round(float(np.median(slippages)), 2),
            "std_is_bps": round(float(np.std(slippages)), 2),
            "p95_is_bps": round(float(np.percentile(slippages, 95)), 2),
            "mean_delay_bps": round(float(np.mean([f.delay_cost_bps for f in fills])), 2),
            "mean_impact_bps": round(float(np.mean([f.market_impact_bps for f in fills])), 2),
        }

    def calibrate_impact_coef(self) -> Optional[float]:
        """
        Weekly regression: slippage ~ α × sqrt(qty/ADV).
        Returns estimated α (impact coefficient).
        """
        fills = [f for f in self._fills if f.adv_shares > 0 and f.qty > 0]
        if len(fills) < 20:
            return None

        X = np.array([np.sqrt(f.qty / f.adv_shares) for f in fills]).reshape(-1, 1)
        y = np.array([f.slippage_bps for f in fills])

        # OLS with intercept
        X_aug = np.column_stack([np.ones(len(X)), X])
        try:
            beta, _, _, _ = np.linalg.lstsq(X_aug, y, rcond=None)
            alpha = float(beta[1])
            logger.info("[tca] calibrated impact coef α=%.4f", alpha)
            return alpha
        except np.linalg.LinAlgError:
            return None

    def recent_fills(self, n: int = 50) -> list[dict]:
        """Return last N fills as dicts for API response."""
        return [
            {
                "fill_id": f.fill_id,
                "symbol": f.symbol,
                "side": f.side,
                "qty": f.qty,
                "fill_px": f.fill_px,
                "algo": f.algo_used,
                "slippage_bps": f.slippage_bps,
                "delay_cost_bps": f.delay_cost_bps,
                "market_impact_bps": f.market_impact_bps,
                "obi_at_submit": f.obi_at_submit,
                "fill_ts": datetime.fromtimestamp(f.fill_ts, tz=timezone.utc).isoformat(),
            }
            for f in self._fills[-n:][::-1]
        ]

    def clear(self) -> None:
        self._fills.clear()


_logger_instance: Optional[TCALogger] = None


def get_tca_logger() -> TCALogger:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = TCALogger()
    return _logger_instance
