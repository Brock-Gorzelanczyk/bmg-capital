"""Regression: every UI surface that displays signal confidence must
multiply by 100 first.

2026-06-30 audit finding: BotDetailPage.tsx:3251 rendered
`{sig.confidence.toFixed(0)}%` — but `sig.confidence` is a 0-1 float, so
0.87 displayed as "1%" instead of "87%". Every other surface in the
codebase gets it right (`Math.round(x * 100)` or `(x * 100).toFixed(N)`).
This static grep locks the fix — any future occurrence of
`.confidence.toFixed(` without a `* 100` between the field and `.toFixed`
will fail the test.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


def _iter_tsx() -> list[Path]:
    return [p for p in FRONTEND_SRC.rglob("*.tsx")
            if "node_modules" not in p.parts and "worktrees" not in str(p)]


def test_no_confidence_toFixed_without_percent_multiply():
    """No `.confidence.toFixed(` may appear anywhere in the source unless
    the field is multiplied by 100 first (or divided from a percentage).
    """
    offenders: list[str] = []
    # Bad pattern: `\.confidence\.toFixed(` — direct toFixed on a 0-1 field.
    # Good pattern: `\.confidence \* 100\)?\.toFixed(` (multiplied first).
    bad = re.compile(r"\.confidence\.toFixed\(")
    for p in _iter_tsx():
        text = p.read_text()
        for m in bad.finditer(text):
            # Report the file + line
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"{p.relative_to(REPO_ROOT)}:{line_no}")
    assert not offenders, (
        "The following files call `.confidence.toFixed(...)` directly on a "
        "0-1 float — will display 0.87 as '1%' instead of '87%'. Multiply "
        "by 100 first (see BotDetailPage.tsx:3251 fix on 2026-06-30):\n"
        + "\n".join(f"  - {o}" for o in offenders)
    )


def test_bot_detail_signals_table_multiplies_confidence():
    """Explicit guard on BotDetailPage.tsx signals table cell — the field
    that was buggy on 2026-06-30. Even a rename should keep the fix.
    """
    src = (FRONTEND_SRC / "pages" / "BotDetailPage.tsx").read_text()
    # The signals table cell that displays confidence must NOT be the raw
    # 0-1 float. It's rendered inside a `<td>` next to strategy/reason.
    # Look for the pattern within a 200-char window around 'sig.confidence'
    # to confirm the `* 100` is present.
    tbody_start = src.find("signals.map((sig)")
    assert tbody_start > 0, "signals table iterator missing"
    section = src[tbody_start:tbody_start + 3000]
    if "sig.confidence" in section:
        # Every occurrence in this cell scope must multiply by 100.
        confidence_lines = [
            line for line in section.split("\n")
            if "sig.confidence" in line and "toFixed" in line
        ]
        for line in confidence_lines:
            assert "* 100" in line or "*100" in line, (
                f"BotDetailPage signals table renders confidence without "
                f"× 100: {line.strip()}"
            )
