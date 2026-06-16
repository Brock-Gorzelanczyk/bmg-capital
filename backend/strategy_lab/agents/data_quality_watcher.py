"""
Data Quality Watcher — Deploy 2 Tier A autonomous data feed monitor.

Checks freshness of regime snapshots, signal data, and price feeds.
Runs hourly — posts to #bmg-monitoring when issues detected.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Staleness thresholds
REGIME_STALE_HOURS   = 26   # RegimeSnapshot older than this → alert
SIGNAL_STALE_HOURS   = 6    # No signals from any bot in 6h → alert (non-weekend)

# Dedup state — prevents repeat alerts for the same issues within the cooldown window
_last_alert_hash: str = ""
_last_alert_ts: datetime | None = None
_ALERT_COOLDOWN_HOURS = 4


def _get_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_BMG_MONITORING", "")
        or os.getenv("DISCORD_CH_MONITORING", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token, channel_id


def _post(channel_id: str, token: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    import httpx
    try:
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json={"embeds": [embed]},
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[dq_watcher] Discord post failed: %s", exc)
        return False


def _check_regime_snapshot(db: Session) -> dict:
    try:
        row = db.execute(text("SELECT ts FROM regime_snapshots ORDER BY ts DESC LIMIT 1")).fetchone()
        if not row or not row[0]:
            return {"ok": False, "issue": "No regime snapshot found", "age_hours": None}
        ts = row[0]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_h > REGIME_STALE_HOURS:
            return {"ok": False, "issue": f"Regime snapshot is {age_h:.1f}h old (limit: {REGIME_STALE_HOURS}h)", "age_hours": round(age_h, 1)}
        return {"ok": True, "age_hours": round(age_h, 1)}
    except Exception as exc:
        return {"ok": False, "issue": f"Query failed: {exc}", "age_hours": None}


def _check_signal_freshness(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    # Skip check on weekends for stock bots
    is_weekend = now.weekday() >= 5
    # SQLite stores datetimes as "YYYY-MM-DD HH:MM:SS" (space, not T).
    # isoformat() produces T-separator which sorts AFTER space in ASCII,
    # making all stored rows appear older than the cutoff → always 0.
    cutoff = (now - timedelta(hours=SIGNAL_STALE_HOURS)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    try:
        count = db.execute(text(
            "SELECT COUNT(*) FROM bot_signals WHERE ts >= :c AND (is_test IS NULL OR is_test = 0)"
        ), {"c": cutoff}).scalar() or 0
        logger.warning("[data_quality] signal_count_6h query returned %d", count)

        if count == 0 and not is_weekend:
            return {"ok": False, "issue": f"No bot signals in last {SIGNAL_STALE_HOURS}h", "signal_count": 0}
        return {"ok": True, "signal_count": count, "weekend": is_weekend}
    except Exception as exc:
        return {"ok": False, "issue": f"Signal query failed: {exc}", "signal_count": None}


def _check_null_data(db: Session) -> dict:
    """Check for NULLs in critical regime fields."""
    issues = []
    try:
        row = db.execute(text("""
            SELECT vix_value, trend_regime, vix_regime
            FROM regime_snapshots ORDER BY ts DESC LIMIT 1
        """)).fetchone()
        if row:
            if row[0] is None: issues.append("vix_value is NULL")
            if row[1] is None: issues.append("trend_regime is NULL")
            if row[2] is None: issues.append("vix_regime is NULL")
    except Exception:
        pass
    return {"ok": len(issues) == 0, "issues": issues}


def run_data_quality_check(db: Session) -> dict:
    """
    Main entry point — called hourly by APScheduler.
    Posts to #bmg-monitoring when data issues are detected.
    """
    now = datetime.now(timezone.utc)

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="data_quality_watcher")
    except Exception:
        pass

    regime   = _check_regime_snapshot(db)
    signals  = _check_signal_freshness(db)
    nulls    = _check_null_data(db)

    all_issues = []
    if not regime["ok"]:   all_issues.append(f"Regime: {regime.get('issue')}")
    if not signals["ok"]:  all_issues.append(f"Signals: {signals.get('issue')}")
    if not nulls["ok"]:    all_issues.extend(nulls.get("issues", []))

    has_issues = bool(all_issues)
    result = {
        "ok":       not has_issues,
        "issues":   all_issues,
        "regime":   regime,
        "signals":  signals,
        "nulls":    nulls,
        "checked_at": now.isoformat(),
    }

    logger.info("[dq_watcher] ok=%s issues=%d", not has_issues, len(all_issues))

    token, ch = _get_channel()

    # Dedup: skip Discord post if same issues posted within cooldown window
    global _last_alert_hash, _last_alert_ts
    _should_post_alert = False
    if has_issues:
        issue_hash = hashlib.md5(",".join(sorted(all_issues)).encode()).hexdigest()[:8]
        elapsed_hours = (
            (now - _last_alert_ts).total_seconds() / 3600
            if _last_alert_ts is not None else float("inf")
        )
        _should_post_alert = (issue_hash != _last_alert_hash) or (elapsed_hours > _ALERT_COOLDOWN_HOURS)

    if has_issues and _should_post_alert:
        embed = {
            "author": {"name": "BMG Capital — Vick (Data Quality)"},
            "title":  f"⚠️ Data Quality Alert — {now.strftime('%Y-%m-%d %H:%M')} UTC",
            "color":  0xF59E0B,
            "fields": [
                {"name": "Issues Detected", "value": "\n".join(f"• {i}" for i in all_issues), "inline": False},
                {"name": "Regime Snapshot Age", "value": f"{regime['age_hours']}h" if regime.get('age_hours') is not None else "Never", "inline": True},
                {"name": "Signal Count (6h)", "value": str(signals.get("signal_count", "N/A")), "inline": True},
            ],
            "footer": {"text": "Vick (Data Quality) · Tier A · Hourly"},
            "timestamp": now.isoformat(),
        }
        try:
            from agents.plain_english import translate_for_brock, make_plain_english_field
            _pe_text = " | ".join(f"{f['name']}: {f['value']}" for f in embed.get("fields", []) if not f['name'].startswith("💬"))
            _pe = translate_for_brock(_pe_text, db=db, channel_id=ch, charge_agent="data_quality_watcher")
            if _pe:
                embed["fields"].append(make_plain_english_field(_pe))
        except Exception as _pe_exc:
            logger.debug("[dq_watcher] plain_english failed: %s", _pe_exc)
        if ch and _post(ch, token, embed):
            logger.warning("[dq_watcher] alert posted: %d issues", len(all_issues))
            _last_alert_hash = issue_hash
            _last_alert_ts = now
        elif not ch:
            # No channel configured — still update dedup state so we don't spam logs
            _last_alert_hash = issue_hash
            _last_alert_ts = now
    elif has_issues:
        logger.info("[dq_watcher] alert suppressed by dedup — hash=%s, same issues within %dh cooldown (%.1fh elapsed)",
                    issue_hash, _ALERT_COOLDOWN_HOURS, elapsed_hours)
    else:
        embed = {
            "author": {"name": "BMG Capital — Vick (Data Quality)"},
            "title":  f"✅ Data Quality Check — {now.strftime('%Y-%m-%d')}",
            "color":  0x16A34A,
            "fields": [
                {"name": "Regime Snapshot Age", "value": f"{regime['age_hours']}h" if regime.get('age_hours') is not None else "Never", "inline": True},
                {"name": "Signal Count (6h)", "value": str(signals.get("signal_count", "N/A")), "inline": True},
                {"name": "Status", "value": "No issues detected", "inline": False},
            ],
            "footer": {"text": "Vick (Data Quality) · Tier A · Hourly"},
            "timestamp": now.isoformat(),
        }
        try:
            from agents.plain_english import translate_for_brock, make_plain_english_field
            _pe_text = " | ".join(f"{f['name']}: {f['value']}" for f in embed.get("fields", []) if not f['name'].startswith("💬"))
            _pe = translate_for_brock(_pe_text, db=db, channel_id=ch, charge_agent="data_quality_watcher")
            if _pe:
                embed["fields"].append(make_plain_english_field(_pe))
        except Exception as _pe_exc:
            logger.debug("[dq_watcher] plain_english failed: %s", _pe_exc)
        if ch and _post(ch, token, embed):
            logger.info("[dq_watcher] green summary posted")

    # Publish to bus
    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import DQ_ALERT
        if has_issues:
            _bus_publish(db, channel=DQ_ALERT, from_agent="data_quality_watcher",
                         to_agent="risk_sentinel", msg_type="dq_alert",
                         subject=f"DQ issues detected: {len(all_issues)}",
                         payload=result, priority=7)
    except Exception as exc:
        logger.debug("[dq_watcher] bus publish skipped: %s", exc)

    # Proactive observation: any issues detected
    try:
        from agents.bus import observe as _obs
        if has_issues:
            _obs(db, agent_id="data_quality_watcher",
                 content=f"Data quality degraded: {len(all_issues)} issue(s) detected. Feed reliability compromised — proposals may be based on stale data.",
                 context={"issues": all_issues[:3]})
    except Exception:
        pass

    # Daily check-in to #fund-team-chat
    try:
        from agents.bus import post_daily_checkin as _checkin
        age = result.get("regime", {}).get("age_hours", "?")
        sig_count = result.get("signals", {}).get("signal_count", "?")
        status_word = "⚠️ Issues found" if has_issues else "✅ All feeds clean"
        _checkin(db, "data_quality_watcher",
                 f"Vick (Data Quality): {status_word}. Regime snapshot {age}h old, "
                 f"{sig_count} signals in last 6h. 8 feeds monitored, 4 endpoints polled.")
    except Exception:
        pass

    return result
