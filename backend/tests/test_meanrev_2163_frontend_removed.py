"""Regression: crypto_meanrev_2163 must NOT appear as a display entry in
the frontend anywhere.

2026-06-30 evening cleanup: this profile was retired months ago but still
lived as a hardcoded row in 5 frontend files (StrategyLab BOT_META +
BOT_ORDER, BotHealthPage NAMES, PortfolioDetailPage BOT_META, AdminBotsPage
NAMES). It rendered as a phantom "Mean Rev 2163" bot in the side-by-side
comparison + admin surfaces even though the backend leaderboards no longer
return it.

Backend DISPLAY_NAMES dicts still contain the entry as a harmless fallback
(if the profile ever returns, it'd render with a name instead of a slug).
Only the frontend hardcoded lists need to be clean.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


def test_no_meanrev_2163_in_frontend_source():
    """No file under frontend/src/ may reference crypto_meanrev_2163."""
    offenders: list[str] = []
    for p in FRONTEND_SRC.rglob("*.tsx"):
        if "node_modules" in p.parts:
            continue
        text = p.read_text()
        if "crypto_meanrev_2163" in text or "Mean Rev 2163" in text or "MeanRev 2163" in text:
            offenders.append(str(p.relative_to(REPO_ROOT)))
    for p in FRONTEND_SRC.rglob("*.ts"):
        if "node_modules" in p.parts:
            continue
        text = p.read_text()
        if "crypto_meanrev_2163" in text or "Mean Rev 2163" in text or "MeanRev 2163" in text:
            offenders.append(str(p.relative_to(REPO_ROOT)))
    assert not offenders, (
        "The following files still hardcode crypto_meanrev_2163 (retired profile) "
        "and will render a phantom row on the side-by-side / admin surfaces:\n"
        + "\n".join(f"  - {o}" for o in offenders)
    )
