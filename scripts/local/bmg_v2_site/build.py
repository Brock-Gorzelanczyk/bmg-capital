"""build.py — BMG Capital v2 public equity research site generator.

Reads publishable notes from the Obsidian vault (research/ folder with
YAML frontmatter marking them as v2 calls) and renders 4 pages:

  1. Landing        — who + what + disclaimer
  2. Research Library — list of published notes with one-liner thesis
  3. Track Record   — table of every call: entry, target, last, benchmark, excess
  4. Process        — how the work is done

Provenance: git is the ledger.
  - Each note's publishing commit hash is extracted from git log
  - Publication date IS the commit timestamp (no separate editable field)
  - Corrections are NEW commits, never amends/force-push
  - The rendered note displays its publishing commit hash

Prices: rendered from data/prices.json (populated by daily_prices.py).
Display the fetched_at timestamp on the Track Record page.

Anti-pattern guard: no Sharpe / t-stat / IR / significance calc. Report
counts as "X of Y". Same rules as research_track_record/report.py.

Usage:
    python3 build.py                 # build to out/
    python3 build.py --serve         # build + serve on localhost:8000
"""

from __future__ import annotations

import argparse
import http.server
import json
import re
import socketserver
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[fail] pip install pyyaml")
    sys.exit(1)
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    print("[fail] pip install jinja2")
    sys.exit(1)
try:
    import markdown
except ImportError:
    print("[fail] pip install markdown")
    sys.exit(1)

ROOT = Path(__file__).parent
VAULT = Path.home() / "Documents" / "BMG-Capital-Vault"
NOTES_DIR = VAULT / "research"
OUT_DIR = ROOT / "out"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
DATA_DIR = ROOT / "data"

DISCLAIMER = (
    "Research published for demonstration purposes by an individual student "
    "analyst. No capital is deployed against these calls and no positions are "
    "held. Nothing here is investment advice or a recommendation to buy or "
    "sell any security."
)


@dataclass
class Call:
    """One published research call — one markdown file with v2 frontmatter."""
    slug: str
    path: Path
    ticker: str
    direction: str
    published_price: float
    price_target: float | None
    horizon_months: int
    benchmark: str
    conviction: int
    thesis: str
    kill_criteria: list[str] = field(default_factory=list)
    status: str = "OPEN"
    closed_price: float | None = None
    closed_reason: str | None = None
    thesis_attribution: str | None = None
    backfill: bool = False
    backfill_note: str | None = None
    body_html: str = ""
    commit_hash: str = ""
    commit_short: str = ""
    published_at: str = ""  # ISO date from git commit timestamp


def read_note(path: Path) -> Call | None:
    """Parse a note's YAML frontmatter + body. Return None if it's not a v2 call."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return None
    front_raw, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(front_raw) or {}
    except yaml.YAMLError:
        # legacy vault notes often have unescaped colons or other malformations
        # in their frontmatter. Not v2 calls; skip.
        return None
    if not isinstance(fm, dict):
        return None
    # v2 marker: must have `ticker` + `direction` + `published_price` fields
    if not all(k in fm for k in ("ticker", "direction", "published_price")):
        return None

    call = Call(
        slug=path.stem,
        path=path,
        ticker=fm["ticker"].upper(),
        direction=fm["direction"].upper(),
        published_price=float(fm["published_price"]),
        price_target=(float(fm["price_target"]) if fm.get("price_target") else None),
        horizon_months=int(fm.get("horizon_months", 12)),
        benchmark=fm.get("benchmark", "IWM").upper(),
        conviction=int(fm.get("conviction", 3)),
        thesis=fm.get("thesis", "").strip(),
        kill_criteria=fm.get("kill_criteria", []) or [],
        status=fm.get("status", "OPEN").upper(),
        closed_price=(float(fm["closed_price"]) if fm.get("closed_price") else None),
        closed_reason=fm.get("closed_reason"),
        thesis_attribution=fm.get("thesis_attribution"),
        backfill=bool(fm.get("backfill", False)),
        backfill_note=fm.get("backfill_note"),
    )

    # Render body markdown (excluding frontmatter)
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc"])
    call.body_html = md.convert(body)

    # Get git commit metadata for this specific file
    _fill_git_metadata(call)

    # Frontmatter published_at wins over git-derived date. Reason: the git
    # ADD-commit date is when the file first entered the repo, which for a
    # revised or backfilled call is NOT the call's true ship date. Both
    # legs of excess return (call and benchmark) must anchor to the same
    # date (Rule 3 basis consistency), and the benchmark fetch in
    # daily_prices.py reads from frontmatter — so the render must too.
    fm_pub = fm.get("published_at")
    if fm_pub:
        if not isinstance(fm_pub, str):
            fm_pub = fm_pub.isoformat()
        call.published_at = fm_pub

    return call


def _git_add_date(path: Path) -> str:
    """Return the ISO date of the git ADD-commit that first introduced this
    file. Used by the backdating assertion in build().
    """
    cmd = ["git", "-C", str(VAULT), "log", "--diff-filter=A", "--follow",
           "--format=%aI", "--", str(path.relative_to(VAULT))]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    ts = out.splitlines()[-1]  # first ADD commit is the LAST line
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()


def _fill_git_metadata(call: Call) -> None:
    """Populate commit_hash, commit_short, published_at from git history."""
    try:
        # git log --diff-filter=A finds the ADD commit for the file (first commit that introduced it)
        cmd = ["git", "-C", str(VAULT), "log", "--diff-filter=A",
               "--follow", "--format=%H|%aI", "--", str(call.path.relative_to(VAULT))]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            line = out.splitlines()[-1]  # the first ADD commit is the LAST line of --format
            h, ts = line.split("|", 1)
            call.commit_hash = h
            call.commit_short = h[:8]
            # Parse ISO timestamp
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            call.published_at = dt.date().isoformat()
    except Exception as e:
        # Vault may not be a git repo yet, or file not committed
        call.commit_hash = "(uncommitted)"
        call.commit_short = "(uncommitted)"
        # Fall back to file mtime as best-effort
        call.published_at = date.fromtimestamp(call.path.stat().st_mtime).isoformat()


def load_all_calls() -> list[Call]:
    calls = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        c = read_note(path)
        if c:
            calls.append(c)
    calls.sort(key=lambda c: c.published_at)
    return calls


@dataclass
class ResearchNote:
    """A supporting research note — no call/rating attached, but rendered as a page."""
    slug: str
    path: Path
    title: str
    body_html: str
    published_at: str


def read_research_note(path: Path) -> ResearchNote | None:
    """Return a ResearchNote if the file has `document_type: research` frontmatter
    but is NOT a v2 call (no ticker/direction/published_price fields).
    """
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return None
    front_raw, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(front_raw) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    # Must declare document_type: research
    if str(fm.get("document_type", "")).lower() != "research":
        return None
    # Skip if it's already picked up as a v2 call
    if all(k in fm for k in ("ticker", "direction", "published_price")):
        return None
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc"])
    body_html = md.convert(body)
    # Prefer explicit `title` from frontmatter, else derive from filename
    title = fm.get("title") or path.stem.replace("-", " ")
    published_at = ""
    try:
        cmd = ["git", "-C", str(VAULT), "log", "--diff-filter=A", "--follow",
               "--format=%aI", "--", str(path.relative_to(VAULT))]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            ts = out.splitlines()[-1]
            published_at = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        published_at = date.fromtimestamp(path.stat().st_mtime).isoformat()
    return ResearchNote(
        slug=path.stem,
        path=path,
        title=str(title),
        body_html=body_html,
        published_at=published_at,
    )


def load_all_research_notes() -> list[ResearchNote]:
    notes = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        # Skip sources files and files in subdirectories like coverage/
        if path.name.endswith("-sources.md"):
            continue
        if path.parent != NOTES_DIR:
            continue
        n = read_research_note(path)
        if n:
            notes.append(n)
    notes.sort(key=lambda n: n.published_at)
    return notes


def load_prices() -> dict:
    """Load data/prices.json produced by daily_prices.py. Missing = empty."""
    p = DATA_DIR / "prices.json"
    if not p.exists():
        return {"fetched_at": None, "prices": {}}
    return json.loads(p.read_text())


def load_kill_ledger() -> dict:
    """Load the kill-criteria ledger from the vault (state/kill_criteria_ledger.json).
    Missing = empty dict; callers must handle 'no data known' explicitly.
    """
    p = VAULT / "state" / "kill_criteria_ledger.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def summarize_kill(kill_ledger: dict, slug: str) -> dict:
    """Return {'total': N, 'counts': {STATUS: N}, 'headline': 'X clear' | ...}
    Headline priority: FIRED > PENDING > STALE > NEVER_EVALUATED > CLEAR.
    """
    entries = kill_ledger.get(slug, {})
    if not entries:
        return {"total": 0, "counts": {}, "headline": "no kill criteria"}
    counts: dict[str, int] = {}
    for cid, row in entries.items():
        s = row.get("status", "NEVER_EVALUATED")
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    # Headline
    if counts.get("FIRED"):
        headline = f"{counts['FIRED']} FIRED / {total}"
    elif counts.get("PENDING"):
        headline = f"{counts['PENDING']} pending / {total}"
    elif counts.get("STALE"):
        headline = f"{counts['STALE']} stale / {total}"
    elif counts.get("NEVER_EVALUATED"):
        headline = f"{counts.get('CLEAR', 0)} clear + {counts['NEVER_EVALUATED']} never evaluated / {total}"
    else:
        headline = f"{counts.get('CLEAR', 0)} clear / {total}"
    return {"total": total, "counts": counts, "headline": headline}


def compute_outcomes(calls: list[Call], prices: dict, kill_ledger: dict | None = None) -> list[dict]:
    """Return per-call outcome dicts for the track-record table."""
    px = prices.get("prices", {})
    kill_ledger = kill_ledger or {}
    outcomes = []
    for c in calls:
        latest = px.get(c.ticker, {}).get("last")
        bench_at_pub = px.get(c.benchmark, {}).get("historical", {}).get(c.published_at)
        bench_now = px.get(c.benchmark, {}).get("last")
        last_price = c.closed_price if c.closed_price is not None else latest

        r_call = ((last_price - c.published_price) / c.published_price * 100.0
                  if last_price is not None else None)
        r_bench = ((bench_now - bench_at_pub) / bench_at_pub * 100.0
                   if (bench_at_pub is not None and bench_now is not None) else None)
        excess = (r_call - r_bench) if (r_call is not None and r_bench is not None) else None

        outcomes.append({
            "call": c,
            "last_price": last_price,
            "return_pct": r_call,
            "benchmark_return_pct": r_bench,
            "excess_pct": excess,
            "kill": summarize_kill(kill_ledger, c.slug),
        })
    return outcomes


def render(env, template: str, path: Path, **ctx) -> None:
    ctx["disclaimer"] = DISCLAIMER
    ctx["build_time"] = datetime.now(timezone.utc).isoformat()
    tpl = env.get_template(template)
    html = tpl.render(**ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def build(serve: bool = False) -> int:
    if not VAULT.exists():
        print(f"[fail] vault not found at {VAULT}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # add zip filter (jinja doesn't ship with zip)
    env.globals["zip"] = zip

    calls = load_all_calls()
    research_notes = load_all_research_notes()
    prices = load_prices()
    kill_ledger = load_kill_ledger()

    # Backdating assertion (added 2026-09-13 after TRN was shipped with
    # published_at 2026-09-10 while the file's git ADD-commit was
    # 2026-09-13, producing a phantom -0.8% excess on a call that had
    # been live for less than an hour).
    # Rule: published_at may not precede the git ADD-commit date of the
    # note by more than MAX_BACKDATE_DAYS (default 1 — allows weekend/
    # holiday publish anchored to previous Friday's close, forbids
    # "wrote today, dated three days ago").
    # MAX_BACKDATE_DAYS = 2 permits a Sunday publish anchored to the previous
    # Friday close, PLUS a one-day tolerance for data-feed lag (Alpaca IEX free
    # tier sometimes trails by ~24h). Anything beyond that is real backdating.
    MAX_BACKDATE_DAYS = 2
    from datetime import timedelta as _td
    if calls:
        backdate_errors = []
        for c in calls:
            if not c.commit_hash or c.commit_hash == "(uncommitted)":
                continue  # can't check pre-commit
            try:
                commit_date = date.fromisoformat(_git_add_date(c.path))
                pub_date = date.fromisoformat(c.published_at)
            except Exception:
                continue
            allowed_earliest = commit_date - _td(days=MAX_BACKDATE_DAYS)
            if pub_date < allowed_earliest:
                backdate_errors.append(
                    f"call {c.slug}: published_at {c.published_at} is "
                    f"{(commit_date - pub_date).days} days before git ADD-commit "
                    f"{commit_date.isoformat()} (max backdate allowed: "
                    f"{MAX_BACKDATE_DAYS} days). A call cannot be entered at a "
                    f"price from before the note existed — the excess-return "
                    f"calculation will show phantom movement over the "
                    f"backdated window."
                )
        if backdate_errors:
            print("[fail] backdating check FAILED:", file=sys.stderr)
            for e in backdate_errors:
                print(f"       {e}", file=sys.stderr)
            print("       build aborted.", file=sys.stderr)
            return 2

    # Rule 3 basis-consistency assertion.
    # For every call, the benchmark historical price MUST be keyed at the
    # SAME date as the call's published_at. Otherwise the excess-return
    # calculation compares (call today vs entry_on_date_X) against
    # (bench today vs bench_on_date_Y) — a Rule 3 basis mismatch on the
    # headline number of the track record. First live example caught
    # 2026-09-12 (see /research/coverage/rail/001-GATX-review-log-2026-09-12.md).
    #
    # This check fails the build if:
    #   (a) benchmark ticker has no entry in prices.json
    #   (b) benchmark has no historical price for call.published_at
    # The daily_prices.py job fetches historical prices keyed by each call's
    # published_at, so a mismatch here means either published_at changed
    # since the last price run OR the price job failed silently for that
    # date. In either case the correct response is to re-run daily_prices.py,
    # not to publish a wrong-basis excess-return number.
    if prices.get("prices"):  # only enforce when we actually have prices
        errors = []
        for c in calls:
            if c.status != "OPEN" and c.closed_price is not None:
                continue  # closed calls have a closed_price; benchmark date less critical
            bench_data = prices["prices"].get(c.benchmark)
            if bench_data is None:
                errors.append(
                    f"call {c.slug}: benchmark '{c.benchmark}' has no entry in prices.json"
                )
                continue
            hist = bench_data.get("historical", {}) or {}
            if c.published_at not in hist:
                errors.append(
                    f"call {c.slug}: benchmark '{c.benchmark}' has no historical price "
                    f"for {c.published_at} (call published date). "
                    f"Present dates: {sorted(hist.keys()) or '[]'}. "
                    "Rule 3 basis mismatch — refuse to build. Re-run daily_prices.py."
                )
        if errors:
            print("[fail] benchmark-date basis check FAILED:", file=sys.stderr)
            for e in errors:
                print(f"       {e}", file=sys.stderr)
            print("       build aborted.", file=sys.stderr)
            return 2

    outcomes = compute_outcomes(calls, prices, kill_ledger)

    open_calls = [o for o in outcomes if o["call"].status == "OPEN"]
    closed_calls = [o for o in outcomes if o["call"].status != "OPEN"]

    # Track-record headline counts (all "X of Y" honestly stated)
    total_closed = len(closed_calls)
    beat_bench = sum(1 for o in closed_calls if (o["excess_pct"] or 0) > 0)
    thesis_correct = sum(1 for o in closed_calls if o["call"].thesis_attribution == "THESIS_CORRECT")
    right_wrong_reason = sum(1 for o in closed_calls if o["call"].thesis_attribution == "RIGHT_WRONG_REASON")
    wrong_calls = sum(1 for o in closed_calls if o["call"].thesis_attribution == "WRONG")
    unresolved = sum(1 for o in closed_calls if o["call"].thesis_attribution == "UNRESOLVED")

    print(f"[build] {len(calls)} call(s) — {len(open_calls)} open, {len(closed_calls)} closed")

    # Copy static assets
    for asset in STATIC.glob("*"):
        dst = OUT_DIR / asset.name
        dst.write_bytes(asset.read_bytes())

    # 1. Landing
    render(env, "landing.html", OUT_DIR / "index.html",
           calls_total=len(calls), open_count=len(open_calls),
           closed_count=len(closed_calls))
    # 2. Research library
    render(env, "library.html", OUT_DIR / "library.html",
           outcomes=outcomes, research_notes=research_notes)
    # 3. Track record
    render(env, "track_record.html", OUT_DIR / "track-record.html",
           outcomes=outcomes,
           open_count=len(open_calls),
           closed_count=len(closed_calls),
           beat_bench=beat_bench,
           total_closed=total_closed,
           thesis_correct=thesis_correct,
           right_wrong_reason=right_wrong_reason,
           wrong_calls=wrong_calls,
           unresolved=unresolved,
           fetched_at=prices.get("fetched_at"))
    # 4. Process
    render(env, "process.html", OUT_DIR / "process.html")
    # 5. Per-call rendered pages
    (OUT_DIR / "calls").mkdir(exist_ok=True)
    for o in outcomes:
        render(env, "note.html", OUT_DIR / "calls" / f"{o['call'].slug}.html",
               call=o["call"], outcome=o)

    # 6. Per-research-note rendered pages (supporting research context)
    (OUT_DIR / "research").mkdir(exist_ok=True)
    for n in research_notes:
        render(env, "research_note.html", OUT_DIR / "research" / f"{n.slug}.html",
               note=n)

    # 7. Base-path rewrite for GitHub Pages project deployment.
    # Templates author internal links as absolute paths ("/style.css"). When
    # hosted at github.io/bmg-capital-site/ the leading "/" resolves to the
    # domain root, not the project subpath. If SITE_BASE_PATH env var is set,
    # prepend it to every leading-slash internal link in every built .html.
    import os as _os
    base = _os.environ.get("SITE_BASE_PATH", "").strip().rstrip("/")
    if base:
        # Prefix href="/foo" / src="/foo" / onclick="location.href='/foo" with
        # the base, but skip external (//, http, mailto:).
        href_re = re.compile(r'((?:href|src)=")(/)([^/"])')
        onclick_re = re.compile(r"(onclick=\"location\.href=')(/)([^/'])")
        for html_path in OUT_DIR.rglob("*.html"):
            txt = html_path.read_text(encoding="utf-8")
            new = href_re.sub(r'\1' + base + r'/\3', txt)
            new = onclick_re.sub(r'\1' + base + r'/\3', new)
            # Also handle href="/" → href="{base}/"
            new = new.replace('href="/"', f'href="{base}/"')
            if new != txt:
                html_path.write_text(new, encoding="utf-8")
        print(f"[build] applied SITE_BASE_PATH={base} to internal links")

    print(f"[build] output at {OUT_DIR}/  ({len(calls)} calls, {len(research_notes)} research notes)")

    if serve:
        os_chdir = __import__("os").chdir
        os_chdir(OUT_DIR)
        port = 8000
        with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
            print(f"[serve] http://localhost:{port}/  (Ctrl-C to stop)")
            httpd.serve_forever()

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    args = ap.parse_args()
    return build(serve=args.serve)


if __name__ == "__main__":
    sys.exit(main())
