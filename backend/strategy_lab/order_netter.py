"""order_netter — aggregate per-bot intent orders, net offsets, submit residual.

Brock 2026-08-20 factor-consolidation research (PM Claude research pass):
DeMiguel-Martin-Utrera-Nogales-Uppal 2020 (SSRN 2912819) showed that
combining characteristics reduces transaction costs because trades across
factors cancel out. That effect is LARGER at small scale — dominant term
at $93K paying retail spreads. Value and momentum bots are ~-0.5
correlated; they routinely fire offsetting orders on the same tickers in
the same rebalance. Every one of those pairs is pure spread cost.

Two-phase design:
  Phase A (SHADOW MODE — this module): each bot rebalance still submits
    orders normally, but ALSO publishes its intent to a per-cycle buffer.
    At cycle end, we compute what the netted order book WOULD have looked
    like, log the diff, and record it to netter_shadow_log for analysis.
    Zero execution impact. Answers: "how much would netting save us?"

  Phase B (LIVE MODE — separate ship, DoD #1 gated): switch bot rebalances
    to PUBLISH-ONLY. Cycle-end orchestrator computes net, submits residual,
    then attributes fills back to contributing bots pro-rata.

This module is Phase A. Ship-safe: side-effect-free relative to execution.

Usage from PR runner:
    from strategy_lab.order_netter import publish_intent, record_cycle
    # In each bot's rebalance loop:
    publish_intent(bot_name, symbol, side, qty, notional_usd)
    # After all bots rebalanced:
    record_cycle(db)
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# In-memory buffer per (cycle) — reset when record_cycle() runs.
_buffer_lock = threading.Lock()
# {(symbol, side): [(bot_name, qty, notional_usd), ...]}
_buffer: dict[tuple[str, str], list[tuple[str, float, float]]] = defaultdict(list)


def publish_intent(bot_name: str, symbol: str, side: str, qty: float, notional_usd: float) -> None:
    """Record a bot's rebalance intent. Non-blocking, memory-only."""
    if not symbol or qty <= 0 or side not in ("buy", "sell"):
        return
    key = (symbol.upper(), side)
    with _buffer_lock:
        _buffer[key].append((bot_name, float(qty), float(notional_usd)))


def compute_netting(buffer: Optional[dict] = None) -> dict:
    """Compute what a netter WOULD have submitted. Returns diff stats.

    Called by record_cycle() with a snapshot of the buffer. Also callable
    standalone with a passed dict for tests.
    """
    b = buffer if buffer is not None else _buffer
    per_symbol: dict[str, dict] = {}
    for (sym, side), rows in b.items():
        gross_qty = sum(q for _, q, _ in rows)
        gross_notional = sum(n for _, _, n in rows)
        entry = per_symbol.setdefault(sym, {
            "buy_qty": 0.0, "sell_qty": 0.0,
            "buy_notional": 0.0, "sell_notional": 0.0,
            "buyer_bots": [], "seller_bots": [],
        })
        if side == "buy":
            entry["buy_qty"] += gross_qty
            entry["buy_notional"] += gross_notional
            entry["buyer_bots"].extend(bn for bn, _, _ in rows)
        else:
            entry["sell_qty"] += gross_qty
            entry["sell_notional"] += gross_notional
            entry["seller_bots"].extend(bn for bn, _, _ in rows)

    total_gross_notional = 0.0
    total_net_notional = 0.0
    savings_symbols = []
    for sym, e in per_symbol.items():
        gross = e["buy_notional"] + e["sell_notional"]
        net_qty = e["buy_qty"] - e["sell_qty"]
        # If both sides fire, net is the residual. Otherwise net equals gross.
        if e["buy_qty"] > 0 and e["sell_qty"] > 0:
            # Value + notional of the offsetting portion
            offset_qty = min(e["buy_qty"], e["sell_qty"])
            avg_px_buy = e["buy_notional"] / e["buy_qty"] if e["buy_qty"] > 0 else 0
            avg_px_sell = e["sell_notional"] / e["sell_qty"] if e["sell_qty"] > 0 else 0
            avg_px = (avg_px_buy + avg_px_sell) / 2
            offset_notional = offset_qty * avg_px * 2  # both sides
            net_notional = gross - offset_notional
            savings_symbols.append({
                "symbol": sym,
                "buyers": e["buyer_bots"],
                "sellers": e["seller_bots"],
                "buy_qty": e["buy_qty"],
                "sell_qty": e["sell_qty"],
                "offset_qty": offset_qty,
                "offset_notional_usd": round(offset_notional, 2),
                "gross_notional_usd": round(gross, 2),
                "net_notional_usd": round(net_notional, 2),
                "residual_side": "buy" if net_qty > 0 else "sell",
                "residual_qty": abs(round(net_qty, 4)),
            })
        else:
            net_notional = gross
        total_gross_notional += gross
        total_net_notional += net_notional

    saved = total_gross_notional - total_net_notional
    return {
        "total_gross_notional_usd": round(total_gross_notional, 2),
        "total_net_notional_usd": round(total_net_notional, 2),
        "savings_notional_usd": round(saved, 2),
        "savings_pct_of_gross": round(saved / total_gross_notional * 100, 2) if total_gross_notional else 0,
        "symbol_pairs_netted": len(savings_symbols),
        "symbols_traded": len(per_symbol),
        "savings_symbols": savings_symbols[:20],
    }


def record_cycle(db: Session) -> dict:
    """Snapshot the buffer, compute netting stats, persist to log, clear."""
    with _buffer_lock:
        snap = {k: list(v) for k, v in _buffer.items()}
        _buffer.clear()
    if not snap:
        return {"skipped": "empty_buffer"}
    stats = compute_netting(snap)
    # Persist
    try:
        _ensure_table(db)
        db.execute(text(
            "INSERT INTO netter_shadow_log (ts_utc, gross_notional_usd, "
            "net_notional_usd, savings_usd, symbol_pairs_netted, "
            "symbols_traded, symbols_json) VALUES (:ts, :gr, :nt, :sv, :np, :st, :sj)"
        ), {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gr": stats["total_gross_notional_usd"],
            "nt": stats["total_net_notional_usd"],
            "sv": stats["savings_notional_usd"],
            "np": stats["symbol_pairs_netted"],
            "st": stats["symbols_traded"],
            "sj": str(stats["savings_symbols"])[:4000],
        })
        db.commit()
    except Exception as exc:
        logger.warning("[order-netter] persist failed (shadow only): %s", exc)
    logger.warning(
        "[order-netter:shadow] gross=$%.2f net=$%.2f saved=$%.2f (%.1f%%) pairs=%d symbols=%d",
        stats["total_gross_notional_usd"], stats["total_net_notional_usd"],
        stats["savings_notional_usd"], stats["savings_pct_of_gross"],
        stats["symbol_pairs_netted"], stats["symbols_traded"],
    )
    return stats


def _ensure_table(db) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS netter_shadow_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            gross_notional_usd REAL NOT NULL,
            net_notional_usd REAL NOT NULL,
            savings_usd REAL NOT NULL,
            symbol_pairs_netted INTEGER NOT NULL,
            symbols_traded INTEGER NOT NULL,
            symbols_json TEXT
        )
    """))
