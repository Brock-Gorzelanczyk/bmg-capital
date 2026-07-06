"""m064 — Strategy Farm Phase 1: template library + candidate table.

Ships the schema and seeds 10 hand-coded templates. No cron. No auto-
backtest. Feature flag BMG_STRATEGY_FARM_ENABLED gates the generator
endpoint; this migration itself is a pure schema change and runs even
when the flag is off.

Note on table naming
--------------------
The spec asked for a `strategy_candidates` table, but that name is
already taken by the existing candidate pipeline (BacktestRun,
WfaRun, CandidateStateHistory all reference it). To keep the two
workflows separate and not disturb existing state history, this
migration creates `farm_candidates`. Phase 3/4 promotion to the
incubation panel is a separate wiring task.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m064_strategy_farm_phase1_2026_07"


# 10 seed templates. Each has a param_schema and a stub of entry/exit
# logic strings — actual sandbox eval happens in Phase 2. asset_classes
# is JSON. base_indicators is JSON. entry_logic_code + exit_logic_code
# are plain Python source strings.
_TEMPLATES: list[dict] = [
    {
        "name": "donchian_breakout",
        "category": "breakout",
        "base_indicators": ["donchian_high", "donchian_low", "atr"],
        "param_schema": {
            "lookback": {"min": 10, "max": 200, "step": 10, "type": "int"},
            "atr_stop_mult": {"min": 1.0, "max": 4.0, "step": 0.25, "type": "float"},
            "risk_pct": {"min": 0.5, "max": 3.0, "step": 0.25, "type": "float"},
        },
        "entry_logic_code": (
            "signal = 'buy' if close > donchian_high(bars, params['lookback']) else "
            "'sell' if close < donchian_low(bars, params['lookback']) else None"
        ),
        "exit_logic_code": (
            "stop = entry_price - params['atr_stop_mult'] * atr(bars, 14) if side=='buy' else "
            "entry_price + params['atr_stop_mult'] * atr(bars, 14)"
        ),
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 250,
    },
    {
        "name": "keltner_meanrev",
        "category": "meanrev",
        "base_indicators": ["ema", "atr"],
        "param_schema": {
            "ema_len": {"min": 10, "max": 100, "step": 10, "type": "int"},
            "channel_mult": {"min": 1.5, "max": 3.5, "step": 0.25, "type": "float"},
            "risk_pct": {"min": 0.5, "max": 2.5, "step": 0.25, "type": "float"},
        },
        "entry_logic_code": (
            "mid = ema(close, params['ema_len']); band = params['channel_mult']*atr(bars,14); "
            "signal = 'buy' if close < mid-band else 'sell' if close > mid+band else None"
        ),
        "exit_logic_code": "target = mid  # revert to mean",
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 200,
    },
    {
        "name": "ema_cross_momentum",
        "category": "momentum",
        "base_indicators": ["ema"],
        "param_schema": {
            "fast_len": {"min": 5, "max": 30, "step": 1, "type": "int"},
            "slow_len": {"min": 20, "max": 200, "step": 5, "type": "int"},
            "risk_pct": {"min": 0.5, "max": 3.0, "step": 0.25, "type": "float"},
        },
        "entry_logic_code": (
            "fast = ema(close, params['fast_len']); slow = ema(close, params['slow_len']); "
            "signal = 'buy' if cross_above(fast, slow) else 'sell' if cross_below(fast, slow) else None"
        ),
        "exit_logic_code": "signal_close_on_recross",
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 300,
    },
    {
        "name": "macd_swing",
        "category": "momentum",
        "base_indicators": ["macd"],
        "param_schema": {
            "fast": {"min": 8, "max": 20, "step": 1, "type": "int"},
            "slow": {"min": 20, "max": 60, "step": 2, "type": "int"},
            "signal": {"min": 5, "max": 15, "step": 1, "type": "int"},
        },
        "entry_logic_code": (
            "hist = macd_hist(close, params['fast'], params['slow'], params['signal']); "
            "signal = 'buy' if hist[-1]>0 and hist[-2]<0 else 'sell' if hist[-1]<0 and hist[-2]>0 else None"
        ),
        "exit_logic_code": "flip_on_opposite_cross",
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 200,
    },
    {
        "name": "rsi_divergence",
        "category": "meanrev",
        "base_indicators": ["rsi"],
        "param_schema": {
            "rsi_len": {"min": 7, "max": 30, "step": 1, "type": "int"},
            "oversold": {"min": 20, "max": 35, "step": 1, "type": "int"},
            "overbought": {"min": 65, "max": 80, "step": 1, "type": "int"},
        },
        "entry_logic_code": (
            "r = rsi(close, params['rsi_len']); "
            "signal = 'buy' if r < params['oversold'] and lower_low(close) and higher_low(r) else "
            "'sell' if r > params['overbought'] and higher_high(close) and lower_high(r) else None"
        ),
        "exit_logic_code": "close_when_rsi_crosses_50",
        "asset_classes": ["stocks", "crypto"],
        "min_bars_required": 150,
    },
    {
        "name": "atr_channel_break",
        "category": "breakout",
        "base_indicators": ["atr", "sma"],
        "param_schema": {
            "sma_len": {"min": 20, "max": 100, "step": 5, "type": "int"},
            "atr_mult": {"min": 1.0, "max": 3.5, "step": 0.25, "type": "float"},
            "risk_pct": {"min": 0.5, "max": 2.5, "step": 0.25, "type": "float"},
        },
        "entry_logic_code": (
            "base = sma(close, params['sma_len']); ch = params['atr_mult']*atr(bars,14); "
            "signal = 'buy' if close > base+ch else 'sell' if close < base-ch else None"
        ),
        "exit_logic_code": "atr_trailing_stop",
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 200,
    },
    {
        "name": "bollinger_squeeze",
        "category": "vol",
        "base_indicators": ["bbands", "keltner"],
        "param_schema": {
            "bb_len": {"min": 15, "max": 30, "step": 1, "type": "int"},
            "bb_mult": {"min": 1.5, "max": 2.5, "step": 0.1, "type": "float"},
            "squeeze_ratio": {"min": 0.5, "max": 0.9, "step": 0.05, "type": "float"},
        },
        "entry_logic_code": (
            "if bbwidth(close, params['bb_len'], params['bb_mult']) / kc_width < params['squeeze_ratio']: "
            "signal = 'buy' if close > sma(close,20) else 'sell'"
        ),
        "exit_logic_code": "close_on_squeeze_release",
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 100,
    },
    {
        "name": "opening_range_break",
        "category": "breakout",
        "base_indicators": ["session_open", "atr"],
        "param_schema": {
            "or_minutes": {"min": 15, "max": 60, "step": 5, "type": "int"},
            "buffer_atr": {"min": 0.1, "max": 1.0, "step": 0.1, "type": "float"},
            "target_r": {"min": 1.0, "max": 3.0, "step": 0.25, "type": "float"},
        },
        "entry_logic_code": (
            "or_h, or_l = opening_range(bars, params['or_minutes']); "
            "buf = params['buffer_atr']*atr(bars,14); "
            "signal = 'buy' if close > or_h+buf else 'sell' if close < or_l-buf else None"
        ),
        "exit_logic_code": "r_multiple_target",
        "asset_classes": ["stocks"],
        "min_bars_required": 60,
    },
    {
        "name": "volume_zscore",
        "category": "vol",
        "base_indicators": ["volume", "sma"],
        "param_schema": {
            "z_window": {"min": 20, "max": 100, "step": 5, "type": "int"},
            "z_entry": {"min": 1.5, "max": 4.0, "step": 0.25, "type": "float"},
            "conf_hold": {"min": 5, "max": 60, "step": 5, "type": "int"},
        },
        "entry_logic_code": (
            "z = zscore(volume, params['z_window']); "
            "signal = 'buy' if z > params['z_entry'] and close > sma(close,20) else "
            "'sell' if z > params['z_entry'] and close < sma(close,20) else None"
        ),
        "exit_logic_code": "time_stop_conf_hold_minutes",
        "asset_classes": ["stocks", "crypto"],
        "min_bars_required": 150,
    },
    {
        "name": "regime_ema_ribbon",
        "category": "momentum",
        "base_indicators": ["ema"],
        "param_schema": {
            "ribbon_lens": {"min": 8, "max": 200, "step": 20, "type": "int_list"},
            "min_stack": {"min": 3, "max": 8, "step": 1, "type": "int"},
            "risk_pct": {"min": 0.5, "max": 2.5, "step": 0.25, "type": "float"},
        },
        "entry_logic_code": (
            "ribbon = [ema(close, l) for l in params['ribbon_lens']]; "
            "stacked_up = all(ribbon[i] > ribbon[i+1] for i in range(len(ribbon)-1)); "
            "signal = 'buy' if stacked_up else 'sell' if stacked_down(ribbon) else None"
        ),
        "exit_logic_code": "unstack_close",
        "asset_classes": ["crypto", "stocks"],
        "min_bars_required": 250,
    },
]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS strategy_templates (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                VARCHAR(80) UNIQUE NOT NULL,
            category            VARCHAR(40) NOT NULL,
            base_indicators     TEXT NOT NULL,
            param_schema        TEXT NOT NULL,
            entry_logic_code    TEXT NOT NULL,
            exit_logic_code     TEXT NOT NULL,
            asset_classes       TEXT NOT NULL,
            min_bars_required   INTEGER NOT NULL DEFAULT 100,
            enabled             BOOLEAN NOT NULL DEFAULT 1,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by          VARCHAR(80) DEFAULT 'brock'
        )
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS farm_candidates (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id         INTEGER NOT NULL,
            parameters          TEXT NOT NULL,
            status              VARCHAR(20) NOT NULL DEFAULT 'generated',
            backtest_stats      TEXT,
            walkforward_stats   TEXT,
            robustness_score    FLOAT,
            rejected_reason     TEXT,
            promoted_at         TIMESTAMP,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(template_id) REFERENCES strategy_templates(id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_farm_candidates_status "
        "ON farm_candidates(status)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_farm_candidates_template "
        "ON farm_candidates(template_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_farm_candidates_created_at "
        "ON farm_candidates(created_at)"
    ))

    inserted = 0
    for t in _TEMPLATES:
        # Skip if a template with this name already exists (idempotent seed).
        existing = conn.execute(text(
            "SELECT id FROM strategy_templates WHERE name = :n"
        ), {"n": t["name"]}).fetchone()
        if existing:
            continue
        conn.execute(text("""
            INSERT INTO strategy_templates
              (name, category, base_indicators, param_schema,
               entry_logic_code, exit_logic_code,
               asset_classes, min_bars_required, enabled, created_at)
            VALUES
              (:name, :category, :base_indicators, :param_schema,
               :entry_logic_code, :exit_logic_code,
               :asset_classes, :min_bars_required, 1, :created_at)
        """), {
            "name": t["name"],
            "category": t["category"],
            "base_indicators": json.dumps(t["base_indicators"]),
            "param_schema": json.dumps(t["param_schema"]),
            "entry_logic_code": t["entry_logic_code"],
            "exit_logic_code": t["exit_logic_code"],
            "asset_classes": json.dumps(t["asset_classes"]),
            "min_bars_required": int(t["min_bars_required"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        inserted += 1

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "tables": ["strategy_templates", "farm_candidates"],
        "templates_seeded": inserted,
        "templates_defined": len(_TEMPLATES),
    }
