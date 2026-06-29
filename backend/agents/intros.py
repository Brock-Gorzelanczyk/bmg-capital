"""R7 — Static agent intro lines (replaces Haiku LLM call in intro_conversation.py).

No LLM required. Static strings per agent persona.
"""
from __future__ import annotations

INTROS: dict[str, str] = {
    "brick":   "Brick reporting — PM desk. Standups are 6:30 AM ET weekdays. I track signal quality, gate rates, and allocation drift. Today I'm watching regime transition signals and cooldown expirations across the fleet.",
    "dick":    "Dick here — CRO. I'm watching drawdowns, leverage, concentration, and the $5/day fallback budget. Red flags get paged immediately; yellows go to weekly review.",
    "nick":    "Nick — equity research. Single-name theses and sector flows. I surface high-conviction watchlist names and flag divergences between analyst price targets and current positioning.",
    "mick":    "Mick — quant. Backtest reviews, regime gating, Sharpe decomposition. I keep strategy_lab honest and call out overfitting before it hits live capital.",
    "vick":    "Vick — data quality. Feed integrity, reconciliation breaks, canonical aggregator drift. If a price feed or position count looks wrong, I'm the one who finds it first.",
    "rick":    "Rick — risk console. Same mandate as Dick but UI-facing. I surface VAR budget, concentration gates, and drawdown warnings on the dashboard in real time.",
    "slick":   "Slick — execution analyst. Fill quality, slippage vs model, simulator vs live divergence. I flag the equity-fallback trap and per-bot asset_class mismatches.",
    "wick":    "Wick — chart pattern detection. Candle structure, breakout confirmation, volume profile. I arm setups in Scout and track pattern success rates by strategy.",
    "patrick": "Patrick — macro. Rates, dollar, regime calls. I advise on positioning in VIX-spike environments and flag sector rotations driven by Fed policy shifts.",
}


def get_intro(agent_name: str) -> str:
    """Return the static intro line for the given agent. Fallback to generic if unknown."""
    return INTROS.get(agent_name.lower(), f"{agent_name} reporting in.")
