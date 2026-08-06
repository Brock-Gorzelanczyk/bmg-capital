"""Price alert monitor — checks all armed alerts against live prices.

Called by the scheduler:
  - Every 1 min Mon-Fri 9:30–16:00 ET  (stock market hours)
  - Every 5 min 24/7                   (crypto)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_ALERT_COLOR = 0xFBBF24  # amber


def run_price_alert_monitor(db) -> None:
    from app.db.models.price_alert import PriceAlert
    from app.db.models.workshop import WorkshopChart
    from app.services.live_prices import fetch_live_prices

    armed = db.query(PriceAlert).filter_by(status="armed").all()
    if not armed:
        return

    tickers = list({a.ticker for a in armed})
    try:
        prices = fetch_live_prices(tickers)
    except Exception as exc:
        logger.warning("[price-monitor] price fetch failed: %s", exc)
        return

    triggered_items: list[dict] = []
    for alert in armed:
        price = prices.get(alert.ticker)
        if price is None:
            continue
        alert_price = alert.price_cents / 100
        hit = (
            (alert.direction == "above" and price >= alert_price) or
            (alert.direction == "below" and price <= alert_price)
        )
        if not hit:
            continue

        alert.status = "triggered"
        alert.triggered_at = datetime.now(timezone.utc)
        db.commit()

        chart_name: Optional[str] = None
        if alert.workshop_chart_id:
            chart = db.query(WorkshopChart).filter_by(id=alert.workshop_chart_id).first()
            if chart:
                chart_name = chart.name

        triggered_items.append({
            "alert": alert,
            "current_price": price,
            "chart_name": chart_name,
        })

    for item in triggered_items:
        if item["alert"].notif_discord:
            _post_discord(item["alert"], item["current_price"], item["chart_name"])

    if triggered_items:
        logger.info(
            "[price-monitor] triggered %d alert(s): %s",
            len(triggered_items),
            [f"{i['alert'].ticker}@{i['alert'].price_cents / 100:.2f}" for i in triggered_items],
        )


def _post_discord(alert, current_price: float, chart_name: Optional[str]) -> None:
    import os
    if os.getenv("NOTIFICATIONS_DISCORD_ENABLED", "false").strip().lower() != "true":
        return
    from app.config import settings
    from app.services.discord_public import _post_to_channel

    channel_id = settings.discord_ch_price_alerts
    if not channel_id or not settings.discord_bot_token:
        logger.debug("[price-monitor] Discord not configured — skipping embed")
        return

    direction_word = "ABOVE" if alert.direction == "above" else "BELOW"
    arrow = "↑" if alert.direction == "above" else "↓"
    alert_price_fmt = f"${alert.price_cents / 100:.2f}"
    current_price_fmt = f"${current_price:.2f} ({arrow})"

    fields = [
        {"name": "Alert Price", "value": alert_price_fmt, "inline": True},
        {"name": "Current Price", "value": current_price_fmt, "inline": True},
        {"name": "Direction", "value": direction_word, "inline": True},
    ]
    if alert.message:
        fields.append({"name": "Your Note", "value": alert.message, "inline": False})
    if chart_name:
        fields.append({"name": "Workshop Chart", "value": chart_name, "inline": False})

    embed = {
        "title": f"🔔 PRICE ALERT — {alert.ticker} crossed {direction_word} {alert_price_fmt}",
        "color": _ALERT_COLOR,
        "fields": fields,
        "footer": {"text": "BMG Capital Workshop · Price Alerts"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _post_to_channel(channel_id, embed, settings.discord_bot_token)
    except Exception as exc:
        logger.warning("[price-monitor] discord post failed for alert %d: %s", alert.id, exc)
