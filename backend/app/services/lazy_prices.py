"""Lazy Prices signal — Cohen, Malloy, Nguyen (2020) J of Finance.

Signal: firms that materially REWRITE their 10-K or 10-Q (measured by cosine
similarity vs prior-year same-form filing) underperform firms that keep
boilerplate stable. Effect concentrated in Item 1A (Risk Factors) — 188 bps/month.

Post-publication:
  - Sungmin Hong LazyAlpha 2026 replication (small-cap 2016-2024)
  - Copy-Paste Outperformance (SSRN 3748216, S&P 1500 to 2020)
  - QuantConnect 2026 OOS test: still beats SPY on Sharpe
  - Cambridge JFQA 2026: effect concentrated in optionable stocks (limits-to-arb)

For BMG's confluence framework:
  - INPUT: ticker symbol
  - OUTPUT: similarity score in [0, 1] (1 = identical to prior year; 0 = totally rewritten)
  - INTERPRETATION: low similarity (bottom quintile ≈ <0.6) → RED flag
                    high similarity (top quintile ≈ >0.9) → GREEN

Data source: SEC EDGAR REST API — free, rate-limited to 10 req/sec.
No paid data required.

Cache: results cached per (symbol, form_type) since 10-Ks are annual events.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# SEC EDGAR requires a descriptive User-Agent per their API docs.
_SEC_USER_AGENT = "BMG-Capital confluence-hunter research@bmg.capital"
_SEC_BASE = "https://data.sec.gov"
_SEC_ARCHIVES = "https://www.sec.gov/Archives"

# In-process cache: (cik, form_type) → (similarity, computed_at_ts)
_SIMILARITY_CACHE: Dict[Tuple[str, str], Tuple[float, float]] = {}
_CACHE_TTL_SEC = 24 * 3600  # daily refresh — filings don't change intraday


def _sec_get(url: str, timeout: int = 15) -> Optional[bytes]:
    """GET SEC EDGAR with proper UA + polite delay."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _SEC_USER_AGENT,
            "Accept": "*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        time.sleep(0.15)  # 10 req/sec limit, be conservative
        return body
    except urllib.error.HTTPError as e:
        logger.warning("[lazy_prices] SEC HTTPError %d for %s", e.code, url)
        return None
    except Exception as e:
        logger.warning("[lazy_prices] SEC fetch failed for %s: %s", url, e)
        return None


def _symbol_to_cik(symbol: str) -> Optional[str]:
    """Map ticker → 10-digit zero-padded CIK via SEC's ticker.txt."""
    body = _sec_get("https://www.sec.gov/files/company_tickers.json")
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    symbol = symbol.upper()
    for row in data.values():
        if isinstance(row, dict) and row.get("ticker", "").upper() == symbol:
            return str(row.get("cik_str", "")).zfill(10)
    return None


def _list_filings(cik: str, form_type: str, count: int = 5) -> List[Dict[str, Any]]:
    """Fetch the most recent `count` filings of given form_type for a CIK.
    Returns list of dicts with accession_number, filing_date, primary_document."""
    body = _sec_get(f"{_SEC_BASE}/submissions/CIK{cik}.json")
    if not body:
        return []
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return []
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    out: List[Dict[str, Any]] = []
    for i, form in enumerate(forms):
        if form != form_type:
            continue
        out.append({
            "accession_number": accessions[i] if i < len(accessions) else "",
            "filing_date": dates[i] if i < len(dates) else "",
            "primary_document": docs[i] if i < len(docs) else "",
        })
        if len(out) >= count:
            break
    return out


def _fetch_filing_document(cik: str, accession_number: str, primary_document: str) -> Optional[str]:
    """Fetch the primary document (typically 10-K HTML) for a filing."""
    accession_clean = accession_number.replace("-", "")
    url = f"{_SEC_ARCHIVES}/edgar/data/{int(cik)}/{accession_clean}/{primary_document}"
    body = _sec_get(url, timeout=30)
    if not body:
        return None
    try:
        return body.decode("utf-8", errors="ignore")
    except Exception:
        return None


# Item 1A (Risk Factors) parser — the section where 188bps/mo effect lives per Cohen/Malloy/Nguyen 2020.
_ITEM_1A_START_PATTERNS = [
    r"item\s*1a[\s\.\-:]*risk\s*factors",
    r"item\s*1a[\s\.\-:]+risk",
]
_ITEM_1A_END_PATTERNS = [
    r"item\s*1b[\s\.\-:]",
    r"item\s*2[\s\.\-:]+properties",
    r"item\s*3[\s\.\-:]+legal",
    r"unresolved\s+staff\s+comments",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_MULTI_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Very lightweight HTML-to-text — good enough for cosine similarity."""
    # Remove script/style blocks entirely
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining tags
    text = _HTML_TAG_RE.sub(" ", text)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
    # Collapse whitespace
    text = _MULTI_WS_RE.sub(" ", text)
    return text.strip()


def _extract_item_1a(document_text: str) -> Optional[str]:
    """Extract Item 1A (Risk Factors) section from a 10-K text. Returns lowercased,
    whitespace-collapsed text or None if section not clearly identifiable."""
    text_lower = document_text.lower()
    # Find earliest Item 1A occurrence
    start_idx = -1
    for pat in _ITEM_1A_START_PATTERNS:
        for m in re.finditer(pat, text_lower):
            # Skip if this is the table-of-contents mention (usually followed by page number)
            snippet = text_lower[m.start():m.start() + 200]
            if re.search(r"\d+\s*item", snippet[10:100]):
                continue  # likely TOC entry
            start_idx = m.end()
            break
        if start_idx > 0:
            break
    if start_idx < 0:
        return None

    # Find earliest end pattern AFTER the start
    end_idx = len(text_lower)
    for pat in _ITEM_1A_END_PATTERNS:
        for m in re.finditer(pat, text_lower[start_idx:]):
            candidate_end = start_idx + m.start()
            if candidate_end < end_idx and candidate_end > start_idx + 500:
                end_idx = candidate_end
                break

    section = document_text[start_idx:end_idx].strip()
    if len(section) < 500:
        return None  # too short to be a real Item 1A
    return _MULTI_WS_RE.sub(" ", section.lower()).strip()


def _cosine_similarity_token(a: str, b: str) -> float:
    """Token-frequency cosine similarity. Simple pure-Python impl to avoid
    dragging scikit-learn into the request path."""
    from collections import Counter
    from math import sqrt

    def _tokenize(s: str) -> List[str]:
        return re.findall(r"[a-z]{2,}", s)

    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    ca = Counter(ta)
    cb = Counter(tb)
    # Dot product
    common = set(ca.keys()) & set(cb.keys())
    dot = sum(ca[t] * cb[t] for t in common)
    na = sqrt(sum(v * v for v in ca.values()))
    nb = sqrt(sum(v * v for v in cb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def compute_lazy_prices_score(symbol: str, form_type: str = "10-K", use_cache: bool = True) -> Dict[str, Any]:
    """Compute Lazy Prices similarity for one symbol.

    Returns dict:
      symbol, form_type, similarity, current_filing_date, prior_filing_date,
      similarity_bucket (RED|YELLOW|GREEN), section (item_1a|full_doc),
      cached: bool.

    RED = bottom quintile of typical distribution (<0.60) — heavy rewriter
    YELLOW = 0.60-0.85
    GREEN = >0.85 — stable boilerplate

    Score < 0 in similarity field indicates failure to compute (parse error, missing filings).
    """
    symbol = symbol.upper().strip()
    now = time.time()
    cache_key = (symbol, form_type)
    if use_cache and cache_key in _SIMILARITY_CACHE:
        val, ts = _SIMILARITY_CACHE[cache_key]
        if now - ts < _CACHE_TTL_SEC:
            return {
                "symbol": symbol,
                "form_type": form_type,
                "similarity": val,
                "similarity_bucket": _bucket(val),
                "cached": True,
            }

    cik = _symbol_to_cik(symbol)
    if not cik:
        return {"symbol": symbol, "form_type": form_type, "similarity": -1.0, "error": "cik_not_found", "cached": False}

    filings = _list_filings(cik, form_type, count=3)
    if len(filings) < 2:
        return {
            "symbol": symbol,
            "form_type": form_type,
            "similarity": -1.0,
            "error": f"need 2 filings, found {len(filings)}",
            "cached": False,
        }

    current = filings[0]
    prior = filings[1]

    cur_doc = _fetch_filing_document(cik, current["accession_number"], current["primary_document"])
    pri_doc = _fetch_filing_document(cik, prior["accession_number"], prior["primary_document"])
    if not cur_doc or not pri_doc:
        return {
            "symbol": symbol,
            "form_type": form_type,
            "similarity": -1.0,
            "error": "document_fetch_failed",
            "cached": False,
        }

    cur_text = _strip_html(cur_doc)
    pri_text = _strip_html(pri_doc)

    # Try Item 1A first (higher-alpha section per paper)
    cur_1a = _extract_item_1a(cur_text)
    pri_1a = _extract_item_1a(pri_text)
    section = "item_1a"
    if cur_1a and pri_1a:
        similarity = _cosine_similarity_token(cur_1a, pri_1a)
    else:
        # Fallback: full-doc similarity (5%/yr effect vs 22%/yr on Item 1A alone)
        section = "full_doc_fallback"
        similarity = _cosine_similarity_token(cur_text.lower(), pri_text.lower())

    _SIMILARITY_CACHE[cache_key] = (similarity, now)

    return {
        "symbol": symbol,
        "form_type": form_type,
        "similarity": round(similarity, 4),
        "similarity_bucket": _bucket(similarity),
        "section": section,
        "current_filing_date": current.get("filing_date"),
        "prior_filing_date": prior.get("filing_date"),
        "cached": False,
    }


def _bucket(similarity: float) -> str:
    """Map similarity to RED/YELLOW/GREEN per typical distribution.
    Thresholds from Cohen/Malloy/Nguyen 2020 empirical quintiles."""
    if similarity < 0:
        return "ERROR"
    if similarity < 0.60:
        return "RED"  # bottom quintile — heavy rewriter, underperformance signal
    if similarity < 0.85:
        return "YELLOW"
    return "GREEN"


def batch_compute_lazy_prices(symbols: List[str], form_type: str = "10-K") -> List[Dict[str, Any]]:
    """Compute Lazy Prices for a list of symbols. Sequential (respects SEC rate limit)."""
    return [compute_lazy_prices_score(s, form_type=form_type) for s in symbols]
