"""
Concentration Caps — Weekend 4, Module 9.

Hard pre-trade limits:
  max_single_position_pct: 10% of account equity
  max_sector_concentration_pct: 30% of account equity
  max_factor_beta: 1.5 (Fama-French style)

Raises ConcentrationError on violation. Integrated with pretrade_risk_gate.

Direct response to the Amaranth Advisors failure:
$6.6B loss from 30%+ concentration in single commodity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Hard limits (can be overridden per-account in future DB config)
MAX_SINGLE_POSITION_PCT = 10.0
MAX_SECTOR_PCT = 30.0
MAX_FACTOR_BETA = 1.5

SECTOR_MAP: dict[str, str] = {
    # ETFs / common names — extend via DB in production
    "SPY": "broad_market", "QQQ": "technology", "IWM": "small_cap",
    "XLK": "technology", "XLF": "financials", "XLE": "energy",
    "XLV": "healthcare", "XLY": "consumer_disc", "XLP": "consumer_staple",
    "XLI": "industrials", "XLB": "materials", "XLU": "utilities",
    "XLC": "communication", "XLRE": "real_estate",
    "GLD": "commodities", "SLV": "commodities", "USO": "commodities",
    "TLT": "bonds", "IEF": "bonds", "AGG": "bonds", "BIL": "cash",
}


class ConcentrationError(Exception):
    def __init__(self, reason: str, check_name: str) -> None:
        super().__init__(f"[{check_name}] {reason}")
        self.reason = reason
        self.check_name = check_name


@dataclass
class Portfolio:
    """Snapshot of current portfolio used for concentration checks."""
    account_equity_usd: float
    positions: list[dict] = field(default_factory=list)
    # Each position: {"symbol": str, "notional_usd": float, "sector": str, "beta": float}


def check_single_position(
    symbol: str,
    current_notional_usd: float,
    proposed_notional_usd: float,
    account_equity_usd: float,
    max_pct: float = MAX_SINGLE_POSITION_PCT,
) -> None:
    """Raise ConcentrationError if position would exceed single-name cap."""
    if account_equity_usd <= 0:
        return
    new_total = current_notional_usd + proposed_notional_usd
    pct = (new_total / account_equity_usd) * 100
    if pct > max_pct:
        raise ConcentrationError(
            f"{symbol} position would be {pct:.1f}% of equity "
            f"(limit: {max_pct}%)",
            "single_position_cap",
        )


def check_sector_concentration(
    proposed_symbol: str,
    proposed_notional_usd: float,
    portfolio: Portfolio,
    max_pct: float = MAX_SECTOR_PCT,
) -> None:
    """Raise ConcentrationError if sector would exceed sector cap."""
    sector = SECTOR_MAP.get(proposed_symbol.upper(), "unknown")
    if sector == "unknown":
        return  # no sector data — skip check

    sector_exposure = sum(
        p["notional_usd"]
        for p in portfolio.positions
        if p.get("sector") == sector
    )
    new_sector = sector_exposure + proposed_notional_usd
    pct = (new_sector / max(portfolio.account_equity_usd, 1)) * 100

    if pct > max_pct:
        raise ConcentrationError(
            f"Adding {proposed_symbol} would bring {sector} sector to "
            f"{pct:.1f}% of equity (limit: {max_pct}%)",
            "sector_concentration",
        )


def check_factor_beta(
    portfolio: Portfolio,
    proposed_beta: float,
    proposed_notional_usd: float,
    max_beta: float = MAX_FACTOR_BETA,
) -> None:
    """
    Check portfolio-level market beta won't exceed cap.

    portfolio_beta = weighted avg of position betas.
    """
    if portfolio.account_equity_usd <= 0:
        return

    total_notional = sum(p.get("notional_usd", 0) for p in portfolio.positions)
    weighted_beta = sum(
        p.get("beta", 1.0) * p.get("notional_usd", 0)
        for p in portfolio.positions
    )

    new_total = total_notional + proposed_notional_usd
    new_weighted = weighted_beta + proposed_beta * proposed_notional_usd

    if new_total <= 0:
        return

    portfolio_beta = new_weighted / new_total
    if portfolio_beta > max_beta:
        raise ConcentrationError(
            f"Portfolio beta would reach {portfolio_beta:.2f} (limit: {max_beta})",
            "factor_beta_cap",
        )


def check_all(
    proposed_symbol: str,
    proposed_notional_usd: float,
    proposed_beta: float,
    current_symbol_notional_usd: float,
    portfolio: Portfolio,
) -> None:
    """
    Run all three concentration checks in one call.
    Raises ConcentrationError on first violation.
    """
    check_single_position(
        proposed_symbol,
        current_symbol_notional_usd,
        proposed_notional_usd,
        portfolio.account_equity_usd,
    )
    check_sector_concentration(proposed_symbol, proposed_notional_usd, portfolio)
    check_factor_beta(portfolio, proposed_beta, proposed_notional_usd)
