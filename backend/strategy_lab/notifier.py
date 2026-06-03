"""
Notification dispatcher. Called by various modules when events occur.
Routes to email (Resend) in paper phase.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ALWAYS_ON = {"anomaly", "health_alert", "pending_review_gt5"}

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://bmgcapital.app")


def notify(
    user_id: int,
    user_email: str,
    notification_type: str,  # anomaly | health_alert | per_trade_fill | daily_summary
    subject: str,
    body: str,
    bot_name: str | None = None,
    deep_link: str | None = None,
) -> None:
    """Dispatch notification. Currently email-only via Resend."""
    resend_key = os.getenv("RESEND_API_KEY")
    if not resend_key:
        logger.info(
            "[notify] %s → %s: %s (RESEND_API_KEY not configured)",
            notification_type,
            user_email,
            subject,
        )
        return

    try:
        import resend

        resend.api_key = resend_key

        bot_badge = (
            f'<span style="background:#0f172a;color:#fff;padding:2px 8px;border-radius:4px;'
            f'font-size:12px;font-weight:600">{bot_name}</span> '
            if bot_name
            else ""
        )

        cta_html = ""
        if deep_link:
            cta_html = (
                f'<p style="margin-top:20px">'
                f'<a href="{deep_link}" style="display:inline-block;padding:10px 20px;'
                f'background:#0f172a;color:#ffffff;text-decoration:none;border-radius:8px;'
                f'font-size:14px;font-weight:600">Open Command Center</a></p>'
            )

        type_color: dict[str, str] = {
            "anomaly": "#dc2626",
            "health_alert": "#d97706",
            "pending_review_gt5": "#7c3aed",
            "per_trade_fill": "#0369a1",
            "daily_summary": "#0f172a",
        }
        accent = type_color.get(notification_type, "#0f172a")

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <div style="max-width:600px;margin:24px auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)">
    <div style="background:{accent};padding:16px 24px">
      <p style="margin:0;color:#ffffff;font-size:11px;letter-spacing:.08em;text-transform:uppercase">{notification_type.replace("_", " ")}</p>
      <h2 style="margin:4px 0 0;color:#ffffff;font-size:18px">{subject}</h2>
    </div>
    <div style="padding:24px">
      {bot_badge}
      <p style="margin:8px 0 0;font-size:15px;color:#374151;line-height:1.6">{body}</p>
      {cta_html}
    </div>
    <div style="padding:12px 24px;background:#f8fafc;border-top:1px solid #e2e8f0">
      <p style="margin:0;font-size:12px;color:#94a3b8">
        BMG Capital Strategy Lab &bull;
        <a href="{FRONTEND_URL}/settings/notifications" style="color:#94a3b8">Manage preferences</a>
      </p>
    </div>
  </div>
</body>
</html>"""

        resend.Emails.send(
            {
                "from": "BMG Capital <alerts@bmgcapital.app>",
                "to": [user_email],
                "subject": f"[BMG] {subject}",
                "html": html,
            }
        )
        logger.info("[notify] %s → %s sent: %s", notification_type, user_email, subject)
    except Exception as e:
        logger.error("[notify] Failed: %s", e)
