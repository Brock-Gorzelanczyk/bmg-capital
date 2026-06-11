"""Portfolio drawdown circuit breaker — runs every 5 min during market hours.

Reads portfolio_equity_snapshots to compute peak-to-trough drawdown.
Halts trading at 10% drawdown; warns at 7%; auto-reopens when DD < 3%.
"""
from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.services.trading_gate import TradingGate

logger = logging.getLogger(__name__)

THRESHOLDS = {
    "halt_drawdown_pct": 0.10,
    "warning_drawdown_pct": 0.07,
    "auto_reopen_recovery_pct": 0.03,
}


def _post_warning(drawdown_pct: float) -> None:
    try:
        import os
        import httpx
        token = os.getenv("DISCORD_BOT_TOKEN", "")
        channel = os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")
        if not token or not channel:
            return
        url = f"https://discord.com/api/v10/channels/{channel}/messages"
        with httpx.Client(timeout=8) as client:
            client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"embeds": [{
                    "title": "⚠️ Drawdown Warning",
                    "description": f"Portfolio drawdown reached **{drawdown_pct:.1%}**. "
                                   f"Halt threshold: {THRESHOLDS['halt_drawdown_pct']:.0%}.",
                    "color": 0xFFA500,
                }]},
            )
    except Exception as exc:
        logger.warning("[drawdown_breaker] Discord warning failed: %s", exc)


def check() -> dict:
    db = SessionLocal()
    try:
        from sqlalchemy import text

        peak_row = db.execute(text(
            "SELECT MAX(equity_usd) FROM portfolio_equity_snapshots "
            "WHERE snapshot_at > datetime('now', '-30 days')"
        )).fetchone()

        latest_row = db.execute(text(
            "SELECT equity_usd FROM portfolio_equity_snapshots "
            "ORDER BY id DESC LIMIT 1"
        )).fetchone()

        if not peak_row or peak_row[0] is None or not latest_row:
            return {"status": "no_data"}

        peak_equity = float(peak_row[0])
        current_equity = float(latest_row[0])

        if peak_equity <= 0:
            return {"status": "no_data"}

        drawdown_pct = (peak_equity - current_equity) / peak_equity

        if drawdown_pct >= THRESHOLDS["halt_drawdown_pct"]:
            if TradingGate.is_open():
                TradingGate.halt(
                    reason=(
                        f"Portfolio drawdown {drawdown_pct:.1%} exceeded "
                        f"{THRESHOLDS['halt_drawdown_pct']:.0%} threshold"
                    ),
                    halted_by="circuit_breaker",
                )
            return {"status": "halted", "drawdown_pct": drawdown_pct}

        if drawdown_pct >= THRESHOLDS["warning_drawdown_pct"]:
            _post_warning(drawdown_pct)
            return {"status": "warning", "drawdown_pct": drawdown_pct}

        if drawdown_pct <= THRESHOLDS["auto_reopen_recovery_pct"]:
            last_row = db.execute(text(
                "SELECT halted_by FROM trading_gate_state ORDER BY id DESC LIMIT 1"
            )).fetchone()
            if last_row and last_row[0] == "circuit_breaker":
                gate_row = db.execute(text(
                    "SELECT is_open FROM trading_gate_state ORDER BY id DESC LIMIT 1"
                )).fetchone()
                if gate_row and gate_row[0] == 0:
                    TradingGate.reopen(reopened_by="circuit_breaker_recovery")
                    return {"status": "auto_reopened", "drawdown_pct": drawdown_pct}

        return {"status": "ok", "drawdown_pct": drawdown_pct}

    except Exception as exc:
        logger.warning("[drawdown_breaker] check failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        db.close()
