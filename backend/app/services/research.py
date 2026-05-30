from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_get(info: dict, key: str, default=None):
    val = info.get(key)
    if val in (None, "N/A", ""):
        return default
    return val


def _extract_quarterly_financials(ticker: yf.Ticker) -> Optional[List[Dict[str, Any]]]:
    """Extract last 4 quarters of income-statement data from yfinance."""
    try:
        df = ticker.quarterly_financials
        if df is None or df.empty:
            return None

        # Rows we care about — yfinance uses these exact index labels
        row_map = {
            "Total Revenue": "revenue",
            "Gross Profit": "gross_profit",
            "Operating Income": "operating_income",
            "Net Income": "net_income",
            "Basic EPS": "eps",
        }

        # Take the four most-recent columns (columns are sorted newest-first)
        cols = list(df.columns[:4])
        quarters: List[Dict[str, Any]] = []
        for col in cols:
            period_label = col.strftime("%b %Y") if hasattr(col, "strftime") else str(col)
            entry: Dict[str, Any] = {"period": period_label}
            for yf_label, our_key in row_map.items():
                if yf_label in df.index:
                    raw = df.loc[yf_label, col]
                    try:
                        entry[our_key] = float(raw) if raw is not None else None
                    except (TypeError, ValueError):
                        entry[our_key] = None
                else:
                    entry[our_key] = None
            quarters.append(entry)
        return quarters if quarters else None
    except Exception as e:
        logger.warning(f"Could not fetch quarterly financials: {e}")
        return None


async def get_fundamentals(symbol: str) -> Dict[str, Any]:
    """Fetch company fundamentals from yfinance."""
    def _fetch() -> dict:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        quarterly = _extract_quarterly_financials(ticker)
        return {
            "symbol": symbol.upper(),
            "name": _safe_get(info, "longName") or _safe_get(info, "shortName") or symbol,
            "sector": _safe_get(info, "sector"),
            "industry": _safe_get(info, "industry"),
            "description": _safe_get(info, "longBusinessSummary"),
            "country": _safe_get(info, "country"),
            "employees": _safe_get(info, "fullTimeEmployees"),
            "website": _safe_get(info, "website"),
            "market_cap": _safe_get(info, "marketCap"),
            "enterprise_value": _safe_get(info, "enterpriseValue"),
            "pe_ratio": _safe_get(info, "trailingPE"),
            "forward_pe": _safe_get(info, "forwardPE"),
            "peg_ratio": _safe_get(info, "pegRatio"),
            "price_to_book": _safe_get(info, "priceToBook"),
            "price_to_sales": _safe_get(info, "priceToSalesTrailing12Months"),
            "eps": _safe_get(info, "trailingEps"),
            "forward_eps": _safe_get(info, "forwardEps"),
            "dividend_yield": _safe_get(info, "dividendYield"),
            "dividend_rate": _safe_get(info, "dividendRate"),
            "payout_ratio": _safe_get(info, "payoutRatio"),
            "ex_dividend_date": _safe_get(info, "exDividendDate"),
            "beta": _safe_get(info, "beta"),
            "week_52_high": _safe_get(info, "fiftyTwoWeekHigh"),
            "week_52_low": _safe_get(info, "fiftyTwoWeekLow"),
            "day_high": _safe_get(info, "dayHigh"),
            "day_low": _safe_get(info, "dayLow"),
            "current_price": _safe_get(info, "currentPrice") or _safe_get(info, "regularMarketPrice"),
            "previous_close": _safe_get(info, "previousClose"),
            "open_price": _safe_get(info, "open"),
            "volume": _safe_get(info, "volume"),
            "avg_volume": _safe_get(info, "averageVolume"),
            "avg_volume_10d": _safe_get(info, "averageVolume10days"),
            "revenue": _safe_get(info, "totalRevenue"),
            "gross_profit": _safe_get(info, "grossProfits"),
            "net_income": _safe_get(info, "netIncomeToCommon"),
            "ebitda": _safe_get(info, "ebitda"),
            "profit_margins": _safe_get(info, "profitMargins"),
            "operating_margins": _safe_get(info, "operatingMargins"),
            "gross_margins": _safe_get(info, "grossMargins"),
            "return_on_equity": _safe_get(info, "returnOnEquity"),
            "return_on_assets": _safe_get(info, "returnOnAssets"),
            "debt_to_equity": _safe_get(info, "debtToEquity"),
            "current_ratio": _safe_get(info, "currentRatio"),
            "quick_ratio": _safe_get(info, "quickRatio"),
            "free_cashflow": _safe_get(info, "freeCashflow"),
            "operating_cashflow": _safe_get(info, "operatingCashflow"),
            "total_cash": _safe_get(info, "totalCash"),
            "total_debt": _safe_get(info, "totalDebt"),
            "short_ratio": _safe_get(info, "shortRatio"),
            "short_percent": _safe_get(info, "shortPercentOfFloat"),
            "analyst_target": _safe_get(info, "targetMeanPrice"),
            "analyst_low": _safe_get(info, "targetLowPrice"),
            "analyst_high": _safe_get(info, "targetHighPrice"),
            "recommendation": _safe_get(info, "recommendationKey"),
            "num_analysts": _safe_get(info, "numberOfAnalystOpinions"),
            "financials": {"quarterly": quarterly} if quarterly else None,
        }

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"Research fetch error for {symbol}: {e}", exc_info=True)
        return {"symbol": symbol.upper(), "error": str(e)}
