"""journal_writer.py — render and persist per-bot daily journal entries.

Phase 1: template-generated body only. No LLM. No filesystem writes.
Writes go to bot_daily_journals table exclusively.

vault_path_for() returns the FUTURE Mac-side path for Phase 1b sync — it
does NOT write to disk from here (Railway cannot reach ~/Documents/).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Sleeve inference ────────────────────────────────────────────────────────

_BOT_SLEEVE_MAP: dict[str, str] = {
    "crypto_quant_scalper":       "quant",
    "crypto_quant_aggressive":    "quant",
    "crypto_quant_mean_reversion": "quant",
    "crypto_meanrev_2163":        "quant",
    "crypto_day":                 "crypto",
    "crypto_swing":               "crypto",
    "crypto_lt":                  "crypto",
    "crypto_onchain":             "crypto",
    "stock_day":                  "stocks",
    "stock_swing":                "stocks",
    "stock_lt":                   "stocks",
    "options_directional":        "options",
    "options_income":             "options",
    "cash_floor":                 "cash_floor",
}


def infer_sleeve(bot_id: str, config_json: Optional[dict] = None) -> str:
    """Return sleeve string for bot_id.

    Priority: config_json.get('sleeve') > _BOT_SLEEVE_MAP > infer from name.
    """
    if config_json and isinstance(config_json, dict):
        sleeve = config_json.get("sleeve")
        if sleeve:
            return str(sleeve)
    if bot_id in _BOT_SLEEVE_MAP:
        return _BOT_SLEEVE_MAP[bot_id]
    # Fallback: infer from name fragments
    if "options" in bot_id:
        return "options"
    if "crypto" in bot_id or "btc" in bot_id:
        return "crypto"
    if "stock" in bot_id or "equity" in bot_id:
        return "stocks"
    if "cash" in bot_id:
        return "cash_floor"
    return "unknown"


# ── Frontmatter renderer ────────────────────────────────────────────────────

# EXACT key order from Brock spec — do NOT reorder.
_FRONTMATTER_KEY_ORDER = [
    "bot_id",
    "date",
    "sleeve",
    "asset_class",
    "starting_capital_cents",
    "ending_pv_cents",
    "day_pnl_cents",
    "day_return_pct",
    "trades_count",
    "winning_trades",
    "losing_trades",
    "win_rate",
    "avg_winner_cents",
    "avg_loser_cents",
    "profit_factor",
    "avg_hold_minutes",
    "max_concurrent_positions",
    "end_of_day_positions",
    "end_of_day_deployed_cents",
    "deployment_pct_avg",
    "regime_when_active",         # nested dict: {vix_band, trend, btc_dom_band}
    "strategies_breakdown",       # nested dict per strategy
    "errors_24h",
    "sentry_issues_24h",
]


def _yaml_scalar(v) -> str:
    """Serialize a single scalar value to YAML-compatible string."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v != v:   # NaN
            return "null"
        return f"{v:.6g}"
    return str(v)


def render_frontmatter(data: dict) -> str:
    """Serialize data dict to YAML frontmatter (--- ... ---).

    Key order matches _FRONTMATTER_KEY_ORDER verbatim (Brock spec).
    No PyYAML — hand-built to preserve order and avoid library version quirks.
    """
    lines: list[str] = ["---"]

    for key in _FRONTMATTER_KEY_ORDER:
        if key not in data:
            continue
        val = data[key]

        if key == "regime_when_active" and isinstance(val, dict):
            lines.append(f"{key}:")
            for subkey in ("vix_band", "trend", "btc_dom_band"):
                subval = val.get(subkey, "UNKNOWN")
                lines.append(f"  {subkey}: {_yaml_scalar(subval)}")

        elif key == "strategies_breakdown" and isinstance(val, dict):
            if not val:
                lines.append(f"{key}: {{}}")
            else:
                lines.append(f"{key}:")
                for strat_name, strat_data in val.items():
                    # Sanitize strategy name for YAML key (replace spaces with underscores)
                    safe_name = str(strat_name).replace(" ", "_").replace(":", "_")
                    lines.append(f"  {safe_name}:")
                    if isinstance(strat_data, dict):
                        for sk, sv in strat_data.items():
                            lines.append(f"    {sk}: {_yaml_scalar(sv)}")
                    else:
                        lines.append(f"    value: {_yaml_scalar(strat_data)}")

        elif key == "sentry_issues_24h":
            if isinstance(val, list) and not val:
                lines.append(f"{key}: []")
            elif isinstance(val, list):
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {_yaml_scalar(item)}")
            else:
                lines.append(f"{key}: {_yaml_scalar(val)}")

        else:
            lines.append(f"{key}: {_yaml_scalar(val)}")

    lines.append("---")
    return "\n".join(lines)


# ── Body renderer ───────────────────────────────────────────────────────────

def render_body(data: dict) -> str:
    """Template-generated Markdown body. No LLM. No prose generation.

    Sections:
      ## Day Summary
      ## Top Strategy
      ## Worst Strategy
      ## Notes for CIO
    """
    bot_id = data.get("bot_id", "unknown")
    journal_date = data.get("date", "unknown")
    trades_count = data.get("trades_count", 0)
    day_pnl_cents = data.get("day_pnl_cents", 0)
    win_rate = data.get("win_rate")
    strategies_breakdown = data.get("strategies_breakdown") or {}
    deployment_pct_avg = data.get("deployment_pct_avg")
    end_of_day_positions = data.get("end_of_day_positions", 0)

    # Format P&L
    pnl_sign = "+" if day_pnl_cents >= 0 else ""
    pnl_dollars = day_pnl_cents / 100.0
    pnl_str = f"{pnl_sign}${pnl_dollars:,.2f}"

    lines: list[str] = []

    # ── Day Summary ──────────────────────────────────────────────────────────
    lines.append("## Day Summary")
    lines.append("")
    if trades_count == 0:
        lines.append(f"Bot **{bot_id}** had no trades on {journal_date}.")
    else:
        lines.append(
            f"Bot **{bot_id}** traded **{trades_count}** time(s) on {journal_date} "
            f"for a realized P&L of **{pnl_str}**."
        )
    lines.append("")
    if win_rate is not None:
        lines.append(f"Win rate: **{win_rate * 100:.1f}%**  |  EOD open positions: **{end_of_day_positions}**")
    else:
        lines.append(f"Win rate: N/A (no closed positions)  |  EOD open positions: **{end_of_day_positions}**")
    lines.append("")
    lines.append("_(unrealized delta excluded — Phase 2)_")
    lines.append("")

    # ── Top Strategy ─────────────────────────────────────────────────────────
    lines.append("## Top Strategy")
    lines.append("")
    if strategies_breakdown:
        best_strat = max(strategies_breakdown.items(), key=lambda kv: kv[1].get("pnl_cents", 0))
        strat_name, strat_data = best_strat
        strat_pnl = strat_data.get("pnl_cents", 0)
        strat_trades = strat_data.get("trades", 0)
        strat_pnl_sign = "+" if strat_pnl >= 0 else ""
        strat_pnl_str = f"{strat_pnl_sign}${strat_pnl / 100.0:,.2f}"
        lines.append(f"**{strat_name}** — {strat_trades} trade(s), P&L: {strat_pnl_str}")
    else:
        lines.append("No strategy data available for this day.")
    lines.append("")

    # ── Worst Strategy ───────────────────────────────────────────────────────
    lines.append("## Worst Strategy")
    lines.append("")
    if strategies_breakdown:
        worst_strat = min(strategies_breakdown.items(), key=lambda kv: kv[1].get("pnl_cents", 0))
        wstrat_name, wstrat_data = worst_strat
        wstrat_pnl = wstrat_data.get("pnl_cents", 0)
        wstrat_trades = wstrat_data.get("trades", 0)
        wstrat_sign = "+" if wstrat_pnl >= 0 else ""
        wstrat_pnl_str = f"{wstrat_sign}${wstrat_pnl / 100.0:,.2f}"
        lines.append(f"**{wstrat_name}** — {wstrat_trades} trade(s), P&L: {wstrat_pnl_str}")
        lines.append("")
        lines.append(
            f"_HYPOTHESIS: {wstrat_name} may be underperforming due to regime mismatch "
            f"or insufficient signal confidence. Review threshold settings._"
        )
    else:
        lines.append("No strategy data available for this day.")
    lines.append("")

    # ── Notes for CIO ────────────────────────────────────────────────────────
    lines.append("## Notes for CIO")
    lines.append("")
    notes: list[str] = []

    if trades_count == 0:
        notes.append("No trades executed on this day — bot may be in cooldown or no signals fired.")
    if deployment_pct_avg is not None and deployment_pct_avg < 0.10:
        notes.append(
            f"Deployment was low ({deployment_pct_avg * 100:.1f}% avg) — "
            f"consider reviewing signal thresholds."
        )
    if end_of_day_positions > 0:
        notes.append(
            f"{end_of_day_positions} position(s) carried into next session — monitor overnight risk."
        )
    if win_rate is not None and win_rate < 0.40:
        notes.append(
            f"Win rate ({win_rate * 100:.1f}%) below 40% — review trade quality and regime alignment."
        )
    notes.append("(error tracking not yet wired — Phase 2)")
    notes.append("(Sentry issues not yet wired — Phase 2)")
    notes.append("(ending_pv_cents is an approximation: starting_capital + day_pnl — Phase 2 wires true EOD NAV)")

    for note in notes:
        lines.append(f"- {note}")
    lines.append("")

    return "\n".join(lines)


# ── Vault path helper ────────────────────────────────────────────────────────

def vault_path_for(bot_id: str, journal_date: date) -> str:
    """Return the FUTURE Mac-side vault path for this journal entry.

    Does NOT write to disk in Phase 1. Used by the API response so the
    Mac-side Phase 1b sync script knows where to write the .md file.
    """
    date_str = journal_date.isoformat() if hasattr(journal_date, "isoformat") else str(journal_date)
    return f"~/Documents/BMG-Capital-Vault/context/strategy-journal/{bot_id}/{date_str}.md"


# ── DB writer ────────────────────────────────────────────────────────────────

def write_journal_row(db: Session, data: dict) -> int:
    """UPSERT a journal row into bot_daily_journals.

    Renders frontmatter YAML and Markdown body from data, then stores
    all fields in the row. Returns the row id.

    Idempotent: calling twice for the same (allocation_id, journal_date)
    overwrites — the UNIQUE constraint on (allocation_id, journal_date)
    is honoured by the INSERT OR REPLACE logic.
    """
    from app.db.models.bot_daily_journal import BotDailyJournal
    from sqlalchemy import and_

    # Render derived fields
    fm_data = dict(data)
    # Ensure 'date' key for frontmatter (may be journal_date)
    if "date" not in fm_data and "journal_date" in fm_data:
        fm_data["date"] = fm_data["journal_date"]
    # Ensure regime_when_active nested dict
    if "regime_when_active" not in fm_data:
        fm_data["regime_when_active"] = {
            "vix_band": data.get("regime_vix_band", "UNKNOWN"),
            "trend": data.get("regime_trend", "UNKNOWN"),
            "btc_dom_band": data.get("regime_btc_dom_band", "UNKNOWN"),
        }
    # Ensure strategies_breakdown key
    if "strategies_breakdown" not in fm_data:
        breakdown_raw = data.get("strategies_breakdown_json") or "{}"
        try:
            fm_data["strategies_breakdown"] = json.loads(breakdown_raw)
        except (json.JSONDecodeError, TypeError):
            fm_data["strategies_breakdown"] = {}

    frontmatter_yaml = render_frontmatter(fm_data)
    body_md = render_body(fm_data)

    allocation_id = data["allocation_id"]
    journal_date = data["journal_date"]

    # Try to find existing row
    existing = (
        db.query(BotDailyJournal)
        .filter(
            and_(
                BotDailyJournal.allocation_id == allocation_id,
                BotDailyJournal.journal_date == journal_date,
            )
        )
        .first()
    )

    breakdown_json = data.get("strategies_breakdown_json")
    if breakdown_json is None:
        breakdown = data.get("strategies_breakdown") or {}
        breakdown_json = json.dumps(breakdown)

    sentry_json = json.dumps(data.get("sentry_issues_24h") or [])

    kwargs = dict(
        allocation_id=allocation_id,
        bot_id=data["bot_id"],
        user_id=data.get("user_id", 1),
        journal_date=journal_date,
        sleeve=data.get("sleeve"),
        asset_class=data.get("asset_class"),
        starting_capital_cents=int(data.get("starting_capital_cents", 0)),
        ending_pv_cents=int(data.get("ending_pv_cents", 0)),
        day_pnl_cents=int(data.get("day_pnl_cents", 0)),
        day_return_pct=float(data.get("day_return_pct", 0.0)),
        trades_count=int(data.get("trades_count", 0)),
        winning_trades=int(data.get("winning_trades", 0)),
        losing_trades=int(data.get("losing_trades", 0)),
        win_rate=data.get("win_rate"),
        avg_winner_cents=data.get("avg_winner_cents"),
        avg_loser_cents=data.get("avg_loser_cents"),
        profit_factor=data.get("profit_factor"),
        avg_hold_minutes=data.get("avg_hold_minutes"),
        max_concurrent_positions=int(data.get("max_concurrent_positions", 0)),
        end_of_day_positions=int(data.get("end_of_day_positions", 0)),
        end_of_day_deployed_cents=int(data.get("end_of_day_deployed_cents", 0)),
        deployment_pct_avg=data.get("deployment_pct_avg"),
        regime_vix_band=data.get("regime_vix_band"),
        regime_trend=data.get("regime_trend"),
        regime_btc_dom_band=data.get("regime_btc_dom_band"),
        strategies_breakdown_json=breakdown_json,
        errors_24h=int(data.get("errors_24h", 0)),
        sentry_issues_json=sentry_json,
        body_md=body_md,
        frontmatter_yaml=frontmatter_yaml,
    )

    if existing is not None:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.flush()
        return existing.id
    else:
        row = BotDailyJournal(**kwargs)
        db.add(row)
        db.flush()
        return row.id
