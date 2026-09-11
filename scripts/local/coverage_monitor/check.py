"""check.py — coverage monitor for the BMG v2 research portfolio.

For every covered ticker (OPEN v2 call in the vault), reports:
  - CIK resolved via SEC's company_tickers.json (cached)
  - Days since the note's most recent git commit (thesis update age)
  - Recent SEC filings from data.sec.gov/submissions/CIK{padded}.json
  - Form 4 insider activity, aggregated by 30-day window (NOT alerted
    individually — Form 4s are reporting, not safety)
  - Filings that appeared since the last check run
  - Next earnings: "TBD (watching for announcement 8-K)" until GATX-style
    "Sets Date for Third-Quarter 2026 Earnings Release" 8-K is detected

Alert tiers (parallels the invariant-engine safety-vs-reporting split):

  SAFETY (individual alerts):
    - New 10-K, 10-Q, 8-K, 13D/13G, DEF 14A, S-1/3, 424B
    - Open-market purchase on Form 4 (rare, high-signal)
    - Insider-selling CLUSTER: 3+ distinct insiders in same direction
      within a 30-day window (excluding 10b5-1 and tax-withholding)
    - Thesis staleness > 60 days on an OPEN call

  REPORTING (summary line, no alerts):
    - Individual Form 4s (routine vesting, 10b5-1s, tax withholding)
    - Historical filings we've already seen

Zero marginal cost: SEC EDGAR only. yfinance was removed 2026-09-10 as
load-bearing risk.

SEC EDGAR rate limit: <=10 req/sec. User-Agent set per SEC policy.

Form 4 transaction-code reference (subset used here):
  P = Open market or private PURCHASE     -> ALERT INDIVIDUALLY
  S = Open market or private SALE          -> counted for cluster only
  A = Grant/award (compensation)           -> excluded (not open market)
  M = Exercise/conversion of derivative    -> excluded
  F = Payment of exercise price or tax by
      delivering securities                -> excluded (tax withholding)
  D = Sale back to issuer (buyback)        -> excluded
  G = Bona fide gift                       -> excluded
  X = Exercise of in-the-money derivative  -> excluded

10b5-1 detection: the Form 4 primary XML has a checkbox flag
`<footnoteId id="Fn1"/>` referencing a footnote that mentions 10b5-1,
plus an explicit `<rule10b5-1Trans>1</rule10b5-1Trans>` element as of
the SEC's Dec 2022 amendment. We check both.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("[fail] pip install requests")
    sys.exit(1)
try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml")
    sys.exit(1)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
VAULT = Path.home() / "Documents" / "BMG-Capital-Vault"
NOTES_DIR = VAULT / "research"

UA = {
    "User-Agent": "BMG Capital Research brock@bmg-capital.com",
    "Accept-Encoding": "gzip, deflate",
}

# Filings that always fire an individual alert
SAFETY_FORMS = {"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A",
                "S-1", "S-3", "424B", "DEF 14A", "SC 13D", "SC 13G",
                "SC 13D/A", "SC 13G/A"}
# Filings we track but do not individually alert on
REPORTING_FORMS = {"4", "4/A", "3", "5"}
ALL_TRACKED_FORMS = SAFETY_FORMS | REPORTING_FORMS

CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_INSIDERS = 3
STALE_THESIS_DAYS = 60


@dataclass
class InsiderTxn:
    accession: str
    filed_date: str
    insider_name: str
    transaction_code: str  # P, S, A, M, F, D, G, X
    transaction_date: str
    shares: float
    is_10b5_1: bool


@dataclass
class Ticker:
    symbol: str
    note_path: Path
    thesis: str
    published_at: str = ""
    last_update_at: str = ""
    last_update_days: int | None = None
    cik: str = ""
    cik_padded: str = ""
    next_earnings_state: str = "TBD (watching for announcement 8-K)"
    recent_filings: list[dict] = field(default_factory=list)
    new_filings: list[dict] = field(default_factory=list)
    insider_txns: list[InsiderTxn] = field(default_factory=list)
    new_insider_txns: list[InsiderTxn] = field(default_factory=list)


def load_covered_tickers() -> list[Ticker]:
    """Read vault research/ for OPEN v2 calls."""
    out = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m: continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict): continue
        if not all(k in fm for k in ("ticker", "direction", "published_price")):
            continue
        if fm.get("status", "OPEN").upper() != "OPEN":
            continue
        t = Ticker(
            symbol=fm["ticker"].upper(),
            note_path=path,
            thesis=fm.get("thesis", "").strip(),
        )
        pub = fm.get("published_at")
        t.published_at = pub if isinstance(pub, str) else (pub.isoformat() if pub else "")
        out.append(t)
    return out


def fill_git_metadata(t: Ticker) -> None:
    try:
        rel = t.note_path.relative_to(VAULT)
        cmd = ["git", "-C", str(VAULT), "log", "-1", "--format=%aI", "--", str(rel)]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            dt = datetime.fromisoformat(out.replace("Z", "+00:00"))
            t.last_update_at = dt.date().isoformat()
            t.last_update_days = (date.today() - dt.date()).days
    except Exception:
        t.last_update_at = "(uncommitted)"


def load_ticker_cik_map() -> dict[str, tuple[str, str]]:
    cache = DATA / "company_tickers.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 86400 * 7:
        payload = json.loads(cache.read_text())
    else:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=UA, timeout=30)
        r.raise_for_status()
        payload = r.json()
        cache.write_text(json.dumps(payload))
    out = {}
    for entry in payload.values():
        tk = entry.get("ticker", "").upper()
        cik = entry.get("cik_str")
        title = entry.get("title", "")
        if tk and cik:
            out[tk] = (str(cik), title)
    return out


def fetch_filings(cik_padded: str, limit: int = 40) -> list[dict]:
    """Get recent filings from SEC submissions API."""
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code != 200:
        return []
    payload = r.json()
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    out = []
    for i in range(min(len(forms), limit * 5)):
        if forms[i] not in ALL_TRACKED_FORMS:
            continue
        out.append({
            "form": forms[i],
            "accession": accessions[i],
            "filed": filing_dates[i],
            "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
        })
        if len(out) >= limit:
            break
    return out


def parse_form4_xml(cik: str, accession: str, primary_doc: str) -> list[InsiderTxn]:
    """Fetch the Form 4 XML and extract non-derivative transactions.

    Skips derivative transactions (usually stock options, less signal-heavy
    than direct open-market activity).
    """
    accession_clean = accession.replace("-", "")
    # The primary_doc from the submissions API often has an XSLT viewer
    # prefix (e.g., "xslF345X06/primarydocument.xml"). The actual XML lives
    # at the accession root without that prefix. Try:
    #   1. primary_doc with any "xsl*/" prefix stripped
    #   2. "primarydocument.xml" (SEC canonical name)
    #   3. "form4.xml" (legacy)
    stripped = primary_doc
    if stripped and "/" in stripped:
        stripped = stripped.rsplit("/", 1)[-1]
    candidates = [
        stripped if stripped.endswith(".xml") else None,
        "primarydocument.xml",
        "form4.xml",
    ]
    candidates = [c for c in candidates if c]
    txns: list[InsiderTxn] = []
    for cand in candidates:
        if not cand: continue
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{cand}"
        try:
            r = requests.get(url, headers=UA, timeout=15)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            # reporting owner
            owner_name = ""
            for elem in root.iter():
                if elem.tag.endswith("rptOwnerName"):
                    owner_name = (elem.text or "").strip()
                    break
            # non-derivative transactions
            for txn in root.iter():
                if not txn.tag.endswith("nonDerivativeTransaction"):
                    continue
                code = ""
                tdate = ""
                shares = 0.0
                is_10b5 = False
                for e in txn.iter():
                    if e.tag.endswith("transactionCode"):
                        code = (e.text or "").strip()
                    elif e.tag.endswith("transactionDate"):
                        # transactionDate has a nested <value>
                        for v in e.iter():
                            if v.tag.endswith("value"):
                                tdate = (v.text or "").strip()
                                break
                    elif e.tag.endswith("transactionShares"):
                        for v in e.iter():
                            if v.tag.endswith("value"):
                                try:
                                    shares = float((v.text or "0").strip())
                                except ValueError:
                                    shares = 0.0
                                break
                # 10b5-1 flag — SEC amended Form 4 in Dec 2022 to include
                # <rule10b5-1Trans> element or a footnote
                for elem in root.iter():
                    if elem.tag.endswith("rule10b5-1Trans"):
                        if (elem.text or "").strip() == "1":
                            is_10b5 = True
                            break
                # Also check footnotes for "10b5-1" text
                if not is_10b5:
                    for elem in root.iter():
                        if elem.tag.endswith("footnote"):
                            if "10b5" in (elem.text or ""):
                                is_10b5 = True
                                break
                if code:
                    txns.append(InsiderTxn(
                        accession=accession,
                        filed_date="",  # set by caller
                        insider_name=owner_name,
                        transaction_code=code,
                        transaction_date=tdate,
                        shares=shares,
                        is_10b5_1=is_10b5,
                    ))
            if txns:
                return txns
        except (requests.RequestException, ET.ParseError):
            continue
    return txns


def summarize_insider_activity(t: Ticker) -> tuple[list[str], list[str]]:
    """Return (alerts, summary_lines) for insider activity.

    ALERTS:
      - Any P (purchase) transaction, non-10b5-1
      - Cluster: 3+ distinct insiders with S (sales) in 30-day window,
        excluding 10b5-1 and F (tax withholding)

    SUMMARY:
      - Rolling 30-day tally by transaction code, distinct-insider count
    """
    alerts = []
    # Filter and count
    signal_txns = [
        x for x in t.insider_txns
        if x.transaction_code in ("P", "S")
        and not x.is_10b5_1
    ]
    # Purchases — individual alerts
    for tx in signal_txns:
        if tx.transaction_code == "P":
            alerts.append(
                f"INSIDER PURCHASE: {t.symbol} — {tx.insider_name} bought "
                f"{int(tx.shares):,} shares on {tx.transaction_date} "
                f"(Form 4 accession {tx.accession[-8:]}, non-10b5-1). "
                "Open-market insider buys are rare and carry signal."
            )
    # Cluster detection — group sales by insider in rolling 30-day window
    # Bucket sales by transaction_date (approximate — one bucket per filing)
    today = date.today()
    recent_sales = [
        x for x in signal_txns
        if x.transaction_code == "S"
        and x.transaction_date
        and (today - date.fromisoformat(x.transaction_date)).days <= CLUSTER_WINDOW_DAYS
    ]
    distinct_sellers = {x.insider_name for x in recent_sales if x.insider_name}
    if len(distinct_sellers) >= CLUSTER_MIN_INSIDERS:
        alerts.append(
            f"INSIDER SELLING CLUSTER: {t.symbol} — {len(distinct_sellers)} distinct "
            f"insiders sold in the last {CLUSTER_WINDOW_DAYS} days (non-10b5-1). "
            f"Sellers: {', '.join(sorted(distinct_sellers))}"
        )

    # Summary line — always emitted (report, not alert)
    if t.insider_txns:
        by_code = defaultdict(int)
        by_code_10b5 = defaultdict(int)
        for x in t.insider_txns:
            if x.is_10b5_1:
                by_code_10b5[x.transaction_code] += 1
            else:
                by_code[x.transaction_code] += 1
        summary = []
        for code in ("P", "S", "A", "M", "F", "D", "G", "X"):
            n = by_code[code]
            m10b5 = by_code_10b5[code]
            if n + m10b5 > 0:
                summary.append(f"{code}={n}" + (f"(+{m10b5} 10b5-1)" if m10b5 else ""))
        summary_line = "  Insider activity (last 40 filings): " + ", ".join(summary)
        return alerts, [summary_line]
    return alerts, []


def load_state() -> dict:
    p = DATA / "state.json"
    if not p.exists():
        return {"last_check": None, "seen_accessions": {}}
    return json.loads(p.read_text())


def save_state(state: dict) -> None:
    (DATA / "state.json").write_text(json.dumps(state, indent=2))


def build_report(tickers: list[Ticker]) -> tuple[str, list[str]]:
    today = date.today().isoformat()
    alerts: list[str] = []
    per_ticker_summary_lines: dict[str, list[str]] = {}

    for t in tickers:
        # Safety-tier filing alerts
        for f in t.new_filings:
            if f["form"] in SAFETY_FORMS:
                alerts.append(f"NEW {f['form']}: {t.symbol} filed on {f['filed']} — "
                              f"thesis last updated {t.last_update_days} days ago "
                              f"({t.last_update_at})")
        # Insider (Form 4) alerts + summary
        insider_alerts, insider_summary = summarize_insider_activity(t)
        alerts.extend(insider_alerts)
        per_ticker_summary_lines[t.symbol] = insider_summary
        # Stale thesis on open call
        if t.last_update_days is not None and t.last_update_days > STALE_THESIS_DAYS:
            alerts.append(f"STALE THESIS: {t.symbol} — last updated {t.last_update_days} "
                          f"days ago ({t.last_update_at})")

    lines = [f"# Coverage Status — {today}", ""]
    if alerts:
        lines.append(f"## ALERTS ({len(alerts)})")
        lines.append("")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append("")
    else:
        lines.append("## No alerts.")
        lines.append("")

    lines.append(f"## Covered tickers ({len(tickers)})")
    lines.append("")
    for t in tickers:
        lines.append(f"### {t.symbol} — CIK {t.cik_padded or '(unresolved)'}")
        lines.append(f"- Note: `{t.note_path.relative_to(VAULT)}`")
        thesis_short = t.thesis[:120] + ("…" if len(t.thesis) > 120 else "")
        lines.append(f"- Thesis: {thesis_short}")
        lines.append(f"- Published: {t.published_at}")
        lines.append(f"- Thesis last updated: {t.last_update_at} "
                     f"({t.last_update_days} days ago)")
        lines.append(f"- Next earnings: {t.next_earnings_state}")
        lines.append(f"- Recent safety-tier filings (last 8):")
        safety_recent = [f for f in t.recent_filings if f["form"] in SAFETY_FORMS][:8]
        if not safety_recent:
            lines.append("    (none)")
        else:
            for f in safety_recent:
                is_new = " **NEW**" if f in t.new_filings else ""
                lines.append(f"    - {f['filed']}: {f['form']}{is_new}")
        for line in per_ticker_summary_lines.get(t.symbol, []):
            lines.append(line)
        lines.append("")

    return "\n".join(lines), alerts


def main() -> int:
    DATA.mkdir(exist_ok=True)
    tickers = load_covered_tickers()
    if not tickers:
        print("[coverage] no OPEN v2 calls found in vault. Nothing to monitor.")
        return 0

    print(f"[coverage] monitoring {len(tickers)} ticker(s)")
    state = load_state()
    cik_map = load_ticker_cik_map()

    for t in tickers:
        fill_git_metadata(t)
        info = cik_map.get(t.symbol)
        if not info:
            print(f"  {t.symbol}: CIK not found in SEC ticker map — skip")
            continue
        t.cik, name = info
        t.cik_padded = f"{int(t.cik):010d}"
        print(f"  {t.symbol}: CIK {t.cik_padded} ({name})")

        # Fetch filings
        t.recent_filings = fetch_filings(t.cik_padded, limit=40)
        time.sleep(0.12)

        # Diff against state
        seen = set(state["seen_accessions"].get(t.symbol, []))
        t.new_filings = [f for f in t.recent_filings if f["accession"] not in seen]
        state["seen_accessions"][t.symbol] = list(
            seen | {f["accession"] for f in t.recent_filings}
        )

        # Parse Form 4 XML for any recent Form 4s (both new and previously seen,
        # up to 20 total — for cluster detection over 30-day window)
        form4s = [f for f in t.recent_filings if f["form"] in ("4", "4/A")][:20]
        for f4 in form4s:
            txns = parse_form4_xml(t.cik, f4["accession"], f4["primary_doc"])
            for tx in txns:
                tx.filed_date = f4["filed"]
            t.insider_txns.extend(txns)
            time.sleep(0.12)
        print(f"    {len(form4s)} Form 4 filings, {len(t.insider_txns)} non-derivative txns parsed")

    report_md, alerts = build_report(tickers)
    report_path = VAULT / "coverage-status.md"
    report_path.write_text(report_md)
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print()
    print("=" * 60)
    print(report_md)
    print("=" * 60)
    print(f"\nWrote report to {report_path}")

    # Exit codes:
    #   0 = no alerts
    #   1 = alerts other than new safety filings
    #   2 = at least one new safety-tier filing (highest attention required)
    if not alerts:
        return 0
    any_new_safety = any(
        a.startswith(("NEW 10-K", "NEW 10-Q", "NEW 8-K", "NEW SC ", "NEW DEF ",
                      "NEW S-", "NEW 424", "INSIDER PURCHASE", "INSIDER SELLING"))
        for a in alerts
    )
    return 2 if any_new_safety else 1


if __name__ == "__main__":
    sys.exit(main())
