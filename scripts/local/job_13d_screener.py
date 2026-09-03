"""13D activist filing screener — LOCAL, non-Railway.

Nightly (after 6 PM ET when SEC EDGAR closes indexing):
  1. Pull the SEC EDGAR daily index (last N days)
  2. Filter to 13D + 13D/A filings only (skip 13G/13G/A — passive noise)
  3. Match filer CIK against ACTIVIST_CIK_WHITELIST (Icahn, Elliott, Ackman, etc.)
  4. Extract target company + ticker (via CIK→ticker lookup at data.sec.gov)
  5. Write ranked candidate list to Obsidian vault

Research basis: research/45-sec-schedule-13d-institutional.md
- Brav/Jiang 2008: ~7% CAR in [-20,+20] window around 13D filings
- Brav/Jiang/Kim 2015: effect does NOT reverse — real value creation
- 2024 SEC amendment: 13D filing deadline tightened to 5 business days
- Retail-latency reality: first-minute pop is HFT; 20-30d medium-hold is capturable

Cost: $0 Railway (100% local, free SEC EDGAR API).
Cadence: Mon-Fri 6:30 PM ET via scripts/local/schedule.yaml.

Follows §L1 local-first architecture.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _obsidian import write_job_output  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# ACTIVIST CIK WHITELIST
# ═══════════════════════════════════════════════════════════════════════
# CIKs verified against SEC EDGAR. When these entities file a 13D, the
# academic evidence for post-filing CAR is strongest (activist track record).
# Passive institutions (Vanguard, BlackRock) file 13Gs, not 13Ds — excluded.
#
# Groupings roughly by activism style (fast/campaign/friendly).
ACTIVIST_CIK_WHITELIST: dict[str, dict[str, str]] = {
    # ── Fast/aggressive activists ────────────────────────────────────
    "0000921669": {"name": "Carl Icahn / Icahn Capital",   "style": "aggressive"},
    "0001321646": {"name": "Elliott Investment Management", "style": "aggressive"},
    "0001511144": {"name": "Pershing Square (Ackman)",     "style": "concentrated"},
    "0001386549": {"name": "Starboard Value",              "style": "operational"},
    "0001418814": {"name": "Trian Fund (Peltz)",           "style": "operational"},
    "0001040273": {"name": "ValueAct Capital",             "style": "friendly-long"},
    "0001056903": {"name": "JANA Partners",                "style": "campaign"},
    "0001466153": {"name": "Third Point (Loeb)",           "style": "campaign"},
    "0001655266": {"name": "Engine No. 1",                 "style": "ESG-activist"},
    "0001603466": {"name": "Land & Buildings (Litt)",      "style": "REIT-activist"},
    # ── Concentrated value-oriented ──────────────────────────────────
    "0001067983": {"name": "Berkshire Hathaway (Buffett)", "style": "concentrated-long"},
    "0001336528": {"name": "Baupost Group (Klarman)",      "style": "value-concentrated"},
    "0001350694": {"name": "Greenlight Capital (Einhorn)", "style": "long-short-activist"},
    # ── Newer / recently active ──────────────────────────────────────
    "0001700084": {"name": "Sachem Head Capital",          "style": "concentrated-value"},
    "0001633986": {"name": "Corvex Management",            "style": "activist-swing"},
    "0001596798": {"name": "Blue Harbour Group",           "style": "constructivist"},
}


# ═══════════════════════════════════════════════════════════════════════
# SEC EDGAR HTTP
# ═══════════════════════════════════════════════════════════════════════
# SEC's rules require a User-Agent identifying the requester.
USER_AGENT = "BMG Capital 32bgorzelanczyk@gmail.com"

# EDGAR full-text search returns filings by form type. We hit the JSON API.
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _http_get(url: str, retries: int = 2) -> str:
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if i == retries:
                raise
            time.sleep(1.0 * (i + 1))
    return ""


def _pad_cik(cik: str) -> str:
    """SEC filings API needs 10-digit zero-padded CIK."""
    return str(int(cik)).zfill(10)


# ═══════════════════════════════════════════════════════════════════════
# CIK → TICKER MAP (single fetch, cached in-memory per run)
# ═══════════════════════════════════════════════════════════════════════

def load_cik_to_ticker() -> dict[str, dict[str, Any]]:
    """Fetch SEC's official company_tickers.json → {cik_str: {ticker, title}}."""
    raw = _http_get(EDGAR_COMPANY_TICKERS_URL)
    data = json.loads(raw)
    # File is {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    out: dict[str, dict[str, Any]] = {}
    for _key, row in data.items():
        cik = _pad_cik(str(row["cik_str"]))
        out[cik] = {"ticker": row["ticker"], "title": row["title"]}
    return out


# ═══════════════════════════════════════════════════════════════════════
# FETCH RECENT 13Ds FOR A GIVEN FILER CIK
# ═══════════════════════════════════════════════════════════════════════

def fetch_filer_recent_13ds(filer_cik: str, lookback_days: int = 14) -> list[dict[str, Any]]:
    """Return list of 13D/13D/A filings by this filer in the last N days.

    Uses the filer's `submissions` endpoint at data.sec.gov which lists all
    forms they've filed. We filter to SC 13D + SC 13D/A only (13G is passive).
    """
    padded = _pad_cik(filer_cik)
    url = EDGAR_SUBMISSIONS_URL.format(cik=padded)
    try:
        raw = _http_get(url)
        data = json.loads(raw)
    except Exception as e:
        return [{"_error": f"submissions fetch failed for CIK {padded}: {e}"}]

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date()
    # SEC uses both "SC 13D" and "SCHEDULE 13D" labels historically. Accept both.
    accepted_forms = {"SC 13D", "SC 13D/A", "SCHEDULE 13D", "SCHEDULE 13D/A"}
    out: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        # We want only Schedule 13D (initial) + 13D/A (amendments). Skip 13G (passive).
        if form not in accepted_forms:
            continue
        try:
            filing_date = datetime.strptime(dates[i], "%Y-%m-%d").date()
        except Exception:
            continue
        if filing_date < cutoff:
            continue
        acc_no = accessions[i].replace("-", "") if i < len(accessions) else ""
        doc = primary_docs[i] if i < len(primary_docs) else ""
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(padded)}/{acc_no}/{doc}"
            if acc_no and doc else "n/a"
        )
        out.append({
            "form": form,
            "filing_date": dates[i],
            "accession": accessions[i],
            "filing_url": filing_url,
        })
    return out


# ═══════════════════════════════════════════════════════════════════════
# EXTRACT TARGET COMPANY FROM 13D DOCUMENT
# ═══════════════════════════════════════════════════════════════════════
# A 13D is filed AGAINST a company (the target/issuer). The filer's
# submissions endpoint tells us WHO filed but not WHO the target is.
# We fetch the filing index page and pull the subject company CIK from
# the header, which lets us map to a ticker.

_SUBJECT_CIK_RE = re.compile(r"CIK=(\d+).*?type=SC%2013D", re.IGNORECASE)


def fetch_target_cik_from_filing(accession: str, filer_cik: str) -> str | None:
    """Fetch the filing's index page and extract the SUBJECT (target) CIK.

    SEC filing pages list both filer + subject CIKs in the header. Since we
    already know the filer, the OTHER CIK on the page is the target.
    """
    acc_clean = accession.replace("-", "")
    filer_padded = _pad_cik(filer_cik)
    # Filing index page (JSON)
    idx_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={filer_padded}"
        f"&type=SC+13D&dateb=&owner=include&count=40&action=getcompany"
    )
    # Actually simpler: use the filing's own index JSON at data.sec.gov
    idx_json = f"https://www.sec.gov/Archives/edgar/data/{int(filer_padded)}/{acc_clean}/index.json"
    try:
        raw = _http_get(idx_json)
        j = json.loads(raw)
    except Exception:
        return None

    # The index.json lists all documents in the filing. The primary doc
    # (usually SCHEDULE13D.htm or a .txt cover) contains the subject header.
    directory = j.get("directory", {}).get("item", [])
    for item in directory:
        name = item.get("name", "")
        if name.lower().endswith(".txt") or "primary_doc" in name.lower() or "sc13d" in name.lower():
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(filer_padded)}/{acc_clean}/{name}"
            try:
                doc_raw = _http_get(doc_url)
            except Exception:
                continue
            # SEC full-submission .txt has 'SUBJECT COMPANY' section with CIK
            m = re.search(r"SUBJECT COMPANY[\s\S]{0,500}?CENTRAL INDEX KEY:\s*(\d+)", doc_raw, re.IGNORECASE)
            if m:
                return _pad_cik(m.group(1))
    return None


# ═══════════════════════════════════════════════════════════════════════
# THE JOB
# ═══════════════════════════════════════════════════════════════════════

def screen_13d_filings(lookback_days: int = 14) -> dict[str, Any]:
    """Main pipeline. Returns dict with candidates + errors + stats."""
    print(f"[13d_screener] Loading CIK→ticker map from SEC...")
    cik_map = load_cik_to_ticker()
    print(f"[13d_screener]   loaded {len(cik_map):,} ticker mappings")

    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    total_filings_checked = 0

    for filer_cik, filer_info in ACTIVIST_CIK_WHITELIST.items():
        print(f"[13d_screener] {filer_info['name']} (CIK {filer_cik})...")
        filings = fetch_filer_recent_13ds(filer_cik, lookback_days=lookback_days)
        time.sleep(0.15)  # SEC rate limit: 10 req/sec, be a good citizen

        for f in filings:
            if "_error" in f:
                errors.append(f["_error"])
                continue
            total_filings_checked += 1
            target_cik = fetch_target_cik_from_filing(f["accession"], filer_cik)
            time.sleep(0.15)
            if not target_cik:
                errors.append(f"no target CIK for {filer_info['name']} filing {f['accession']}")
                continue
            # Skip self-filings (activist filing on their own entity — e.g., Icahn on IEP,
            # Berkshire on BRK). Not tradeable as activist signal; it's own-position mgmt.
            if target_cik == _pad_cik(filer_cik):
                continue
            target_info = cik_map.get(target_cik)
            if not target_info:
                # Not in the ticker map — likely a private co, ADR, or fund
                errors.append(f"no ticker for target CIK {target_cik} ({filer_info['name']} filing {f['accession']})")
                continue
            candidates.append({
                "filer_name": filer_info["name"],
                "filer_style": filer_info["style"],
                "filer_cik": filer_cik,
                "target_ticker": target_info["ticker"],
                "target_name": target_info["title"],
                "target_cik": target_cik,
                "form": f["form"],
                "filing_date": f["filing_date"],
                "filing_url": f["filing_url"],
            })

    return {
        "candidates": candidates,
        "errors": errors,
        "activists_checked": len(ACTIVIST_CIK_WHITELIST),
        "total_filings_checked": total_filings_checked,
        "lookback_days": lookback_days,
    }


# ═══════════════════════════════════════════════════════════════════════
# REPORT WRITER
# ═══════════════════════════════════════════════════════════════════════

def build_report(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 13D Activist Filing Screener\n\n")
    lines.append("**What this is:** nightly SEC EDGAR pull of new Schedule 13D + 13D/A filings\n")
    lines.append("from the activist CIK whitelist. Signal source per research/45:\n")
    lines.append("Brav/Jiang 2008 ~7% CAR in [-20,+20] window; effect does NOT reverse.\n\n")
    lines.append(
        f"**Lookback:** {result['lookback_days']} days · "
        f"activists monitored: {result['activists_checked']} · "
        f"filings found: {result['total_filings_checked']}\n\n"
    )

    candidates = result.get("candidates", [])
    if not candidates:
        lines.append("## No new activist filings in lookback window\n\n")
        lines.append("Nothing to arm today. This is normal — activist filings are event-driven,\n")
        lines.append("with days/weeks of quiet between major campaigns.\n")
    else:
        # Group by ticker (an amendment + initial = same conviction)
        by_ticker: dict[str, list[dict]] = {}
        for c in candidates:
            by_ticker.setdefault(c["target_ticker"], []).append(c)

        lines.append(f"## {len(candidates)} filings across {len(by_ticker)} tickers\n\n")
        lines.append("| Ticker | Company | Activist | Style | Form | Filed | Link |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for c in sorted(candidates, key=lambda x: x["filing_date"], reverse=True):
            lines.append(
                f"| **{c['target_ticker']}** | {c['target_name'][:40]} | "
                f"{c['filer_name'][:30]} | {c['filer_style']} | "
                f"{c['form']} | {c['filing_date']} | "
                f"[filing]({c['filing_url']}) |\n"
            )
        lines.append("\n")

        # Ranked action list — tickers with multiple activist filings first
        multi = {t: fs for t, fs in by_ticker.items() if len(fs) > 1}
        if multi:
            lines.append("## HIGH CONVICTION — multiple activist filings on same ticker\n\n")
            for tkr, fs in sorted(multi.items(), key=lambda x: -len(x[1])):
                names = ", ".join(sorted(set(f["filer_name"] for f in fs)))
                lines.append(f"- **{tkr}** ({len(fs)} filings): {names}\n")
            lines.append("\n")

        lines.append("## Suggested action per ticker\n\n")
        for tkr, fs in by_ticker.items():
            latest = max(fs, key=lambda x: x["filing_date"])
            days_since = (datetime.now().date() - datetime.strptime(latest["filing_date"], "%Y-%m-%d").date()).days
            lines.append(
                f"### {tkr} — {latest['target_name']}\n"
                f"- **Filer:** {latest['filer_name']} ({latest['filer_style']})\n"
                f"- **Filed:** {latest['filing_date']} ({days_since}d ago)\n"
                f"- **Play:** 20-30d swing hold on the underlying; consider 3-6mo ITM calls for leverage\n"
                f"- **Invalidation:** target drops below pre-filing 20d avg\n"
                f"- **Size:** 1.5% NAV (Kelly-safe) for stock; 0.5% NAV premium for options\n\n"
            )

    if result.get("errors"):
        lines.append("## Non-fatal errors during run\n\n")
        for e in result["errors"][:20]:
            lines.append(f"- {e}\n")
        if len(result["errors"]) > 20:
            lines.append(f"- ...and {len(result['errors']) - 20} more\n")

    lines.append("\n---\n\n")
    lines.append("*Source:* SEC EDGAR (free public data). *Runner:* scripts/local/job_13d_screener.py (Mac).\n")
    lines.append("*Research basis:* research/45-sec-schedule-13d-institutional.md\n")
    lines.append("*Convictions to keep in mind:* first-minute pop is HFT-dominated; the 20-30d medium-hold portion of the ~7% CAR is what BMG can capture at retail latency.\n")
    return "".join(lines)


def run() -> str:
    try:
        result = screen_13d_filings(lookback_days=14)
        body = build_report(result)
        path = write_job_output("13d_screener", body)
        n = len(result.get("candidates", []))
        return f"ok · {n} candidates · wrote {path}"
    except Exception as e:
        import traceback
        err_body = "# 13D screener — FAILED\n\n```\n" + traceback.format_exc() + "\n```\n"
        write_job_output("13d_screener", err_body)
        return f"error: {e}"


if __name__ == "__main__":
    print(run())
