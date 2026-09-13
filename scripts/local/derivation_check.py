"""derivation_check.py — arithmetic check on DERIVED sources rows.

The vault_provenance_check and falsified_audit gates verify (1) that every
inline marker in a note resolves to a sources row, and (2) that no falsified
claim reappears in a note. Neither gate verifies the arithmetic done BETWEEN
cited figures — a class of failure that reached publication three times in
one session (2026-09-12):

  - bridge components ~$32M + ~$9M + ~$4M shown as ~$46M (correct: ~$45M)
  - leverage stated 4.6x where $12.5B / $2.8B = 4.46x
  - "$0.17 divergence" between $178.18 and $177.01 (correct: $1.17)

The two figures on either side of the arithmetic were both cited and both
resolved cleanly through their marker IDs. Provenance exit 0, falsified
audit exit 0. The class was invisible to gates because gates only checked
citation, not computation.

This script closes that class. It extends the sources-file schema by
introducing an optional `## Derivations` table alongside the primary rows
table. Each row in the derivations table describes ONE DERIVED figure:

    ## Derivations

    | ID | Expression | Stated | Tolerance | Notes |
    |----|------------|--------|-----------|-------|
    | G02 | B23 * G01 | 6512.48 | 5 | market cap in $M (M shares x $/share) |
    | G35 | G30 - G29 | 45 | 0.5 | 2026 -> 2027 pretax bridge in $M |

The check parses this table, resolves each input marker's numeric value from
the corresponding row in the primary Rows table, safe-evaluates the
Expression, and compares abs(computed - Stated) <= Tolerance.

Row value resolution:
  1. If a row's Claim contains "[value: N]" (or "[value: N M]" etc.), use N.
  2. Otherwise use the FIRST number appearing in the Claim, ignoring $, K, M,
     B, x, %, and commas.
  3. If neither works, the check fails with an explicit "cannot resolve input"
     error and instructions to add "[value: N]" to the input row's Claim.

Expression grammar (safe AST subset):
  - numeric constants (int, float)
  - Name (marker ID like G01, F18, S32)
  - BinOp: + - * /
  - UnaryOp: + -
  - parenthesized subexpressions
  Any other AST node (Call, Attribute, Subscript, comprehension, etc.) is
  rejected as unsafe.

Exit codes:
  0 — all derivations tie AND every DERIVED source row has a derivation entry
  2 — at least one derivation does not tie, OR a DERIVED row has no entry
  3 — target file / sources file not found
  4 — parse error (malformed derivation row or unsafe expression)

Usage:
    python3 scripts/local/derivation_check.py path/to/note.md
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Sources-row parser (same shape as vault_provenance_check).
SOURCE_ROW_RE = re.compile(
    r"^\|\s*([A-Z]\d+)\s*\|\s*(.+?)\s*\|\s*(TIER1|TIER2|TIER3|BANNED)\s*\|",
)

# Derivations-table row parser: | ID | Expression | Stated | Tolerance | Notes |
# Notes column is optional; Tolerance defaults to 0 if empty.
DERIVATION_ROW_RE = re.compile(
    r"^\|\s*([A-Z]\d+)\s*\|\s*([^|]+?)\s*\|\s*([-+]?\d+(?:\.\d+)?)\s*\|\s*([-+]?\d+(?:\.\d+)?)\s*\|",
)

# Section header
DERIVATIONS_HEADER_RE = re.compile(r"^##\s+Derivations\s*$", re.IGNORECASE | re.MULTILINE)

# Explicit value marker: [value: 178.18] or [value: 1,349]
EXPLICIT_VALUE_RE = re.compile(r"\[value:\s*([-+]?[\d,]+(?:\.\d+)?)\s*\]", re.IGNORECASE)

# First-number heuristic: matches integers or decimals, optionally preceded
# by $ or ~$, ignoring commas. Skips isolated tokens like "Q4" or "DOT-111"
# by requiring the number to NOT be immediately preceded by a letter or "-"
# (so "Q4" won't match the "4"). We use a preceding-word-boundary that
# forbids alphanumeric/dash before the number.
FIRST_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9\-\/])\$?~?\$?\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?)",
)

# Marks a row as DERIVED (case-insensitive substring in Claim).
DERIVED_KEYWORD = re.compile(r"\bDERIVED\b", re.IGNORECASE)


@dataclass
class SourceRow:
    marker_id: str
    claim: str
    tier: str


@dataclass
class Derivation:
    marker_id: str
    expression: str
    stated: float
    tolerance: float
    notes: str
    line_no: int  # for error messages


def sources_path_for(doc_path: Path) -> Path:
    return doc_path.with_name(doc_path.stem + "-sources.md")


def parse_source_rows(src_text: str) -> dict[str, SourceRow]:
    rows: dict[str, SourceRow] = {}
    in_derivations = False
    for line in src_text.splitlines():
        if DERIVATIONS_HEADER_RE.match(line):
            in_derivations = True
            continue
        if in_derivations:
            # Once we hit the Derivations header, no more primary rows below.
            # (If a user re-adds primary rows below, that's a malformed file
            # and we'd catch orphan markers via provenance_check.)
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|\s*-+\s*\|", stripped):
            continue
        m = SOURCE_ROW_RE.match(stripped)
        if not m:
            continue
        marker_id, claim, tier = m.group(1), m.group(2), m.group(3)
        rows[marker_id] = SourceRow(marker_id=marker_id, claim=claim.strip(), tier=tier)
    return rows


def parse_derivations(src_text: str) -> tuple[list[Derivation], list[str]]:
    """Parse the ## Derivations table. Return (rows, errors)."""
    lines = src_text.splitlines()
    # Find start of derivations section.
    start = None
    for i, line in enumerate(lines):
        if DERIVATIONS_HEADER_RE.match(line):
            start = i + 1
            break
    if start is None:
        return [], []

    derivs: list[Derivation] = []
    errors: list[str] = []
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("##"):  # next section
            break
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|\s*-+\s*\|", stripped):
            continue
        # Skip header row (contains "ID" or "Expression" in first cells).
        if re.match(r"^\|\s*ID\s*\|", stripped, re.IGNORECASE):
            continue
        m = DERIVATION_ROW_RE.match(stripped)
        if not m:
            errors.append(f"L{i + 1}: cannot parse derivation row: {stripped}")
            continue
        marker_id = m.group(1)
        expression = m.group(2).strip()
        stated = float(m.group(3))
        tolerance = float(m.group(4))
        # Extract Notes column (the rest after the tolerance column)
        rest = stripped[m.end():]
        notes = ""
        # rest may look like " | some notes here |"
        rest_stripped = rest.strip()
        if rest_stripped.startswith("|"):
            rest_stripped = rest_stripped[1:].strip()
        if rest_stripped.endswith("|"):
            rest_stripped = rest_stripped[:-1].strip()
        notes = rest_stripped
        derivs.append(
            Derivation(
                marker_id=marker_id,
                expression=expression,
                stated=stated,
                tolerance=tolerance,
                notes=notes,
                line_no=i + 1,
            )
        )
    return derivs, errors


def extract_value(row: SourceRow) -> tuple[float | None, str]:
    """Return (value, method) where method is 'explicit' or 'heuristic' or 'none'."""
    m = EXPLICIT_VALUE_RE.search(row.claim)
    if m:
        return float(m.group(1).replace(",", "")), "explicit"
    m = FIRST_NUMBER_RE.search(row.claim)
    if m:
        return float(m.group(1).replace(",", "")), "heuristic"
    return None, "none"


# --- safe AST evaluator ---------------------------------------------------

ALLOWED_BINOPS = {ast.Add, ast.Sub, ast.Mult, ast.Div}
ALLOWED_UNOPS = {ast.UAdd, ast.USub}


class UnsafeExpressionError(ValueError):
    pass


def _safe_eval(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, values)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise UnsafeExpressionError(f"non-numeric constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise UnsafeExpressionError(f"unknown name: {node.id}")
        return values[node.id]
    if isinstance(node, ast.BinOp):
        if type(node.op) not in ALLOWED_BINOPS:
            raise UnsafeExpressionError(f"unsupported binary op: {type(node.op).__name__}")
        left = _safe_eval(node.left, values)
        right = _safe_eval(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise UnsafeExpressionError("division by zero")
            return left / right
    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in ALLOWED_UNOPS:
            raise UnsafeExpressionError(f"unsupported unary op: {type(node.op).__name__}")
        operand = _safe_eval(node.operand, values)
        if isinstance(node.op, ast.UAdd):
            return +operand
        return -operand
    raise UnsafeExpressionError(f"unsupported AST node: {type(node).__name__}")


def safe_eval(expression: str, values: dict[str, float]) -> float:
    tree = ast.parse(expression, mode="eval")
    return _safe_eval(tree, values)


def marker_ids_in_expression(expression: str) -> list[str]:
    """Extract all Name-node identifiers from expression."""
    ids: list[str] = []
    for node in ast.walk(ast.parse(expression, mode="eval")):
        if isinstance(node, ast.Name):
            ids.append(node.id)
    return ids


# --- main -----------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    doc_path = Path(args.doc).expanduser().resolve()
    if not doc_path.exists():
        print(f"[fail] document not found: {doc_path}", file=sys.stderr)
        return 3
    src_path = sources_path_for(doc_path)
    if not src_path.exists():
        print(f"[fail] sources file not found: {src_path.name}", file=sys.stderr)
        return 3

    src_text = src_path.read_text(encoding="utf-8")

    rows = parse_source_rows(src_text)
    derivs, parse_errors = parse_derivations(src_text)

    if parse_errors:
        print(f"[fail] {len(parse_errors)} parse error(s) in derivations table:", file=sys.stderr)
        for e in parse_errors:
            print(f"       {e}", file=sys.stderr)
        return 4

    print(f"[check] derivation arithmetic on {doc_path.name}")
    print(f"        source rows: {len(rows)}   derivations declared: {len(derivs)}")

    # 1) Verify every DERIVED row has a derivation entry.
    derived_row_ids = {mid for mid, r in rows.items() if DERIVED_KEYWORD.search(r.claim)}
    declared_ids = {d.marker_id for d in derivs}
    undeclared = sorted(derived_row_ids - declared_ids)

    # 2) Verify each derivation.
    failures: list[str] = []
    passes = 0
    skipped = 0
    for d in derivs:
        # Explicit opt-out for derivations that cannot be expressed as
        # simple arithmetic (e.g., analyst-modeled ranges, uncertainty bands).
        # Notes field must justify. Row is counted as "declared" for the
        # requirement that every DERIVED source row has a derivation entry.
        if d.expression.strip().upper() == "SKIP":
            skipped += 1
            if args.verbose or True:
                print(f"          [{d.marker_id}] SKIP — {d.notes or '(no reason given)'}")
            continue
        input_ids = marker_ids_in_expression(d.expression)
        input_values: dict[str, float] = {}
        missing_inputs: list[str] = []
        unresolvable: list[str] = []
        for iid in input_ids:
            row = rows.get(iid)
            if row is None:
                missing_inputs.append(iid)
                continue
            v, method = extract_value(row)
            if v is None:
                unresolvable.append(iid)
                continue
            input_values[iid] = v
            if args.verbose:
                print(f"          input {iid} = {v} (via {method})")
        if missing_inputs:
            failures.append(
                f"[{d.marker_id}] L{d.line_no}: expression references marker(s) "
                f"not in sources file: {missing_inputs}"
            )
            continue
        if unresolvable:
            failures.append(
                f"[{d.marker_id}] L{d.line_no}: cannot extract numeric value from "
                f"input row(s): {unresolvable}. "
                f"Add '[value: N]' to the input row's Claim."
            )
            continue
        try:
            computed = safe_eval(d.expression, input_values)
        except UnsafeExpressionError as e:
            failures.append(
                f"[{d.marker_id}] L{d.line_no}: unsafe / invalid expression '{d.expression}': {e}"
            )
            continue
        except SyntaxError as e:
            failures.append(
                f"[{d.marker_id}] L{d.line_no}: expression '{d.expression}' has syntax error: {e}"
            )
            continue

        diff = abs(computed - d.stated)
        if diff > d.tolerance:
            failures.append(
                f"[{d.marker_id}] L{d.line_no}: MISMATCH  stated={d.stated}  "
                f"computed={computed:.6g}  diff={diff:.6g}  tolerance={d.tolerance}  "
                f"expression={d.expression!r}"
            )
        else:
            passes += 1
            if args.verbose:
                print(f"          [{d.marker_id}] pass  stated={d.stated}  computed={computed:.6g}")

    # Reports
    print(f"        {passes} of {len(derivs) - skipped} arithmetic derivations pass "
          f"({skipped} SKIP-opted-out)")
    if undeclared:
        print(f"[fail]  {len(undeclared)} DERIVED row(s) without a Derivations entry:")
        for uid in undeclared:
            print(f"        {uid}: {rows[uid].claim[:100]}...")
        print("        Each DERIVED row must have a matching row in the ## Derivations table.")
        return 2

    if failures:
        print(f"[fail]  {len(failures)} derivation(s) do not tie:")
        for f in failures:
            print(f"        {f}")
        return 2

    print("[ok]    all derivations tie, all DERIVED rows have derivation entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
