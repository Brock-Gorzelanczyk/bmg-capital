from __future__ import annotations

from datetime import date


def compute_risk_score(
    time_horizon: str,
    loss_tolerance: str,
    has_emergency_fund: bool,
    savings_rate: float,
    experience: str,
) -> float:
    """Returns 1.0-10.0 risk score."""

    # Horizon score (35% weight)
    horizon_map = {"<2yr": 1, "2-5": 3, "5-10": 5, "10-20": 7, "20+": 10}
    h = horizon_map.get(time_horizon, 5)

    # Loss tolerance (30%)
    lt_map = {"sell_all": 1, "sell_some": 4, "hold": 7, "buy_more": 10}
    lt = lt_map.get(loss_tolerance, 5)

    # Capacity / liquidity (25%)
    cap = 8 if has_emergency_fund else 3
    cap += min(savings_rate * 10, 3)  # savings rate 0-30% → 0-3 bonus

    # Experience (10%)
    exp_map = {"none": 2, "some": 5, "experienced": 8, "professional": 10}
    exp = exp_map.get(experience, 5)

    score = (h * 0.35) + (lt * 0.30) + (cap * 0.25) + (exp * 0.10)
    return round(min(max(score, 1.0), 10.0), 1)


def score_to_allocation(score: float) -> dict:
    """Maps 1-10 score to equity/bond/cash target allocation."""
    if score <= 2:
        return {"VTI": 0.10, "VXUS": 0.05, "BND": 0.50, "BNDX": 0.15, "cash": 0.20}
    elif score <= 4:
        return {"VTI": 0.25, "VXUS": 0.10, "BND": 0.40, "BNDX": 0.15, "cash": 0.10}
    elif score <= 6:
        return {"VTI": 0.35, "VXUS": 0.15, "BND": 0.30, "BNDX": 0.10, "cash": 0.10}
    elif score <= 8:
        return {"VTI": 0.50, "VXUS": 0.20, "BND": 0.20, "BNDX": 0.05, "cash": 0.05}
    else:  # 9-10
        return {"VTI": 0.55, "VXUS": 0.25, "VBR": 0.08, "VWO": 0.07, "BND": 0.04, "cash": 0.01}


def compute_glide_path(target_date: date, current_date: date = None) -> list[dict]:
    """
    Returns monthly glide path from now to target_date.
    As horizon shrinks from 20yr → 5yr → 1yr, equity goes 90% → 60% → 10%.
    """
    from datetime import date as d
    if current_date is None:
        current_date = d.today()

    months_until = max(1, (target_date.year - current_date.year) * 12 +
                       (target_date.month - current_date.month))

    # Equity fraction: linear from 90% at 20+yr to 10% at 1yr
    def equity_at_years(y: float) -> float:
        if y >= 20:
            return 0.90
        if y <= 1:
            return 0.10
        return 0.10 + (y - 1) / 19 * 0.80

    path = []
    for m in range(0, min(months_until + 1, 241), max(1, months_until // 24)):
        yr = current_date.year + (current_date.month + m - 1) // 12
        mo = (current_date.month + m - 1) % 12 + 1
        y_left = (months_until - m) / 12.0
        eq = equity_at_years(y_left)
        path.append({
            "date": f"{yr}-{mo:02d}",
            "equity": round(eq, 2),
            "bonds": round((1 - eq) * 0.8, 2),
            "cash": round((1 - eq) * 0.2, 2),
        })
    return path


def monte_carlo_probability(
    target_amount: float,
    current_balance: float,
    monthly_contribution: float,
    months_to_goal: int,
    equity_fraction: float,
    n_simulations: int = 1000,
    seed: int = None,
) -> float:
    """
    Simplified Monte Carlo: lognormal returns.
    Equity: 7% annual mean, 15% std. Bonds: 3% mean, 5% std.
    Returns probability 0-100%.
    """
    import random
    import math

    annual_return = equity_fraction * 0.07 + (1 - equity_fraction) * 0.03
    annual_std = equity_fraction * 0.15 + (1 - equity_fraction) * 0.05
    monthly_mean = annual_return / 12
    monthly_std = annual_std / (12 ** 0.5)

    if seed is not None:
        random.seed(seed)

    successes = 0
    for _ in range(n_simulations):
        balance = current_balance
        for _ in range(months_to_goal):
            r = random.gauss(monthly_mean, monthly_std)
            balance = balance * (1 + r) + monthly_contribution
        if balance >= target_amount:
            successes += 1

    return round(successes / n_simulations * 100, 1)


def monte_carlo_percentiles(
    target_amount: float,
    current_balance: float,
    monthly_contribution: float,
    months_to_goal: int,
    equity_fraction: float,
    n_simulations: int = 2000,
    seed: int = None,
) -> dict:
    """
    Run Monte Carlo and return full distribution statistics.
    Returns probability, expected_value, p10, p50, p90.
    """
    import random

    annual_return = equity_fraction * 0.07 + (1 - equity_fraction) * 0.03
    annual_std = equity_fraction * 0.15 + (1 - equity_fraction) * 0.05
    monthly_mean = annual_return / 12
    monthly_std = annual_std / (12 ** 0.5)

    if seed is not None:
        random.seed(seed)

    final_balances = []
    for _ in range(n_simulations):
        balance = current_balance
        for _ in range(months_to_goal):
            r = random.gauss(monthly_mean, monthly_std)
            balance = balance * (1 + r) + monthly_contribution
        final_balances.append(balance)

    final_balances.sort()
    successes = sum(1 for b in final_balances if b >= target_amount)
    probability_pct = round(successes / n_simulations * 100, 1)
    expected_value = round(sum(final_balances) / n_simulations, 2)

    p10_idx = int(0.10 * n_simulations)
    p50_idx = int(0.50 * n_simulations)
    p90_idx = int(0.90 * n_simulations)

    percentile_10 = round(final_balances[p10_idx], 2)
    percentile_50 = round(final_balances[p50_idx], 2)
    percentile_90 = round(final_balances[p90_idx], 2)

    return {
        "probability_pct": probability_pct,
        "expected_value": expected_value,
        "percentile_10": percentile_10,
        "percentile_50": percentile_50,
        "percentile_90": percentile_90,
    }


def score_to_portfolio_type(score: float) -> str:
    """Maps risk score 1-10 to a human-readable portfolio type label."""
    if score <= 2:
        return "Conservative"
    elif score <= 4:
        return "Moderate"
    elif score <= 6:
        return "Balanced"
    elif score <= 8:
        return "Growth"
    else:
        return "Aggressive Growth"
