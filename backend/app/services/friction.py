"""
Paper-trade friction modeling: slippage + commission per asset_class.

V1 model (per Brock's spec for COMMIT 12):

  Stocks   slippage 3 bps  · commission $0.005/share, min $1.00 per trade
  Crypto   slippage 15 bps · taker fee 10 bps
  Options  slippage 5 bps  · commission $0.65 per contract

Applied at trade-write time in runner._execute_signal (and the options
branch). Written to bot_trade.fees_cents — the existing column — so no
schema migration is required. Sharpe + realized P&L computations that
already subtract fees_cents automatically reflect the friction.

Historical backfill of existing rows is a separate task (track in backlog).
This commit only models prospective trades.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Basis-points slippage applied as a discount to the fill price.
# Slippage cents = entry_price_cents × qty × slippage_bps / 10_000
_SLIPPAGE_BPS = {
    "stock":   3,
    "crypto":  15,
    "options": 5,
    "quant":   15,    # quant bots typically trade crypto microstructure
}

# Commission models — closure returns commission in cents given (qty, fill_price_dollars, contract_count)
def _commission_stocks(qty: float, fill_price_dollars: float, contracts: float = 0) -> int:
    """$0.005/share, min $1.00 per trade. fill_price unused for stocks."""
    raw = qty * 0.005
    return int(round(max(1.00, raw) * 100))


def _commission_crypto(qty: float, fill_price_dollars: float, contracts: float = 0) -> int:
    """10 bps taker on notional."""
    notional = qty * fill_price_dollars
    return int(round(notional * 0.001 * 100))


def _commission_options(qty: float, fill_price_dollars: float, contracts: float = 0) -> int:
    """$0.65 per contract. contracts arg required; falls back to qty."""
    c = float(contracts or qty or 1)
    return int(round(c * 0.65 * 100))


_COMMISSION_FNS = {
    "stock":   _commission_stocks,
    "crypto":  _commission_crypto,
    "options": _commission_options,
    "quant":   _commission_crypto,
}


def model_friction_cents(
    asset_class: str,
    qty: float,
    fill_price_dollars: float,
    contracts: float = 0,
) -> int:
    """Return total friction (slippage + commission) in cents for a single trade leg.

    Defaults to the stocks model if asset_class is unrecognized. Never raises —
    returns 0 on bad inputs so trade-write never fails because of friction math.
    """
    try:
        if qty <= 0 or fill_price_dollars <= 0:
            return 0
        ac = (asset_class or "stock").lower()
        slippage_bps = _SLIPPAGE_BPS.get(ac, _SLIPPAGE_BPS["stock"])
        notional_cents = qty * fill_price_dollars * 100
        slippage_cents = int(round(notional_cents * slippage_bps / 10_000))
        commission_fn = _COMMISSION_FNS.get(ac, _commission_stocks)
        commission_cents = commission_fn(qty, fill_price_dollars, contracts)
        return max(0, slippage_cents + commission_cents)
    except Exception as exc:
        logger.warning("[friction] model failed (ac=%s qty=%s px=%s): %s",
                       asset_class, qty, fill_price_dollars, exc)
        return 0


def slippage_bps_for(asset_class: str) -> int:
    return _SLIPPAGE_BPS.get((asset_class or "stock").lower(), 3)
