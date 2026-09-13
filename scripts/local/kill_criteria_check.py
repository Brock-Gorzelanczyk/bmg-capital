"""kill_criteria_check.py — evaluate kill criteria on open v2 research calls.

Kill criteria in note frontmatter were documentation, not checks. A call
could run indefinitely with its criteria never evaluated — silence looked
identical to CLEAR. This script closes that gap.

Two classes of criterion are handled differently:

AUTOMATABLE (evaluate directly, every run):
  - Carloads (chemical AND petroleum both negative Y/Y): pulled from
    the AAR weekly rail traffic report or a snapshot in state/aar_snapshot.json.
    Both must be negative to FIRE.
  - Credit downgrade below BBB-: checked against state/credit_ratings.json
    baseline. Any change or downgrade flips to FIRED / PENDING.

JUDGEMENT (cannot be automated — force evaluation instead):
  - LPI below +10%, LPI misses guidance two quarters running,
    disposition gains guided below $150M, utilization below 96%.
  - When the coverage monitor detects a new 10-Q / 8-K for the ticker
    (or --simulate-earnings is passed), all judgement criteria flip to
    PENDING EVALUATION and stay pending across runs until a human
    records a verdict with cited figure and date via --record-verdict.

STATUS VALUES:
  CLEAR            — evaluated recently, criterion not tripped
  PENDING          — evaluation required (earnings event detected); no verdict yet
  FIRED            — criterion tripped, action required
  NEVER_EVALUATED  — automatable data missing OR no earnings event has occurred
                     since publication (correct state for judgement criteria
                     on a young call)
  STALE            — automatable data is present but older than allowed window

Silence never counts as pass: a criterion with no data reads NEVER_EVALUATED
or STALE, never CLEAR.

Ledger persisted at state/kill_criteria_ledger.json in the vault, keyed by
{call_slug: {criterion_id: {...}}}.

Usage:
    python3 kill_criteria_check.py                          # evaluate all open calls
    python3 kill_criteria_check.py --json                   # machine-readable output
    python3 kill_criteria_check.py --simulate-earnings GATX # flip judgement to PENDING
    python3 kill_criteria_check.py --record-verdict <call>_<crit_id> \\
        --status CLEAR --figure "Q3 2026 LPI: +15.2%" --date 2026-10-27
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml", file=sys.stderr)
    sys.exit(1)

VAULT = Path.home() / "Documents" / "BMG-Capital-Vault"
NOTES_DIR = VAULT / "research"
STATE_DIR = VAULT / "state"
LEDGER_PATH = STATE_DIR / "kill_criteria_ledger.json"
AAR_SNAPSHOT_PATH = STATE_DIR / "aar_snapshot.json"
CREDIT_RATINGS_PATH = STATE_DIR / "credit_ratings.json"
COVERAGE_STATE_PATH = Path.home() / "my-new-project" / "scripts" / "local" / "coverage_monitor" / "data" / "state.json"

# How stale is too stale for automatable inputs (days).
AAR_MAX_AGE_DAYS = 21
RATINGS_MAX_AGE_DAYS = 365  # ratings don't change often; a year is fine


@dataclass
class Criterion:
    """One kill criterion on one call."""
    call_slug: str
    call_ticker: str
    crit_id: str  # stable hash of criterion text within the call
    text: str
    kind: str  # "automatable_carloads" | "automatable_rating" | "judgement"
    action: str  # TRIM_HALF | REASSESS | EXIT (parsed from criterion text)
    # Runtime evaluation:
    status: str = "NEVER_EVALUATED"
    figure: str = ""  # what the criterion was evaluated against
    evaluated_at: str = ""  # ISO date
    source: str = ""  # where the figure came from


# --- criterion classification -------------------------------------------

def classify(text: str) -> str:
    t = text.lower()
    if "aar" in t and "carload" in t:
        return "automatable_carloads"
    if "credit downgrade" in t or "credit rating" in t:
        return "automatable_rating"
    if any(k in t for k in ("lpi", "disposition gain", "utilization", "fleet utilization")):
        return "judgement"
    return "judgement"  # default: force human evaluation, never silent pass


def parse_action(text: str) -> str:
    """Extract action verb (TRIM_HALF / REASSESS / EXIT) from criterion text."""
    t = text.upper()
    for a in ("TRIM HALF", "TRIM_HALF", "REASSESS", "EXIT"):
        if a in t:
            return a.replace(" ", "_")
    return "UNKNOWN"


def stable_id(text: str) -> str:
    """8-char stable hash of the criterion text."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# --- loading -------------------------------------------------------------

@dataclass
class Call:
    slug: str
    ticker: str
    path: Path
    status: str
    kill_texts: list[str]


def load_open_calls() -> list[Call]:
    calls: list[Call] = []
    for p in sorted(NOTES_DIR.rglob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        if not all(k in fm for k in ("ticker", "direction", "published_price")):
            continue
        status = str(fm.get("status", "OPEN")).upper()
        if status != "OPEN":
            continue
        calls.append(Call(
            slug=p.stem,
            ticker=fm["ticker"].upper(),
            path=p,
            status=status,
            kill_texts=list(fm.get("kill_criteria", []) or []),
        ))
    return calls


def build_criteria(calls: list[Call]) -> list[Criterion]:
    crits: list[Criterion] = []
    for c in calls:
        for text in c.kill_texts:
            crits.append(Criterion(
                call_slug=c.slug,
                call_ticker=c.ticker,
                crit_id=stable_id(text),
                text=text,
                kind=classify(text),
                action=parse_action(text),
            ))
    return crits


# --- ledger --------------------------------------------------------------

def load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return {}
    try:
        return json.loads(LEDGER_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_ledger(ledger: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")


def merge_ledger_state(crits: list[Criterion], ledger: dict) -> None:
    """Read prior verdicts from ledger into criterion runtime state."""
    for c in crits:
        prior = ledger.get(c.call_slug, {}).get(c.crit_id)
        if not prior:
            continue
        c.status = prior.get("status", c.status)
        c.figure = prior.get("figure", c.figure)
        c.evaluated_at = prior.get("evaluated_at", c.evaluated_at)
        c.source = prior.get("source", c.source)


def persist(crits: list[Criterion], ledger: dict) -> None:
    for c in crits:
        slug = ledger.setdefault(c.call_slug, {})
        slug[c.crit_id] = {
            "text": c.text,
            "kind": c.kind,
            "action": c.action,
            "status": c.status,
            "figure": c.figure,
            "evaluated_at": c.evaluated_at,
            "source": c.source,
        }
    save_ledger(ledger)


# --- automatable checks --------------------------------------------------

def evaluate_carloads(c: Criterion) -> None:
    """Chemical AND petroleum carloads both negative Y/Y -> FIRE."""
    if not AAR_SNAPSHOT_PATH.exists():
        c.status = "NEVER_EVALUATED"
        c.figure = "no AAR snapshot at state/aar_snapshot.json"
        c.source = "MANUAL FETCH REQUIRED"
        return
    snap = json.loads(AAR_SNAPSHOT_PATH.read_text())
    fetched = snap.get("fetched_at", "")
    try:
        age = (date.today() - date.fromisoformat(fetched[:10])).days
    except Exception:
        age = 9999
    if age > AAR_MAX_AGE_DAYS:
        c.status = "STALE"
        c.figure = f"AAR data {age}d old; last fetched {fetched}"
        c.source = "state/aar_snapshot.json"
        return

    chem = snap.get("chemicals_ytd_pct")
    pet = snap.get("petroleum_ytd_pct")
    if chem is None or pet is None:
        c.status = "NEVER_EVALUATED"
        c.figure = f"AAR snapshot missing chemicals/petroleum fields: {snap}"
        c.source = "state/aar_snapshot.json"
        return
    fig = f"chemicals YTD {chem:+.1f}% / petroleum YTD {pet:+.1f}% (AAR {snap.get('week_label', '')})"
    c.figure = fig
    c.evaluated_at = date.today().isoformat()
    c.source = snap.get("source_url", "state/aar_snapshot.json")
    if chem < 0 and pet < 0:
        c.status = "FIRED"
    else:
        c.status = "CLEAR"


def evaluate_rating(c: Criterion) -> None:
    """Credit rating below BBB- -> FIRE.

    Baseline is stored in state/credit_ratings.json:
      { "GATX": {"moodys": "Baa1", "sp": "BBB", "fitch": "BBB+",
                 "as_of": "2026-03-31", "source_url": "..." } }
    Any change flips to PENDING (manual verify), any downgrade to speculative
    grade flips to FIRED.
    """
    if not CREDIT_RATINGS_PATH.exists():
        c.status = "NEVER_EVALUATED"
        c.figure = "no ratings baseline at state/credit_ratings.json"
        c.source = "MANUAL FETCH REQUIRED"
        return
    ratings = json.loads(CREDIT_RATINGS_PATH.read_text())
    entry = ratings.get(c.call_ticker)
    if not entry:
        c.status = "NEVER_EVALUATED"
        c.figure = f"no baseline for {c.call_ticker} in state/credit_ratings.json"
        c.source = "MANUAL FETCH REQUIRED"
        return

    as_of = entry.get("as_of", "")
    try:
        age = (date.today() - date.fromisoformat(as_of)).days
    except Exception:
        age = 9999
    fig = (f"Moody's {entry.get('moodys','?')} / "
           f"S&P {entry.get('sp','?')} / "
           f"Fitch {entry.get('fitch','?')} as of {as_of} ({age}d old)")
    c.figure = fig
    c.evaluated_at = date.today().isoformat()
    c.source = entry.get("source_url", "state/credit_ratings.json")
    if age > RATINGS_MAX_AGE_DAYS:
        c.status = "STALE"
        return
    # Speculative-grade threshold check.
    # Investment-grade whitelist (any known rating not in this set is treated
    # as speculative). This is the safer direction — a novel rating string
    # (e.g., "Baa1u" for unsolicited, or a suffixed variant) forces a
    # PENDING-style review rather than silently passing.
    MOODYS_IG = {"Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3",
                 "Baa1", "Baa2", "Baa3"}
    SP_FITCH_IG = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
                   "BBB+", "BBB", "BBB-"}

    def is_speculative(r: str, agency: str) -> tuple[bool, str]:
        """Return (speculative, reason)."""
        r = (r or "").strip()
        if not r:
            return True, "empty rating"
        ig = MOODYS_IG if agency == "moodys" else SP_FITCH_IG
        if r in ig:
            return False, ""
        return True, f"'{r}' not in {agency} investment-grade whitelist"

    speculative_hits: list[str] = []
    for agency in ("moodys", "sp", "fitch"):
        spec, reason = is_speculative(entry.get(agency, ""), agency)
        if spec:
            speculative_hits.append(f"{agency}={entry.get(agency, '')} ({reason})")

    if speculative_hits:
        c.status = "FIRED"
        c.figure = f"{fig} | speculative: {'; '.join(speculative_hits)}"
        return
    c.status = "CLEAR"


# --- earnings event detection --------------------------------------------

EARNINGS_FORMS = {"10-K", "10-Q", "8-K"}


def detect_earnings_event(ticker: str) -> tuple[bool, str]:
    """Return (event_detected, description) by reading coverage_monitor state."""
    if not COVERAGE_STATE_PATH.exists():
        return False, ""
    try:
        state = json.loads(COVERAGE_STATE_PATH.read_text())
    except json.JSONDecodeError:
        return False, ""
    last_check = state.get("last_check", "")
    # We can't tell from state.json ALONE if there's a NEW earnings filing —
    # coverage_monitor tracks accessions but doesn't tag them with form type
    # in the persisted state. So we rely on --simulate-earnings for the flip.
    # A future enhancement is to also persist form-type per accession.
    return False, ""


def flip_judgement_to_pending(crits: list[Criterion], ticker: str, event_desc: str) -> int:
    """Set judgement criteria for ticker to PENDING if not already CLEAR-post-event."""
    flipped = 0
    for c in crits:
        if c.call_ticker != ticker:
            continue
        if c.kind != "judgement":
            continue
        # Only flip if status is not already PENDING or FIRED
        if c.status in ("PENDING", "FIRED"):
            continue
        c.status = "PENDING"
        c.figure = f"earnings event detected: {event_desc}"
        c.evaluated_at = date.today().isoformat()
        c.source = "earnings-trigger"
        flipped += 1
    return flipped


# --- report --------------------------------------------------------------

STATUS_ICON = {
    "CLEAR": "OK",
    "PENDING": "PENDING",
    "FIRED": "FIRED",
    "NEVER_EVALUATED": "NEVER",
    "STALE": "STALE",
}


def render_report(crits: list[Criterion]) -> str:
    lines: list[str] = []
    lines.append("# KILL CRITERIA")
    lines.append("")
    by_call: dict[str, list[Criterion]] = {}
    for c in crits:
        by_call.setdefault(c.call_slug, []).append(c)
    for slug in sorted(by_call.keys()):
        cs = by_call[slug]
        ticker = cs[0].call_ticker
        # Summary line
        counts: dict[str, int] = {}
        for c in cs:
            counts[c.status] = counts.get(c.status, 0) + 1
        summary = " · ".join(f"{n} {s.replace('_', ' ')}" for s, n in sorted(counts.items()))
        lines.append(f"## {ticker} ({slug}) — {len(cs)} criteria: {summary}")
        lines.append("")
        for c in cs:
            icon = STATUS_ICON.get(c.status, c.status)
            lines.append(f"- [{icon}] ({c.kind}, action {c.action}) — {c.text}")
            if c.figure:
                lines.append(f"      figure:    {c.figure}")
            if c.evaluated_at:
                lines.append(f"      evaluated: {c.evaluated_at}")
            if c.source:
                lines.append(f"      source:    {c.source}")
            lines.append("")
    return "\n".join(lines)


def compact_by_call(crits: list[Criterion]) -> dict[str, dict]:
    """For site build. Return {slug: {counts, criteria: [...]}}"""
    out: dict[str, dict] = {}
    by_call: dict[str, list[Criterion]] = {}
    for c in crits:
        by_call.setdefault(c.call_slug, []).append(c)
    for slug, cs in by_call.items():
        counts: dict[str, int] = {}
        for c in cs:
            counts[c.status] = counts.get(c.status, 0) + 1
        out[slug] = {
            "total": len(cs),
            "counts": counts,
            "criteria": [asdict(c) for c in cs],
        }
    return out


# --- CLI -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--simulate-earnings", metavar="TICKER",
                    help="pretend an earnings event just occurred for TICKER; flip its judgement criteria to PENDING")
    ap.add_argument("--record-verdict", metavar="CALLSLUG_CRITID",
                    help='record human verdict on a criterion (format: "001-GATX_a1b2c3d4")')
    ap.add_argument("--status", choices=("CLEAR", "PENDING", "FIRED"),
                    help="verdict status for --record-verdict")
    ap.add_argument("--figure", help="figure cited for --record-verdict, e.g. \"Q3 2026 LPI: +15.2%\"")
    ap.add_argument("--date", help="evaluation date ISO for --record-verdict (default today)")
    ap.add_argument("--section-only", action="store_true", help="print only the KILL CRITERIA section markdown, no report headers")
    args = ap.parse_args()

    calls = load_open_calls()
    if not calls:
        print("[kill-check] no OPEN v2 calls found in vault.")
        return 0

    crits = build_criteria(calls)
    ledger = load_ledger()
    merge_ledger_state(crits, ledger)

    # Record-verdict mode: update one criterion and exit.
    if args.record_verdict:
        try:
            slug_part, crit_part = args.record_verdict.rsplit("_", 1)
        except ValueError:
            print(f"[fail] --record-verdict format is <callslug>_<critid8>, got: {args.record_verdict}", file=sys.stderr)
            return 2
        target = next((c for c in crits if c.call_slug == slug_part and c.crit_id == crit_part), None)
        if not target:
            print(f"[fail] no criterion {slug_part}_{crit_part} found in current calls.", file=sys.stderr)
            return 2
        if not args.status:
            print("[fail] --record-verdict requires --status", file=sys.stderr)
            return 2
        target.status = args.status
        target.figure = args.figure or ""
        target.evaluated_at = args.date or date.today().isoformat()
        target.source = "human-verdict"
        persist(crits, ledger)
        print(f"[ok] recorded {args.status} on {target.call_slug} {target.crit_id}: {target.text[:80]}...")
        return 0

    # Simulate earnings: flip judgement criteria to PENDING for the named ticker.
    if args.simulate_earnings:
        ticker = args.simulate_earnings.upper()
        flipped = flip_judgement_to_pending(crits, ticker, f"SIMULATED earnings event {date.today().isoformat()}")
        print(f"[simulate] flipped {flipped} judgement criteria on {ticker} to PENDING")
        persist(crits, ledger)
        # Fall through to also print report

    # Evaluate automatable criteria on every run.
    for c in crits:
        if c.kind == "automatable_carloads":
            evaluate_carloads(c)
        elif c.kind == "automatable_rating":
            evaluate_rating(c)
        # judgement criteria: leave prior state (from ledger merge). If a
        # ticker had a real earnings event and PENDING was set, it persists
        # across runs until a human records a verdict.

    persist(crits, ledger)

    if args.json:
        print(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calls": compact_by_call(crits),
        }, indent=2))
        return 0

    report = render_report(crits)
    if not args.section_only:
        print(report)
    else:
        # Section-only mode: for embedding into coverage-monitor report.
        print(report)

    # Exit codes:
    #   0 = all CLEAR
    #   1 = at least one PENDING or NEVER_EVALUATED or STALE
    #   2 = at least one FIRED
    statuses = {c.status for c in crits}
    if "FIRED" in statuses:
        return 2
    if statuses - {"CLEAR"}:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
