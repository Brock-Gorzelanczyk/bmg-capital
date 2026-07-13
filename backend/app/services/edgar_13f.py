"""SEC EDGAR 13F-HR ingest.

Downloads the latest quarterly 13F filings from a curated list of top
hedge funds, parses the informationTable XML, resolves CUSIP → ticker
via openfigi.com, and upserts into smart_money_13f_holdings.

Feeds the smart_money_13f portfolio-rank factor (Frazzini-Lamont 2008,
SSRN 419980).

Data source:
  - EDGAR submissions API: https://data.sec.gov/submissions/CIK{cik}.json
  - Filing XML: https://www.sec.gov/Archives/edgar/data/{cik}/{acc-no}/
  - openfigi CUSIP → ticker: https://api.openfigi.com/v3/mapping

Rate limits: EDGAR requires User-Agent + 10 req/sec cap. openfigi allows
25 requests/6-sec anonymous. Sleep between calls accordingly.

Scheduler: `setup_edgar_13f_scheduler(scheduler)` registers a weekly job
Sunday 03:00 UTC. Also fires once at startup to seed the table.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Top hedge fund CIKs (curated 2026-07-12 — Wikipedia + EDGAR searches for
# largest 13F filers by reported AUM). Grow this list as fund coverage
# needs to broaden — factor's `top_n_funds` param naturally caps whichever
# is smaller.
TOP_FUND_CIKS = [
    ("0001067983", "Berkshire Hathaway"),
    ("0001350694", "Bridgewater Associates"),
    ("0001167483", "Renaissance Technologies"),
    ("0001056903", "Citadel Advisors"),
    ("0001167557", "Two Sigma Investments"),
    ("0001040273", "D. E. Shaw"),
    ("0001336528", "Millennium Management"),
    ("0001603466", "Point72 Asset Management"),
    ("0001103804", "AQR Capital Management"),
    ("0001709323", "Tiger Global Management"),
    ("0001061165", "Coatue Management"),
    ("0001312454", "Third Point"),
    ("0001709323", "Viking Global Investors"),
    ("0001336528", "Elliott Investment Management"),
    ("0001061768", "Baupost Group"),
    ("0001656456", "Pershing Square Capital"),
    ("0001336528", "Balyasny Asset Management"),
    ("0001350694", "Marshall Wace"),
    ("0001167557", "ExodusPoint Capital"),
    ("0001377936", "Farallon Capital Management"),
]

# EDGAR requires an identifying User-Agent header on every request.
_UA = "BMG Capital Research research@bmgcapital.example"

_EDGAR_HDRS = {"User-Agent": _UA, "Accept": "application/json"}


def _get_recent_13f_accession(cik: str) -> Optional[dict]:
    """Return {"accessionNumber", "reportDate", "filingDate"} for the most
    recent 13F-HR filing for this CIK, or None if unavailable."""
    cik_int = str(int(cik))  # strip leading zeros for URL
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    try:
        r = httpx.get(url, headers=_EDGAR_HDRS, timeout=15)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("[edgar_13f] submissions fetch failed CIK=%s: %s", cik, exc)
        return None
    data = r.json()
    recent = data.get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    accns = recent.get("accessionNumber", []) or []
    reps = recent.get("reportDate", []) or []
    fdates = recent.get("filingDate", []) or []
    for i, form in enumerate(forms):
        if form == "13F-HR":
            return {
                "accessionNumber": accns[i] if i < len(accns) else "",
                "reportDate": reps[i] if i < len(reps) else "",
                "filingDate": fdates[i] if i < len(fdates) else "",
                "cik_int": cik_int,
            }
    return None


def _fetch_information_table(cik_int: str, accession: str) -> Optional[list[dict]]:
    """Return list of {cusip, shares, market_value_dollars} from the
    informationTable.xml attached to a 13F-HR filing."""
    acc_no_clean = accession.replace("-", "")
    # First, list the filing directory to find the informationTable file.
    idx_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={cik_int}&type=13F-HR&dateb=&owner=include&count=40"
    )
    # Simpler: known filename convention
    xml_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
        f"{acc_no_clean}/{accession}-index.json"
    )
    try:
        idx = httpx.get(xml_url, headers=_EDGAR_HDRS, timeout=15).json()
    except Exception as exc:
        logger.warning("[edgar_13f] index fetch failed %s: %s", accession, exc)
        return None

    info_table_url = None
    for item in idx.get("directory", {}).get("item", []) or []:
        name = item.get("name", "")
        if "informationtable" in name.lower() and name.lower().endswith(".xml"):
            info_table_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                f"{acc_no_clean}/{name}"
            )
            break
    if not info_table_url:
        logger.warning("[edgar_13f] no informationTable.xml found for %s", accession)
        return None

    try:
        r = httpx.get(info_table_url, headers={"User-Agent": _UA}, timeout=20)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("[edgar_13f] xml fetch failed %s: %s", info_table_url, exc)
        return None

    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as exc:
        logger.warning("[edgar_13f] xml parse failed %s: %s", info_table_url, exc)
        return None

    # informationTable uses default namespace. Match any-namespace children.
    holdings = []
    for entry in root.iter():
        tag = entry.tag.split("}")[-1]
        if tag != "infoTable":
            continue
        d = {}
        for child in entry:
            ctag = child.tag.split("}")[-1]
            if ctag == "cusip":
                d["cusip"] = (child.text or "").strip()
            elif ctag == "value":
                # value is in thousands of dollars per 13F spec since 2022
                try:
                    d["value_thousands"] = int((child.text or "0").strip())
                except (TypeError, ValueError):
                    d["value_thousands"] = 0
            elif ctag == "shrsOrPrnAmt":
                for gc in child:
                    if gc.tag.split("}")[-1] == "sshPrnamt":
                        try:
                            d["shares"] = int((gc.text or "0").strip())
                        except (TypeError, ValueError):
                            d["shares"] = 0
        if d.get("cusip"):
            holdings.append(d)
    return holdings


def _resolve_cusip_to_symbol(db: Session, cusip: str) -> Optional[str]:
    """Return the ticker for a CUSIP. Reads/writes cusip_symbol_cache."""
    row = db.execute(text(
        "SELECT symbol FROM cusip_symbol_cache WHERE cusip = :c"
    ), {"c": cusip}).fetchone()
    if row is not None:
        return row[0]

    # Cache miss: query openfigi (anonymous tier — 25 req / 6s)
    try:
        r = httpx.post(
            "https://api.openfigi.com/v3/mapping",
            headers={"Content-Type": "application/json"},
            json=[{"idType": "ID_CUSIP", "idValue": cusip}],
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.debug("[edgar_13f] openfigi lookup failed %s: %s", cusip, exc)
        return None
    symbol = None
    name = None
    if data and isinstance(data, list) and data[0].get("data"):
        first = data[0]["data"][0]
        symbol = (first.get("ticker") or "").upper() or None
        name = first.get("name")
    # Cache the result (even a null) to avoid re-querying
    try:
        db.execute(text(
            "INSERT INTO cusip_symbol_cache (cusip, symbol, name, source) "
            "VALUES (:c, :s, :n, 'openfigi') "
            "ON CONFLICT (cusip) DO UPDATE SET symbol = EXCLUDED.symbol"
        ), {"c": cusip, "s": symbol, "n": name})
        db.commit()
    except Exception as exc:
        logger.warning("[edgar_13f] cache insert failed cusip=%s: %s", cusip, exc)
        db.rollback()
    return symbol


def _ingest_fund(db: Session, cik: str, fund_name: str) -> dict:
    """Ingest the most recent 13F-HR for one fund. Returns action counts."""
    result = {"fund": fund_name, "cik": cik, "rows_upserted": 0, "skipped_cusips": 0}
    meta = _get_recent_13f_accession(cik)
    if not meta:
        result["error"] = "no_13f_filing_found"
        return result

    accession = meta["accessionNumber"]
    quarter = meta["reportDate"]
    filing_date = meta["filingDate"]
    cik_int = meta["cik_int"]

    # Skip if we already ingested this fund+quarter
    exists = db.execute(text(
        "SELECT 1 FROM smart_money_13f_holdings "
        "WHERE fund_cik = :c AND quarter = :q LIMIT 1"
    ), {"c": cik, "q": quarter}).fetchone()
    if exists is not None:
        result["skipped_already_ingested"] = True
        return result

    holdings = _fetch_information_table(cik_int, accession)
    if not holdings:
        result["error"] = "empty_information_table"
        return result

    now_iso = datetime.now(timezone.utc).isoformat()
    for h in holdings:
        cusip = h["cusip"]
        shares = int(h.get("shares", 0) or 0)
        value_thousands = int(h.get("value_thousands", 0) or 0)
        mv_cents = value_thousands * 1000 * 100  # thousands → dollars → cents
        symbol = _resolve_cusip_to_symbol(db, cusip)
        if not symbol:
            result["skipped_cusips"] += 1
            # Still record the holding — later CUSIP resolutions can back-fill
        try:
            db.execute(text("""
                INSERT INTO smart_money_13f_holdings
                    (fund_cik, fund_name, quarter, cusip, symbol,
                     shares_held, market_value_cents, filed_at, ingested_at)
                VALUES
                    (:cik, :name, :q, :cu, :s, :sh, :mv, :fd, :ing)
                ON CONFLICT (fund_cik, quarter, cusip) DO UPDATE SET
                    symbol = COALESCE(EXCLUDED.symbol, smart_money_13f_holdings.symbol),
                    shares_held = EXCLUDED.shares_held,
                    market_value_cents = EXCLUDED.market_value_cents
            """), {
                "cik": cik, "name": fund_name, "q": quarter,
                "cu": cusip, "s": symbol, "sh": shares, "mv": mv_cents,
                "fd": filing_date, "ing": now_iso,
            })
            result["rows_upserted"] += 1
        except Exception as exc:
            logger.warning("[edgar_13f] row upsert failed %s/%s: %s", cik, cusip, exc)
        # Gentle rate-limit: openfigi anon = 25/6s
        time.sleep(0.05)

    db.commit()
    logger.warning(
        "[edgar_13f] ingested %s (CIK %s, quarter %s): %d rows, %d unresolved",
        fund_name, cik, quarter, result["rows_upserted"], result["skipped_cusips"],
    )
    return result


def ingest_all_funds(db: Session) -> dict:
    """Iterate the curated fund list and ingest each."""
    seen_ciks = set()
    results = []
    for cik, name in TOP_FUND_CIKS:
        if cik in seen_ciks:
            continue
        seen_ciks.add(cik)
        try:
            results.append(_ingest_fund(db, cik, name))
        except Exception as exc:
            logger.error("[edgar_13f] fund ingest raised for %s: %s", name, exc)
            results.append({"fund": name, "cik": cik, "error": str(exc)[:200]})
        # EDGAR rate limit courtesy
        time.sleep(0.15)
    total_rows = sum(r.get("rows_upserted", 0) for r in results)
    logger.warning(
        "[edgar_13f] full ingest done: funds=%d total_rows=%d",
        len(results), total_rows,
    )
    return {"funds": len(results), "total_rows": total_rows, "results": results}


def setup_edgar_13f_scheduler(scheduler) -> None:
    """Register a weekly Sunday 03:00 UTC job. Also runs once ~30s after
    startup so the first ingest doesn't wait for Sunday."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from datetime import timedelta
    except Exception as exc:
        logger.warning("[edgar_13f] apscheduler unavailable: %s", exc)
        return

    from app.db.session import SessionLocal

    def _job() -> None:
        db = SessionLocal()
        try:
            res = ingest_all_funds(db)
            logger.warning("[edgar_13f] scheduled ingest: %s", res)
        finally:
            db.close()

    scheduler.add_job(
        _job,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
        id="edgar_13f_weekly",
        replace_existing=True,
    )
    # Also fire once ~1 minute after startup so first ingest happens now.
    scheduler.add_job(
        _job,
        DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(minutes=1)),
        id="edgar_13f_bootstrap",
        replace_existing=True,
    )
    logger.warning("[edgar_13f] scheduler registered (weekly Sun 03:00 UTC + 1-min bootstrap)")
