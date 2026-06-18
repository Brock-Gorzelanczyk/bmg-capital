from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import requests
import yfinance as yf
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)

# Cloud environments (Railway, Render, Fly, etc.) get rate-limited or blocked by
# Yahoo Finance when using the default urllib session. A browser-like User-Agent
# with a retry-enabled session resolves the vast majority of cloud fetch failures.
def _yf_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    })
    return session


def compute_bmg_score(info: dict) -> dict:
    """Compute a 1-10 BMG composite quality/momentum score from yfinance info dict."""

    def safe(key, default=None):
        val = info.get(key)
        if val in (None, "N/A", ""):
            return default
        return val

    components: dict = {}

    # 1. Value (0-2): based on forwardPE
    forward_pe = safe("forwardPE")
    if forward_pe is not None and forward_pe > 0:
        if forward_pe < 15:
            components["value"] = 2
        elif forward_pe <= 25:
            components["value"] = 1
        else:
            components["value"] = 0
    else:
        components["value"] = 0

    # 2. Growth (0-2): based on revenueGrowth
    revenue_growth = safe("revenueGrowth")
    if revenue_growth is not None:
        if revenue_growth > 0.15:
            components["growth"] = 2
        elif revenue_growth >= 0.05:
            components["growth"] = 1
        else:
            components["growth"] = 0
    else:
        components["growth"] = 0

    # 3. Profitability (0-2): based on profitMargins
    profit_margins = safe("profitMargins")
    if profit_margins is not None:
        if profit_margins > 0.15:
            components["profitability"] = 2
        elif profit_margins >= 0.05:
            components["profitability"] = 1
        else:
            components["profitability"] = 0
    else:
        components["profitability"] = 0

    # 4. Momentum (0-2): price position within 52-week range
    current_price = safe("currentPrice") or safe("regularMarketPrice")
    high_52 = safe("fiftyTwoWeekHigh")
    low_52 = safe("fiftyTwoWeekLow")
    if current_price is not None and high_52 is not None and low_52 is not None:
        price_range = high_52 - low_52
        if price_range > 0:
            position = (current_price - low_52) / price_range
            if position > 0.7:
                components["momentum"] = 2
            elif position >= 0.4:
                components["momentum"] = 1
            else:
                components["momentum"] = 0
        else:
            components["momentum"] = 0
    else:
        components["momentum"] = 0

    # 5. Analyst Consensus (0-2): based on recommendationMean (1=Strong Buy … 5=Strong Sell)
    rec_mean = safe("recommendationMean")
    if rec_mean is not None:
        if rec_mean <= 2.0:
            components["analyst"] = 2
        elif rec_mean <= 2.5:
            components["analyst"] = 1
        else:
            components["analyst"] = 0
    else:
        components["analyst"] = 1  # neutral default when missing

    score = float(sum(components.values()))

    if score >= 8:
        grade = "A"
    elif score >= 6:
        grade = "B"
    elif score >= 4:
        grade = "C"
    elif score >= 2:
        grade = "D"
    else:
        grade = "F"

    return {"score": score, "grade": grade, "components": components}


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
        ticker = yf.Ticker(symbol, session=_yf_session())
        info = ticker.info
        # yfinance returns a single-key sparse dict when Yahoo blocks the request
        if len(info) < 5:
            raise ValueError(f"Yahoo Finance returned no data for {symbol} — possibly rate-limited or invalid ticker")
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
            "bmg_score": compute_bmg_score(info),
        }

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"Research fetch error for {symbol}: {e}", exc_info=True)
        return {"symbol": symbol.upper(), "error": str(e)}
