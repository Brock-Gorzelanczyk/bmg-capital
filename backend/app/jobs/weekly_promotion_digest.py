"""Weekly promotion digest — runs every Monday at 9 AM ET.

Queries recent tier transitions and posts a rich embed to #sentinel-ops
summarising which bots were promoted or demoted in the past 7 days.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from app.db.session import SessionLocal
from app.db.models.bots import BotAllocation, BotProfile
from app.db.models.allocation import BotTierHistory

logger = logging.getLogger(__name__)

_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing": "Stock Swing",
    "stock_day": "Stock Day",
    "stock_lt": "Stock Long-Term",
    "crypto_swing": "Crypto Swing",
    "crypto_day": "Crypto Day",
    "crypto_lt": "Crypto Long-Term",
    "crypto_onchain": "Crypto On-Chain",
    "crypto_quant_aggressive": "Quant Aggressive",
    "options_flow": "Options Flow",
    "stock_momentum": "Stock Momentum",
    "stock_breakout": "Stock Breakout",
    "stock_mean_reversion": "Stock Mean Rev",
}

_TIER_EMOJI: dict[str, str] = {
    "T3": "🟢",
    "T2": "🔵",
    "T1": "🟡",
    "T0": "⚫",
}


def _post_embed(embed: dict) -> bool:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel = os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")
    if not token or not channel:
        logger.warning("[weekly_digest] Discord env vars missing — skipping post")
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"embeds": [embed]},
            )
        if resp.is_success:
            return True
        logger.warning("[weekly_digest] Discord post failed: %s %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.error("[weekly_digest] Discord post error: %s", exc)
        return False


def run() -> dict:
    """Entry point called by scheduler."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)

        recent_changes = (
            db.query(BotTierHistory)
            .filter(BotTierHistory.changed_at >= cutoff)
            .order_by(BotTierHistory.changed_at.desc())
            .all()
        )

        if not recent_changes:
            logger.info("[weekly_digest] No tier changes in past 7 days — skipping digest")
            return {"changes": 0}

        alloc_ids = list({c.allocation_id for c in recent_changes})
        allocs = db.query(BotAllocation).filter(BotAllocation.id.in_(alloc_ids)).all()
        alloc_map: dict[int, BotAllocation] = {a.id: a for a in allocs}
        profile_ids = list({a.profile_id for a in allocs})
        profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
        profile_map: dict[int, BotProfile] = {p.id: p for p in profiles}

        promotions = [c for c in recent_changes if (c.new_tier or "") > (c.previous_tier or "")]
        demotions = [c for c in recent_changes if (c.new_tier or "") < (c.previous_tier or "")]

        fields = []
        if promotions:
            lines = []
            for c in promotions:
                alloc = alloc_map.get(c.allocation_id)
                profile = profile_map.get(alloc.profile_id) if alloc else None
                name = _DISPLAY_NAMES.get(profile.name, profile.name if profile else "Unknown")
                emoji_old = _TIER_EMOJI.get(c.previous_tier or "T1", "")
                emoji_new = _TIER_EMOJI.get(c.new_tier, "")
                lines.append(
                    f"{emoji_old} {c.previous_tier} → {emoji_new} {c.new_tier} | "
                    f"**{name}** | "
                    f"30d: {c.return_30d_pct_at_change:.1f}% | "
                    f"WR: {(c.win_rate_at_change or 0)*100:.0f}%"
                )
            fields.append({
                "name": f"📈 Promotions ({len(promotions)})",
                "value": "\n".join(lines) or "—",
                "inline": False,
            })

        if demotions:
            lines = []
            for c in demotions:
                alloc = alloc_map.get(c.allocation_id)
                profile = profile_map.get(alloc.profile_id) if alloc else None
                name = _DISPLAY_NAMES.get(profile.name, profile.name if profile else "Unknown")
                emoji_old = _TIER_EMOJI.get(c.previous_tier or "T2", "")
                emoji_new = _TIER_EMOJI.get(c.new_tier, "")
                lines.append(
                    f"{emoji_old} {c.previous_tier} → {emoji_new} {c.new_tier} | "
                    f"**{name}** | "
                    f"30d: {c.return_30d_pct_at_change:.1f}% | "
                    f"DD: {(c.max_drawdown_at_change or 0)*100:.1f}%"
                )
            fields.append({
                "name": f"📉 Demotions ({len(demotions)})",
                "value": "\n".join(lines) or "—",
                "inline": False,
            })

        embed = {
            "title": "📊 Weekly Allocation Tier Digest",
            "description": (
                f"{len(recent_changes)} tier change(s) in the past 7 days — "
                f"{len(promotions)} promotion(s), {len(demotions)} demotion(s)"
            ),
            "color": 0x5865F2,
            "fields": fields,
            "footer": {"text": "BMG Capital — Allocation Engine"},
            "timestamp": now.isoformat(),
        }

        _post_embed(embed)
        logger.info("[weekly_digest] Posted digest: %d changes", len(recent_changes))
        return {"changes": len(recent_changes), "promotions": len(promotions), "demotions": len(demotions)}
    except Exception as exc:
        logger.error("[weekly_digest] job failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        db.close()
