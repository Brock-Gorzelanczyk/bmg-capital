"""artifact_consistency.py — check downstream artifacts for headline/table drift.

Purpose (per M19). A source note can pass its ship gate while the downstream
one-pager, deck, or PDF contains a scenario table that uses a multiple the
note argues against, or a price target that does not tie to (EPS * multiple)
within tolerance. Every arithmetic step is individually defensible; the
document contradicts itself.

This script scans a rendered artifact (HTML text layer or plain text) for:
  1. Every dollar price of the form $NNN or $NNN.NN.
  2. Every multiple of the form NN.N× or NN.Nx.
  3. Every EPS of the form $NN.NN in a context that reads as EPS.

Checks:
  A. The headline multiple (declared explicitly in the artifact via a
     comment `<!-- consistency:headline-multiple=17.8 -->`) matches every
     multiple used in a scenario table row that also carries a
     scenario-multiple marker. If a scenario row's multiple differs from
     the headline multiple, that is a fail unless the row is explicitly
     marked as an alternative scenario (`consistency:allow-multiple`).
  B. Every row that carries `consistency:price=$NNN eps=$NN.NN mult=NN.N`
     inline comment ties within $2/share tolerance (default) of
     `EPS * multiple`.

Both are opt-in via inline HTML comments — the check does not try to
infer the headline multiple from the document structure (fragile). Adding
the comments is a one-time markering pass per artifact, same shape as
the source-note inline marker discipline.

The check ALSO runs a mode-A pass that does not require markers: it
extracts all multiples in the document and flags any distinct multiple
value that appears in a `<table>` context — human review of the flag
list is the fallback for documents that have not yet been markered.

Exit codes:
  0 = all checks pass (or no consistency markers present + no drift
      detected in table multiples).
  2 = consistency violation: a marked scenario row's multiple does not
      match the headline multiple, or a marked price row does not tie
      to (EPS * multiple) within tolerance.
  3 = target file not found.

Usage:
  python3 scripts/local/artifact_consistency.py path/to/artifact.html
  python3 scripts/local/artifact_consistency.py path/to/artifact.html --tolerance 3.0
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADLINE_MARKER = re.compile(r"consistency:headline-multiple=([\d.]+)")
PRICE_MARKER = re.compile(
    r"consistency:price=\$?([\d.]+)\s+eps=\$?([\d.]+)\s+mult=([\d.]+)"
)
ALLOW_MULTIPLE_MARKER = "consistency:allow-multiple"
MULTIPLE_IN_TEXT = re.compile(r"(\d{1,2}\.\d)\s*[×x]")


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def strip_tags(html: str) -> str:
    """Rough tag strip for text-layer scanning."""
    no_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_script)
    entities = (
        no_tags.replace("&mdash;", " -- ")
        .replace("&ndash;", "-")
        .replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&middot;", " . ")
        .replace("&times;", "x")
        .replace("&divide;", "/")
        .replace("&minus;", "-")
        .replace("&amp;", "&")
    )
    return re.sub(r"\s+", " ", entities)


def check_headline_consistency(html: str, tolerance: float) -> list[str]:
    """Marker-driven consistency checks. Returns list of failure messages."""
    errors: list[str] = []

    headline_match = HEADLINE_MARKER.search(html)
    if not headline_match:
        # Marker-based headline check is opt-in.
        return errors
    headline_mult = float(headline_match.group(1))

    # Check every price row marker
    for m in PRICE_MARKER.finditer(html):
        price = float(m.group(1))
        eps = float(m.group(2))
        mult = float(m.group(3))
        computed = eps * mult
        if abs(computed - price) > tolerance:
            errors.append(
                f"price row: EPS ${eps:.2f} * mult {mult}x = ${computed:.2f} "
                f"but declared price ${price:.2f} (diff ${abs(computed - price):.2f}, "
                f"tolerance ${tolerance:.2f})"
            )
        # If this row's multiple is NOT the headline multiple and NOT marked
        # as an intentional alternative, that is a drift.
        row_context = html[max(0, m.start() - 200) : m.end() + 200]
        if abs(mult - headline_mult) > 0.05 and ALLOW_MULTIPLE_MARKER not in row_context:
            errors.append(
                f"scenario row multiple {mult}x differs from headline multiple "
                f"{headline_mult}x with no `consistency:allow-multiple` marker "
                f"(context: '...{row_context[190:250]}...')"
            )
    return errors


def scan_multiples_in_tables(html: str) -> dict[str, list[str]]:
    """Mode-A pass. Find every multiple that appears inside a <table>
    context and group by value. Returns {multiple_value: [row_snippets]}."""
    groups: dict[str, list[str]] = {}
    for table_match in re.finditer(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE):
        table_html = table_match.group(0)
        table_text = strip_tags(table_html)
        for m in MULTIPLE_IN_TEXT.finditer(table_text):
            val = m.group(1)
            snippet = table_text[max(0, m.start() - 40) : m.end() + 40].strip()
            groups.setdefault(val, []).append(snippet)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact", help="path to HTML or text artifact")
    ap.add_argument(
        "--tolerance",
        type=float,
        default=2.0,
        help="dollar tolerance for (EPS * multiple) vs declared price (default $2)",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="only print PASS/FAIL summary lines",
    )
    args = ap.parse_args()

    path = Path(args.artifact)
    if not path.exists():
        print(f"[fail] artifact not found: {path}", file=sys.stderr)
        return 3

    html = load_text(path)
    errors = check_headline_consistency(html, args.tolerance)

    # Mode-A: report distinct multiples found in tables (advisory, not fail)
    table_mults = scan_multiples_in_tables(html)

    if not args.quiet:
        print(f"[check] artifact_consistency.py on {path.name}")
        if table_mults:
            print(f"        distinct multiples in <table> contexts: {sorted(table_mults.keys())}")
        if HEADLINE_MARKER.search(html):
            hm = HEADLINE_MARKER.search(html).group(1)
            print(f"        headline multiple declared: {hm}x")
        else:
            print("        no `consistency:headline-multiple=` marker present — running advisory pass only")

    if errors:
        print(f"[fail] {len(errors)} consistency violation(s):")
        for e in errors:
            print(f"       - {e}")
        print(f"       document is NOT shippable per M19.")
        return 2

    print("[ok]   no consistency violations detected.")
    if not HEADLINE_MARKER.search(html):
        print("       (advisory mode — add `consistency:headline-multiple=X` and per-row `consistency:price=$Y eps=$Z mult=W` markers to enable strict enforcement.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
