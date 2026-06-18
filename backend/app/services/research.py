from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Yahoo Finance requires a session cookie (A3) + crumb for its v10 API.
# Plain requests handles this fine — no curl_cffi or browser impersonation needed.
_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _yahoo_session_and_crumb() -> tuple[requests.Session, str]:
    session = requests.Session()
    session.headers.update(_YF_HEADERS)
    try:
        session.get("https://fc.yahoo.com/", timeout=8)
    except Exception:
        pass
    r = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=8)
    r.raise_for_status()
    crumb = r.text.strip()
    if not crumb:
        raise ValueError("Empty crumb from Yahoo Finance")
    return session, crumb


def _g(d: dict, key: str):
    """Get a value from a Yahoo Finance module dict, unwrapping {raw, fmt} if needed."""
    v = d.get(key)
    if isinstance(v, dict) and "raw" in v:
        return v["raw"]
    if v in (None, "N/A", "", "None"):
        return None
    return v


def _safe_get(info: dict, key: str, default=None):
    val = info.get(key)
    if val in (None, "N/A", ""):
        return default
    return val


def _fetch_all_modules(symbol: str) -> tuple[dict, list]:
    """
    Fetch Yahoo Finance quoteSummary and return (flat_info_dict, quarterly_list).
    Uses cookie+crumb auth via plain requests — works on Railway / any cloud host.
    """
    session, crumb = _yahoo_session_and_crumb()

    modules = ",".join([
        "price",
        "summaryDetail",
        "financialData",
        "defaultKeyStatistics",
        "assetProfile",
        "incomeStatementHistoryQuarterly",
    ])
    resp = session.get(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
        f"?modules={modules}&crumb={crumb}&formatted=false",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    qs = data.get("quoteSummary", {})
    if qs.get("error"):
        raise ValueError(f"Yahoo Finance error for {symbol}: {qs['error']}")
    result = qs.get("result") or []
    if not result:
        raise ValueError(f"No data returned by Yahoo Finance for {symbol}")

    def _mod(name: str) -> dict:
        for r in result:
            if name in r:
                return r[name]
        return {}

    price   = _mod("price")
    sd      = _mod("summaryDetail")
    fd      = _mod("financialData")
    ks      = _mod("defaultKeyStatistics")
    profile = _mod("assetProfile")

    info = {
        "longName":                     _g(price, "longName") or _g(profile, "longName"),
        "shortName":                    _g(price, "shortName"),
        "sector":                       _g(profile, "sector"),
        "industry":                     _g(profile, "industry"),
        "longBusinessSummary":          _g(profile, "longBusinessSummary"),
        "country":                      _g(profile, "country"),
        "fullTimeEmployees":            _g(profile, "fullTimeEmployees"),
        "website":                      _g(profile, "website"),
        "marketCap":                    _g(price, "marketCap"),
        "enterpriseValue":              _g(ks, "enterpriseValue"),
        "trailingPE":                   _g(sd, "trailingPE"),
        "forwardPE":                    _g(sd, "forwardPE"),
        "pegRatio":                     _g(ks, "pegRatio"),
        "priceToBook":                  _g(ks, "priceToBook"),
        "priceToSalesTrailing12Months": _g(sd, "priceToSalesTrailing12Months"),
        "trailingEps":                  _g(ks, "trailingEps"),
        "forwardEps":                   _g(ks, "forwardEps"),
        "dividendYield":                _g(sd, "dividendYield"),
        "dividendRate":                 _g(sd, "dividendRate"),
        "payoutRatio":                  _g(sd, "payoutRatio"),
        "exDividendDate":               _g(sd, "exDividendDate"),
        "beta":                         _g(sd, "beta"),
        "fiftyTwoWeekHigh":             _g(sd, "fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow":              _g(sd, "fiftyTwoWeekLow"),
        "dayHigh":                      _g(price, "regularMarketDayHigh"),
        "dayLow":                       _g(price, "regularMarketDayLow"),
        "currentPrice":                 _g(price, "regularMarketPrice"),
        "regularMarketPrice":           _g(price, "regularMarketPrice"),
        "previousClose":                _g(price, "regularMarketPreviousClose"),
        "open":                         _g(price, "regularMarketOpen"),
        "volume":                       _g(price, "regularMarketVolume"),
        "averageVolume":                _g(sd, "averageVolume"),
        "averageVolume10days":          _g(sd, "averageVolume10days"),
        "totalRevenue":                 _g(fd, "totalRevenue"),
        "grossProfits":                 _g(fd, "grossProfits"),
        "netIncomeToCommon":            _g(ks, "netIncomeToCommon"),
        "ebitda":                       _g(fd, "ebitda"),
        "profitMargins":                _g(fd, "profitMargins"),
        "operatingMargins":             _g(fd, "operatingMargins"),
        "grossMargins":                 _g(fd, "grossMargins"),
        "returnOnEquity":               _g(fd, "returnOnEquity"),
        "returnOnAssets":               _g(fd, "returnOnAssets"),
        "debtToEquity":                 _g(fd, "debtToEquity"),
        "currentRatio":                 _g(fd, "currentRatio"),
        "quickRatio":                   _g(fd, "quickRatio"),
        "freeCashflow":                 _g(fd, "freeCashflow"),
        "operatingCashflow":            _g(fd, "operatingCashflow"),
        "totalCash":                    _g(fd, "totalCash"),
        "totalDebt":                    _g(fd, "totalDebt"),
        "shortRatio":                   _g(ks, "shortRatio"),
        "shortPercentOfFloat":          _g(ks, "shortPercentOfFloat"),
        "targetMeanPrice":              _g(fd, "targetMeanPrice"),
        "targetLowPrice":               _g(fd, "targetLowPrice"),
        "targetHighPrice":              _g(fd, "targetHighPrice"),
        "recommendationKey":            _g(fd, "recommendationKey"),
        "numberOfAnalystOpinions":      _g(fd, "numberOfAnalystOpinions"),
        "recommendationMean":           _g(fd, "recommendationMean"),
        "revenueGrowth":                _g(fd, "revenueGrowth"),
    }

    if not info.get("currentPrice") and not info.get("regularMarketPrice"):
        raise ValueError(f"Yahoo Finance returned empty price data for {symbol}")

    # Quarterly financials from incomeStatementHistoryQuarterly
    quarterly = _extract_quarterly_from_module(_mod("incomeStatementHistoryQuarterly"))

    return info, quarterly


def _extract_quarterly_from_module(mod: dict) -> Optional[List[Dict[str, Any]]]:
    """Parse incomeStatementHistoryQuarterly module into our standard quarterly list."""
    try:
        history = mod.get("incomeStatementHistory") or []
        if not history:
            return None
        quarters = []
        for entry in history[:4]:
            end_ts = _g(entry, "endDate")
            if end_ts:
                try:
                    period = datetime.fromtimestamp(end_ts).strftime("%b %Y")
                except Exception:
                    period = str(end_ts)
            else:
                period = "Unknown"

            def _val(k):
                v = _g(entry, k)
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            quarters.append({
                "period":           period,
                "revenue":          _val("totalRevenue"),
                "gross_profit":     _val("grossProfit"),
                "operating_income": _val("operatingIncome"),
                "net_income":       _val("netIncome"),
                "eps":              _val("basicEps"),
            })
        return quarters if quarters else None
    except Exception as e:
        logger.warning("[research] quarterly parse failed: %s", e)
        return None


def compute_bmg_score(info: dict) -> dict:
    """Compute a 1-10 BMG composite quality/momentum score."""

    def safe(key, default=None):
        val = info.get(key)
        if val in (None, "N/A", ""):
            return default
        return val

    components: dict = {}

    forward_pe = safe("forwardPE")
    if forward_pe is not None and forward_pe > 0:
        components["value"] = 2 if forward_pe < 15 else (1 if forward_pe <= 25 else 0)
    else:
        components["value"] = 0

    revenue_growth = safe("revenueGrowth")
    if revenue_growth is not None:
        components["growth"] = 2 if revenue_growth > 0.15 else (1 if revenue_growth >= 0.05 else 0)
    else:
        components["growth"] = 0

    profit_margins = safe("profitMargins")
    if profit_margins is not None:
        components["profitability"] = 2 if profit_margins > 0.15 else (1 if profit_margins >= 0.05 else 0)
    else:
        components["profitability"] = 0

    current_price = safe("currentPrice") or safe("regularMarketPrice")
    high_52 = safe("fiftyTwoWeekHigh")
    low_52 = safe("fiftyTwoWeekLow")
    if current_price and high_52 and low_52:
        price_range = high_52 - low_52
        if price_range > 0:
            position = (current_price - low_52) / price_range
            components["momentum"] = 2 if position > 0.7 else (1 if position >= 0.4 else 0)
        else:
            components["momentum"] = 0
    else:
        components["momentum"] = 0

    rec_mean = safe("recommendationMean")
    if rec_mean is not None:
        components["analyst"] = 2 if rec_mean <= 2.0 else (1 if rec_mean <= 2.5 else 0)
    else:
        components["analyst"] = 1

    score = float(sum(components.values()))
    grade = "A" if score >= 8 else ("B" if score >= 6 else ("C" if score >= 4 else ("D" if score >= 2 else "F")))
    return {"score": score, "grade": grade, "components": components}


async def get_fundamentals(symbol: str) -> Dict[str, Any]:
    """Fetch company fundamentals via Yahoo Finance cookie+crumb API (no curl_cffi)."""
    def _fetch() -> dict:
        info, quarterly = _fetch_all_modules(symbol)
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
        logger.error("[research] fetch error for %s: %s", symbol, e, exc_info=True)
        return {"symbol": symbol.upper(), "error": str(e)}
