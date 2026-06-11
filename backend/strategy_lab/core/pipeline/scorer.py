"""Composite promotion scorer — evaluates whether a candidate passes all gates."""
from __future__ import annotations

from dataclasses import dataclass, field

PROMOTION_GATES = {
    "wfe_min":         0.50,   # Hard gate: walk-forward efficiency
    "oos_sharpe_min":  0.75,   # Hard gate: out-of-sample Sharpe
    "dsr_min":         0.90,   # Hard gate: deflated Sharpe ratio
    "pbo_max":         0.10,   # Hard gate: probability of backtest overfitting
    "net_sharpe_min":  0.50,   # Hard gate: net-of-cost Sharpe
    "cost_drag_max":   0.30,   # Soft warning: cost drag fraction
}

_SHADOW_DAYS_REQUIRED = 63


@dataclass
class GateResult:
    passes: bool
    hard_failures: list[str]
    soft_warnings: list[str]
    score: float          # 0.0–1.0 composite
    details: dict


def evaluate_promotion(
    backtest_result: dict,
    wfa_result: dict,
    shadow_days: int = 0,
) -> GateResult:
    """Return GateResult. passes=True only if all hard gates pass AND shadow_days >= 63."""
    hard_failures: list[str] = []
    soft_warnings: list[str] = []
    details: dict = {}

    # ── Pull values ───────────────────────────────────────────────────────────
    net_sharpe  = float(backtest_result.get("net_sharpe")  or backtest_result.get("sharpe") or 0.0)
    cost_pct    = float(backtest_result.get("total_cost_pct") or 0.0)
    wfe         = float(wfa_result.get("wfe") or 0.0)
    oos_sharpe  = float(wfa_result.get("aggregate_oos_sharpe") or 0.0)
    dsr         = float(wfa_result.get("dsr") or 0.0)
    pbo         = float(wfa_result.get("pbo") or 1.0)

    details = {
        "net_sharpe":   net_sharpe,
        "cost_pct":     cost_pct,
        "wfe":          wfe,
        "oos_sharpe":   oos_sharpe,
        "dsr":          dsr,
        "pbo":          pbo,
        "shadow_days":  shadow_days,
    }

    # ── Hard gates ────────────────────────────────────────────────────────────
    if wfe < PROMOTION_GATES["wfe_min"]:
        hard_failures.append(f"WFE {wfe:.2f} < {PROMOTION_GATES['wfe_min']} required")
    if oos_sharpe < PROMOTION_GATES["oos_sharpe_min"]:
        hard_failures.append(f"OOS Sharpe {oos_sharpe:.2f} < {PROMOTION_GATES['oos_sharpe_min']} required")
    if dsr < PROMOTION_GATES["dsr_min"]:
        hard_failures.append(f"DSR {dsr:.2f} < {PROMOTION_GATES['dsr_min']} required")
    if pbo > PROMOTION_GATES["pbo_max"]:
        hard_failures.append(f"PBO {pbo:.2f} > {PROMOTION_GATES['pbo_max']} max")
    if net_sharpe < PROMOTION_GATES["net_sharpe_min"]:
        hard_failures.append(f"Net Sharpe {net_sharpe:.2f} < {PROMOTION_GATES['net_sharpe_min']} required")
    if shadow_days < _SHADOW_DAYS_REQUIRED:
        hard_failures.append(f"Shadow period {shadow_days}d < {_SHADOW_DAYS_REQUIRED}d required")

    # ── Soft warnings ─────────────────────────────────────────────────────────
    if cost_pct > PROMOTION_GATES["cost_drag_max"]:
        soft_warnings.append(f"Cost drag {cost_pct:.1%} > {PROMOTION_GATES['cost_drag_max']:.0%} — consider reducing turnover")

    # ── Composite score (0–1) ─────────────────────────────────────────────────
    # Normalize each metric to 0–1 contribution
    components = [
        min(1.0, max(0.0, wfe        / 1.0)),
        min(1.0, max(0.0, oos_sharpe / 2.0)),
        min(1.0, max(0.0, dsr        / 1.0)),
        min(1.0, max(0.0, (PROMOTION_GATES["pbo_max"] - pbo + 0.1) / 0.2)),
        min(1.0, max(0.0, net_sharpe / 2.0)),
        min(1.0, max(0.0, shadow_days / _SHADOW_DAYS_REQUIRED)),
    ]
    score = round(sum(components) / len(components), 3)

    return GateResult(
        passes=len(hard_failures) == 0,
        hard_failures=hard_failures,
        soft_warnings=soft_warnings,
        score=score,
        details=details,
    )
