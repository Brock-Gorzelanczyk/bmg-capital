"""
cost_model.py — Round-trip cost estimation for paper trades.
Almgren-Chriss square-root market impact + realistic exchange fees.
Pure analytics: no trading mutations, no external dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Fee tables
# ---------------------------------------------------------------------------

EXCHANGE_FEES: dict[str, dict[str, float]] = {
    "alpaca_equity": {"maker": 0.0,  "taker": 0.0},   # PFOF ~1.5 bps implicit
    "binance_spot":  {"maker": 7.5,  "taker": 7.5},   # with BNB discount
    "binance_perp":  {"maker": 2.0,  "taker": 5.0},
    "coinbase":      {"maker": 5.0,  "taker": 20.0},
    "kraken":        {"maker": 16.0, "taker": 26.0},
}

HALF_SPREAD_BPS: dict[str, float] = {
    "equity_large_cap": 1.5,   # AAPL, MSFT, SPY
    "equity_mid_cap":   3.0,
    "equity_small_cap": 8.0,
    "btc":              2.0,   # BTC/USD
    "eth":              2.5,
    "crypto_large":     3.5,   # top-20 alts
    "crypto_mid":       8.0,
    "futures":          0.5,
    "default":          5.0,
}

# DDL for persisting daily cost rollup results.
BOT_COST_ANALYSIS_DDL: str = """
CREATE TABLE IF NOT EXISTS bot_cost_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    gross_return_pct REAL,
    total_cost_pct REAL,
    net_return_pct REAL,
    cost_drag_pct REAL,
    n_trades INTEGER,
    per_trade_avg_bps REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bot_id, snapshot_date)
);
"""

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_ALPACA_PFOF_BPS: float = 1.5          # implicit PFOF added on top of stated 0 fee
_AC_ETA: float = 0.32                   # Almgren-Chriss linear impact coefficient
_DEFAULT_ADV_RATIO: float = 0.001       # Q/ADV fallback when ADV unknown
_DEFAULT_DAILY_VOL: float = 0.02        # 2% daily volatility fallback
_PERP_FUNDING_BPS_PER_HOUR: float = 0.125  # 0.01%/8h = 0.125 bps/h

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CostEstimate:
    fee_bps: float       # exchange fee round-trip (2x one-way)
    spread_bps: float    # round-trip spread (2x half-spread)
    impact_bps: float    # Almgren-Chriss market impact
    slippage_bps: float  # timing slippage
    funding_bps: float   # perp funding cost (0 for spot/equity)
    total_bps: float     # sum of all components
    total_pct: float     # total_bps / 10000

    def to_dollars(self, notional_usd: float) -> float:
        """Dollar cost for a given notional position size."""
        return notional_usd * (self.total_pct / 100.0)


# ---------------------------------------------------------------------------
# Symbol / asset-type helpers
# ---------------------------------------------------------------------------

_BTC_SYMBOLS: frozenset[str] = frozenset({"BTC-USD", "BTC/USD", "BTCUSDT", "XBTUSD"})
_ETH_SYMBOLS: frozenset[str] = frozenset({"ETH-USD", "ETH/USD", "ETHUSDT"})
_CRYPTO_EXCHANGES: frozenset[str] = frozenset({"binance_spot", "binance_perp", "coinbase", "kraken"})


def _asset_type(symbol: str, exchange: str) -> str:
    """Classify a symbol into a HALF_SPREAD_BPS key."""
    sym_upper = symbol.upper()

    if symbol in _BTC_SYMBOLS:
        return "btc"
    if symbol in _ETH_SYMBOLS:
        return "eth"
    if sym_upper.endswith("-PERP") or sym_upper.endswith("-SWAP") or sym_upper.endswith("PERP"):
        return "futures"
    if exchange in _CRYPTO_EXCHANGES:
        return "crypto_large"
    return "equity_large_cap"


# ---------------------------------------------------------------------------
# Core cost function
# ---------------------------------------------------------------------------

def cost_per_trade(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    exchange: str,
    adv_dollar: Optional[float] = None,
    daily_vol: Optional[float] = None,
    order_type: str = "market",
    holding_hours: Optional[float] = None,
) -> CostEstimate:
    """Estimate round-trip cost for a single trade."""

    # -- 1. Fee --
    fee_table = EXCHANGE_FEES.get(exchange, {"maker": 0.0, "taker": 0.0})
    one_way_fee_bps: float = fee_table["taker"] if order_type == "market" else fee_table["maker"]
    fee_bps: float = one_way_fee_bps * 2.0
    if exchange == "alpaca_equity":
        fee_bps += _ALPACA_PFOF_BPS

    # -- 2. Spread --
    atype = _asset_type(symbol, exchange)
    half_spread = HALF_SPREAD_BPS.get(atype, HALF_SPREAD_BPS["default"])
    spread_bps: float = half_spread * 2.0

    # -- 3. Almgren-Chriss market impact --
    vol: float = daily_vol if daily_vol is not None else _DEFAULT_DAILY_VOL
    sigma_bps: float = vol * 10_000.0
    notional: float = qty * price
    if adv_dollar and adv_dollar > 0:
        participation: float = notional / adv_dollar
    else:
        participation = _DEFAULT_ADV_RATIO
    impact_bps: float = sigma_bps * _AC_ETA * math.sqrt(participation)

    # -- 4. Slippage --
    base_slippage_bps: float = 0.5 + (vol * 100.0 * 0.1)
    slippage_bps: float = base_slippage_bps if order_type == "market" else base_slippage_bps / 2.0

    # -- 5. Funding (perps only) --
    funding_bps: float = 0.0
    if exchange == "binance_perp" and holding_hours is not None:
        funding_bps = _PERP_FUNDING_BPS_PER_HOUR * holding_hours

    # -- 6. Total --
    total_bps: float = fee_bps + spread_bps + impact_bps + slippage_bps + funding_bps
    total_pct: float = total_bps / 10_000.0

    return CostEstimate(
        fee_bps=round(fee_bps, 4),
        spread_bps=round(spread_bps, 4),
        impact_bps=round(impact_bps, 4),
        slippage_bps=round(slippage_bps, 4),
        funding_bps=round(funding_bps, 4),
        total_bps=round(total_bps, 4),
        total_pct=round(total_pct, 8),
    )


# ---------------------------------------------------------------------------
# Daily rollup helper
# ---------------------------------------------------------------------------

def estimate_bot_daily_costs(
    trades: list[dict],
    gross_return_pct: float,
) -> dict:
    """
    Sum cost estimates across a list of trades and compare against gross return.

    Each trade dict must have: symbol, side, qty, price, exchange.
    Optional keys: adv_dollar, daily_vol, order_type, holding_hours.
    """
    if not trades:
        return {
            "total_cost_pct": 0.0,
            "net_return_pct": gross_return_pct,
            "cost_drag_pct": 0.0,
            "n_trades": 0,
            "per_trade_avg_bps": 0.0,
        }

    total_cost_bps: float = 0.0

    for trade in trades:
        estimate = cost_per_trade(
            symbol=trade["symbol"],
            side=trade["side"],
            qty=float(trade["qty"]),
            price=float(trade["price"]),
            exchange=trade["exchange"],
            adv_dollar=trade.get("adv_dollar"),
            daily_vol=trade.get("daily_vol"),
            order_type=trade.get("order_type", "market"),
            holding_hours=trade.get("holding_hours"),
        )
        total_cost_bps += estimate.total_bps

    n: int = len(trades)
    per_trade_avg_bps: float = total_cost_bps / n
    total_cost_pct: float = total_cost_bps / 10_000.0
    net_return_pct: float = gross_return_pct - total_cost_pct

    if gross_return_pct != 0.0:
        cost_drag_pct = (gross_return_pct - net_return_pct) / abs(gross_return_pct)
    else:
        cost_drag_pct = 0.0

    return {
        "total_cost_pct": round(total_cost_pct, 8),
        "net_return_pct": round(net_return_pct, 8),
        "cost_drag_pct": round(cost_drag_pct, 6),
        "n_trades": n,
        "per_trade_avg_bps": round(per_trade_avg_bps, 4),
    }


# ---------------------------------------------------------------------------
# Exchange inference helper
# ---------------------------------------------------------------------------

def infer_exchange(bot_name: str, symbol: str) -> str:
    """Heuristic exchange detection from bot name and symbol."""
    bot_lower = bot_name.lower()
    sym_upper = symbol.upper()

    if "perp" in bot_lower:
        return "binance_perp"

    crypto_tokens = ("BTC", "ETH", "USDT", "USDC")
    if any(tok in sym_upper for tok in crypto_tokens) or "crypto" in bot_lower:
        return "binance_spot"

    return "alpaca_equity"
