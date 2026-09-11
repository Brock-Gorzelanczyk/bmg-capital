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

    return call


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


def load_prices() -> dict:
    """Load data/prices.json produced by daily_prices.py. Missing = empty."""
    p = DATA_DIR / "prices.json"
    if not p.exists():
        return {"fetched_at": None, "prices": {}}
    return json.loads(p.read_text())


def compute_outcomes(calls: list[Call], prices: dict) -> list[dict]:
    """Return per-call outcome dicts for the track-record table."""
    px = prices.get("prices", {})
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
    prices = load_prices()
    outcomes = compute_outcomes(calls, prices)

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
    render(env, "library.html", OUT_DIR / "library.html", outcomes=outcomes)
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

    print(f"[build] output at {OUT_DIR}/")

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
