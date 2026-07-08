"""Factor: Accruals (Sloan 1996, "Do Stock Prices Fully Reflect Information
in Accruals and Cash Flows about Future Earnings?", The Accounting Review).

One of the strongest, most-replicated cross-sectional anomalies. Firms
with high accruals (large gap between reported earnings and actual cash
flow) underperform because the earnings quality is low — the reported
earnings are propped up by non-cash items that reverse over time.

Balance-sheet accruals formula (Sloan's original):
    accruals = (ΔCA - ΔCash) - (ΔCL - ΔSTDebt - ΔTaxPay) - Dep
             / avg_total_assets

Simplified for BMG (yfinance data availability):
    accruals ≈ (net_income - operating_cash_flow) / avg_total_assets

This captures the SAME economic content — the difference between accrual
accounting earnings and cash. High = earnings driven by accruals =
underperform. Low or negative = earnings backed by cash = outperform.

Ranking:
    Score = -accruals   (invert so higher score = LOW accruals = expected outperformer)
    Long top decile     = lowest-accrual names (highest earnings quality)

Reference: Sloan 1996; Richardson-Sloan-Soliman-Tuna 2005 (extension).
Sharpe of long/short quintile spread: 0.8-1.0 documented; long-only top
decile: 0.4-0.5. Complements momentum + quality bots.

Params:
    (none — uses trailing 4 quarters of financials via yfinance)

Data: yfinance ticker.quarterly_financials + quarterly_balance_sheet +
      quarterly_cashflow.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _accruals_score(ticker: str) -> Optional[float]:
    """Return -accruals so higher is better (low accruals = quality earnings).

    None on any data-availability failure.
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:accruals] yfinance import failed: %s", exc)
        return None

    try:
        tk = yf.Ticker(ticker)
        # Quarterly cashflow gives us "Net Income" and "Operating Cash Flow".
        cf = tk.quarterly_cashflow
        bs = tk.quarterly_balance_sheet
        if cf is None or bs is None or cf.empty or bs.empty:
            return None

        # yfinance rows can be labeled differently across tickers. Common names:
        #   "Net Income" or "Net Income Common Stockholders"
        #   "Operating Cash Flow" or "Total Cash From Operating Activities"
        #   "Total Assets"
        def _pick(df, keys):
            for k in keys:
                if k in df.index:
                    return df.loc[k]
            return None

        # yfinance quarterly_cashflow row names vary across tickers. Check
        # in order of most-common first. Verified 2026-07-08 against AAPL:
        # 'Operating Cash Flow' + 'Net Income From Continuing Operations'.
        ni = _pick(cf, [
            "Net Income From Continuing Operations",
            "Net Income",
            "Net Income Common Stockholders",
            "NetIncome",
        ])
        ocf = _pick(cf, [
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "CashFromOperatingActivities",
        ])
        ta = _pick(bs, ["Total Assets", "TotalAssets"])
        if ni is None or ocf is None or ta is None:
            return None
        if len(ni) < 4 or len(ta) < 2:
            return None

        # Trailing 4 quarters of net income + operating cash flow.
        ni_ttm = float(ni.iloc[:4].sum())
        ocf_ttm = float(ocf.iloc[:4].sum())

        # Average total assets over trailing quarters.
        avg_ta = float(ta.iloc[:2].mean())
        if avg_ta <= 0:
            return None

        accruals = (ni_ttm - ocf_ttm) / avg_ta

        # Invert so higher score = lower accruals = expected outperformer.
        return -float(accruals)
    except Exception as exc:
        logger.debug("[factor:accruals] %s compute failed: %s", ticker, exc)
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: -accruals_ratio}. Higher = lower accruals = long."""
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        v = _accruals_score(sym)
        if v is None:
            continue
        scores[sym] = v
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:accruals] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:accruals] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
