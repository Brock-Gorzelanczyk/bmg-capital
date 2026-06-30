"""BMG vault sync — Mac-side polling that mirrors DB journals + audits to vault filesystem.

Polls the backend admin endpoints every N seconds, writes:
  - per-bot daily journals    → vault/context/strategy-journal/<bot>/<YYYY-MM-DD>.md
  - per-bot rolling 30d        → vault/context/strategy-journal/<bot>/_rolling_30d.md
  - daily audit summaries      → vault/context/daily-audits/<YYYY-MM-DD>.md

Runs as a launchd job at /Users/brockgorzelanczyk/Library/LaunchAgents/com.bmg.vault-sync.plist.
Idempotent: writes overwrite-in-place if content unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

API = os.environ.get("BMG_API_BASE", "https://disciplined-intuition-production-5207.up.railway.app")
TOKEN = os.environ.get("BMG_USER_TOKEN", "")
VAULT_ROOT = Path(os.environ.get("BMG_VAULT_ROOT", "/Users/brockgorzelanczyk/Documents/BMG-Capital-Vault"))
POLL_INTERVAL = int(os.environ.get("VAULT_SYNC_INTERVAL_SECONDS", "300"))  # 5 min default

# Canonical 13 bots — match bot_profiles.name in DB
BOT_NAMES = [
    "crypto_quant_aggressive", "crypto_quant_mean_reversion", "crypto_quant_scalper",
    "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
    "stock_swing", "stock_day", "stock_lt",
    "options_income", "options_directional",
    "cash_floor",
]


def fetch(path: str, *, accept_404: bool = False) -> dict | None:
    """GET request; returns parsed JSON, or None on 404 (when accept_404=True), or raises."""
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "User-Agent": "bmg-vault-sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and accept_404:
            return None
        sys.stderr.write(f"[vault-sync] {path} -> HTTP {exc.code}\n")
        return None
    except Exception as exc:
        sys.stderr.write(f"[vault-sync] {path} -> {type(exc).__name__}: {exc}\n")
        return None


def write_if_changed(dest: Path, content: str) -> bool:
    """Write content to dest; return True if file was created or changed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            if dest.read_text() == content:
                return False
        except Exception:
            pass
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(content)
    tmp.rename(dest)
    return True


def sync_strategy_journals() -> dict:
    """Pull per-bot latest journal + rolling-30d from backend; write to vault."""
    written = []
    for bot in BOT_NAMES:
        # Latest journal entry
        data = fetch(f"/api/admin/strategy-journal/{bot}", accept_404=True)
        if data and isinstance(data, dict):
            journal_date = data.get("journal_date") or data.get("date")
            body_md = data.get("body_markdown") or ""
            frontmatter = data.get("frontmatter") or {}
            if journal_date and body_md:
                fm_yaml = _dict_to_yaml_frontmatter(frontmatter)
                content = f"{fm_yaml}\n{body_md}\n"
                dest = VAULT_ROOT / "context" / "strategy-journal" / bot / f"{journal_date}.md"
                if write_if_changed(dest, content):
                    written.append(str(dest.relative_to(VAULT_ROOT)))

        # Rolling 30d summary
        rolling = fetch(f"/api/admin/strategy-journal/{bot}/rolling/30d", accept_404=True)
        if rolling and isinstance(rolling, dict):
            content = _rolling_summary_md(bot, rolling)
            dest = VAULT_ROOT / "context" / "strategy-journal" / bot / "_rolling_30d.md"
            if write_if_changed(dest, content):
                written.append(str(dest.relative_to(VAULT_ROOT)))
    return {"strategy_journal_files_written": len(written), "paths": written[:10]}


def sync_daily_audits() -> dict:
    """Pull latest daily audit; write to vault."""
    data = fetch("/api/admin/daily-audit/latest", accept_404=True)
    if not data:
        return {"daily_audit_files_written": 0}

    run_at = data.get("run_at") or data.get("as_of") or ""
    date_str = run_at[:10] if run_at else time.strftime("%Y-%m-%d")
    summary_md = data.get("summary_markdown") or data.get("summary") or ""
    overall = data.get("overall_status") or "UNKNOWN"
    checks = data.get("checks") or []
    alerts = data.get("alerts") or []

    body = f"""---
date: {date_str}
overall_status: {overall}
alerts_count: {len(alerts)}
---

# BMG Strategy Lab Daily Audit — {date_str}

**Status:** {overall}

{summary_md if summary_md else _render_checks(checks, alerts)}
"""
    dest = VAULT_ROOT / "context" / "daily-audits" / f"{date_str}.md"
    written = write_if_changed(dest, body)
    return {"daily_audit_files_written": 1 if written else 0, "path": str(dest.relative_to(VAULT_ROOT))}


def _render_checks(checks: list, alerts: list) -> str:
    """Fallback renderer if summary_markdown is empty."""
    lines = []
    for c in checks:
        emoji = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "❌"}.get(c.get("status", ""), "•")
        lines.append(f"- {emoji} **{c.get('name', '?')}**: {c.get('details', '')}")
    if alerts:
        lines.append("\n## Alerts\n")
        for a in alerts:
            lines.append(f"- 🚨 {a}")
    return "\n".join(lines)


def _rolling_summary_md(bot: str, data: dict) -> str:
    """Render rolling 30d aggregate as Markdown."""
    return f"""---
bot_id: {bot}
window: 30d
generated_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
total_pnl_cents: {data.get('total_pnl_cents', 0)}
total_trades: {data.get('total_trades', 0)}
win_rate: {data.get('win_rate', 0)}
rolling_sharpe: {data.get('rolling_sharpe', 0)}
journals_count: {data.get('journals_count', 0)}
---

# {bot} — rolling 30d

- **Total P&L:** ${data.get('total_pnl_cents', 0) / 100:,.2f}
- **Total trades:** {data.get('total_trades', 0)}
- **Win rate:** {(data.get('win_rate', 0) or 0) * 100:.1f}%
- **Rolling Sharpe:** {data.get('rolling_sharpe', 0):.2f}
- **Best strategy 30d:** {data.get('best_strategy_30d') or 'n/a'}
- **Worst strategy 30d:** {data.get('worst_strategy_30d') or 'n/a'}
- **Journals aggregated:** {data.get('journals_count', 0)}
"""


def _dict_to_yaml_frontmatter(d: dict) -> str:
    """Render dict as YAML frontmatter (simple, deterministic, no library dep)."""
    lines = ["---"]
    for k in sorted(d.keys()):
        v = d[k]
        if isinstance(v, (dict, list)):
            lines.append(f"{k}: {json.dumps(v)}")
        elif v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def main() -> int:
    if not TOKEN:
        sys.stderr.write("[vault-sync] BMG_USER_TOKEN env required\n")
        return 1
    if not VAULT_ROOT.exists():
        sys.stderr.write(f"[vault-sync] Vault root does not exist: {VAULT_ROOT}\n")
        return 1

    sys.stderr.write(
        f"[vault-sync] starting — api={API[:60]} vault={VAULT_ROOT} interval={POLL_INTERVAL}s\n"
    )

    while True:
        try:
            j = sync_strategy_journals()
            a = sync_daily_audits()
            if j["strategy_journal_files_written"] > 0 or a["daily_audit_files_written"] > 0:
                sys.stderr.write(
                    f"[vault-sync] synced: journals={j['strategy_journal_files_written']} "
                    f"audit={a['daily_audit_files_written']}\n"
                )
        except Exception as exc:
            sys.stderr.write(f"[vault-sync] cycle error: {type(exc).__name__}: {exc}\n")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
