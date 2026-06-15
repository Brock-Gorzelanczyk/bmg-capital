"""
/api/fund — fund-level endpoints.

GET /api/fund/attention — priority-ranked list of items requiring Brock's decision.
Sources: proposal_audit (pending), stale bot health, candidate pipeline, daily plan.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fund", tags=["fund"])

_BOT_DISPLAY: dict[str, str] = {
    "stock_swing":                 "Stock Swing",
    "stock_day":                   "Stock Day",
    "stock_lt":                    "Stock Long-Term",
    "crypto_swing":                "Crypto Swing",
    "crypto_day":                  "Crypto Day",
    "crypto_lt":                   "Crypto Long-Term",
    "crypto_onchain":              "Crypto Onchain",
    "options_income":              "Equity Income",
    "options_directional":         "Equity Directional",
    "crypto_quant_aggressive":     "Quant Aggressive",
    "crypto_quant_mean_reversion": "Quant Mean Rev",
    "crypto_quant_scalper":        "Quant Scalper",
    "crypto_meanrev_2163":         "Mean Rev 2163",
}


@router.get("/attention")
def get_attention_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a priority-ranked list of items requiring the CIO's attention.
    Severity: red > yellow > gray. Within each band, most recent first.
    """
    items: list[dict] = []

    # ── 1. Pending Tier B proposals ───────────────────────────────────────────
    try:
        rows = db.execute(text("""
            SELECT proposal_id, proposal_type, generated_ts, proposed_change
            FROM proposal_audit
            WHERE decision = 'pending'
            ORDER BY generated_ts DESC
            LIMIT 5
        """)).fetchall()
        for row in rows:
            change: dict = {}
            try:
                change = json.loads(row[3]) if row[3] else {}
            except Exception:
                pass
            bot = change.get("bot", "")
            display_bot = _BOT_DISPLAY.get(bot, bot.replace("_", " ").title()) if bot else "?"
            delta = change.get("delta", 0) or 0
            direction = "Increase" if delta > 0 else "Reduce"
            cur = change.get("current_value", "?")
            prop = change.get("proposed_value", "?")
            ts_raw = row[2]
            ts_str = str(ts_raw)[:16].replace("T", " ") if ts_raw else "?"
            items.append({
                "id": row[0],
                "severity": "red",
                "title": f"{row[0]} — {direction} {display_bot} {cur}% → {prop}%",
                "subtitle": f"Awaiting CIO approval · generated {ts_str} UTC",
                "action": "proposals",
                "link": "/fund",
                "ts": str(ts_raw),
            })
    except Exception as exc:
        logger.debug("[fund/attention] proposals query failed: %s", exc)

    # ── 2. RED risk alerts from risk_sentinel ─────────────────────────────────
    try:
        cutoff_2h = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        risk_rows = db.execute(text("""
            SELECT subject, created_at FROM agent_messages
            WHERE from_agent = 'risk_sentinel'
              AND msg_type IN ('health', 'breach', 'risk_alert')
              AND created_at >= :c
            ORDER BY created_at DESC LIMIT 3
        """), {"c": cutoff_2h}).fetchall()
        for r in risk_rows:
            items.append({
                "id": f"risk_{r[1]}",
                "severity": "red",
                "title": f"Risk Alert — {(r[0] or 'Unnamed alert')[:80]}",
                "subtitle": f"Triggered {str(r[1])[:16].replace('T',' ')} UTC",
                "action": "view",
                "link": "/monitoring",
                "ts": str(r[1]),
            })
    except Exception as exc:
        logger.debug("[fund/attention] risk alert query failed: %s", exc)

    # ── 3. Stale bots ─────────────────────────────────────────────────────────
    try:
        from strategy_lab.agents.strategy_monitor import _check_bot_windows
        bots = _check_bot_windows(db)
        stale = [b for b in bots if b.get("status") == "STALE"]
        for b in stale[:3]:
            minutes = b.get("minutes_since_last", 0) or 0
            hours_h = round(minutes / 60, 1)
            display = _BOT_DISPLAY.get(b["bot"], b["bot"].replace("_", " ").title())
            last = b.get("last_signal", "?")
            last_str = str(last)[:10] if last else "unknown"
            items.append({
                "id": f"stale_{b['bot']}",
                "severity": "yellow",
                "title": f"Stale Bot — {display}",
                "subtitle": f"Silent {hours_h}h · Last signal {last_str}",
                "action": "investigate",
                "link": f"/strategy/{b['bot']}",
                "ts": str(last) if last else "",
            })
    except Exception as exc:
        logger.debug("[fund/attention] stale bots check failed: %s", exc)

    # ── 4. Promotable candidates (shadow paper ≥ 63 days) ────────────────────
    try:
        from app.db.models.pipeline import StrategyCandidate
        from datetime import date as _date
        today = _date.today()
        candidates = db.query(StrategyCandidate).filter(
            StrategyCandidate.state == "SHADOW_PAPER"
        ).all()
        for c in candidates[:3]:
            created = getattr(c, "created_at", None) or getattr(c, "updated_at", None)
            days_in_shadow = (datetime.now(timezone.utc) - created).days if created else 0
            if days_in_shadow >= 63:
                items.append({
                    "id": f"candidate_{c.id}",
                    "severity": "yellow",
                    "title": f"Candidate Ready — {c.name}",
                    "subtitle": f"{days_in_shadow}d in shadow paper · gates may be met",
                    "action": "candidates",
                    "link": f"/candidates/{c.id}",
                    "ts": str(created) if created else "",
                })
    except Exception as exc:
        logger.debug("[fund/attention] candidates query failed: %s", exc)

    # ── 5. Today's daily plan if synthesized ─────────────────────────────────
    try:
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        plan = db.execute(text("""
            SELECT created_at, subject FROM agent_messages
            WHERE channel = 'standup_output' AND created_at >= :c
            ORDER BY created_at DESC LIMIT 1
        """), {"c": cutoff_24h}).fetchone()
        if plan:
            ts_str = str(plan[0])[:16].replace("T", " ")
            items.append({
                "id": "daily_plan",
                "severity": "gray",
                "title": "Daily Plan ready",
                "subtitle": f"Brief synthesized at {ts_str} UTC",
                "action": "view",
                "link": "/morning-brief",
                "ts": str(plan[0]),
            })
    except Exception as exc:
        logger.debug("[fund/attention] standup query failed: %s", exc)

    # Sort: red > yellow > gray, then most recent first
    _sev = {"red": 0, "yellow": 1, "gray": 2}
    items.sort(key=lambda x: (_sev.get(x.get("severity", "gray"), 2), -(len(x.get("ts", "")) or 0)))

    return {"items": items, "count": len(items)}
