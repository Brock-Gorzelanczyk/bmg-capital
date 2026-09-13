"""method_block.py — print the current METHOD block from state/current.md.

Mirrors coverage_block.py. The METHOD block lists every rule in
`/reference/method/M##.md` so that a session-start read of state/current.md
surfaces the discipline layer alongside the coverage layer.

Rationale (2026-09-13):
    Rules in /reference/method/ are useless if nothing reads them. Coverage
    is auto-inserted into state/current.md and read every session; method
    now uses the same pattern. Sub-agents also need the block — this
    script is the single source for that paste.

Usage:
    python3 scripts/local/method_block.py                  # prints the block
    python3 scripts/local/method_block.py --vault /path    # override vault
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_VAULT = Path("~/Documents/BMG-Capital-Vault").expanduser()

BLOCK_RE = re.compile(
    r"(<!--\s*method-auto-start.*?<!--\s*method-auto-end\s*-->)",
    re.DOTALL,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    args = ap.parse_args()

    state_path = Path(args.vault).expanduser().resolve() / "state" / "current.md"
    if not state_path.exists():
        print(f"[fail] state file missing: {state_path}", file=sys.stderr)
        return 2
    text = state_path.read_text(encoding="utf-8")
    m = BLOCK_RE.search(text)
    if not m:
        print(f"[fail] METHOD block markers not found in {state_path}", file=sys.stderr)
        print("       expected <!-- method-auto-start ... --> ... <!-- method-auto-end -->", file=sys.stderr)
        return 3
    sys.stdout.write(m.group(1))
    if not m.group(1).endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
