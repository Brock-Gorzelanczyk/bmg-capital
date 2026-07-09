"""Broker vs DB position reconciliation.

Diffs the live Alpaca paper positions against `bot_positions` rows that are
still open (closed_at IS NULL) and reports symbols that are out of sync.

READ-ONLY. Never mutates broker state. Never auto-closes db_only positions
or auto-creates broker_only rows. Brock decides per-row (mass-action
restraint per `06-decision-history.md`).

Severity buckets:
  ok    — zero diffs (matched qty and side, no broker_only, no db_only)
  warn  — any diffs but the total dollar divergence is < $100
  alert — diffs >= $100
  error — Alpaca call failed; report carries the exception message
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

WARN_DIVERGENCE_USD = 100.0

# ── Type aliases ────────────────────────────────────────────────────────────
# A "broker position" is a dict with at least: symbol, qty (float),
# market_value (float, USD, signed for shorts).
BrokerPosition = Dict[str, Any]


def _default_alpaca_fetcher() -> List[BrokerPosition]:
    """Fetch live positions from Alpaca paper account.

    Resolution order for credentials matches `routers/admin.py:/alpaca/ping`:
      ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET, then
      ALPACA_API_KEY  / ALPACA_SECRET_KEY.

    Returns a list of normalized dicts. Raises on auth/network errors so the
    caller can wrap into the error report.
    """
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError(
            "No Alpaca credentials found. Set ALPACA_PAPER_KEY + "
            "ALPACA_PAPER_SECRET (or ALPACA_API_KEY + ALPACA_SECRET_KEY)."
        )

    from alpaca.trading.client import TradingClient

    client = TradingClient(key, secret, paper=True)
    raw_positions = client.get_all_positions()

    normalized: List[BrokerPosition] = []
    for p in raw_positions:
        try:
            normalized.append({
                "symbol": str(getattr(p, "symbol", "")).upper(),
                "qty": float(getattr(p, "qty", 0) or 0),
                "market_value": float(getattr(p, "market_value", 0) or 0),
                "side": str(getattr(p, "side", "long") or "long"),
            })
        except Exception as exc:  # pragma: no cover — defensive parse
            logger.warning("[reconcile] could not parse broker position %r: %s", p, exc)
    return normalized


def _fetch_db_positions(db, user_id: int) -> List[Dict[str, Any]]:
    """Return one row per tracked BMG position for the given user.

    Two source tables:
      1. bot_positions — the per-signal trigger runtime (options + quant + swing).
         Joined via bot_allocations to filter by user_id.
      2. portfolio_rank_holdings — the portfolio-rank sleeve (Phase 2 broker
         execution). One row per basket name; does NOT link to bot_allocations.
         Included so PR broker fills don't get flagged as broker-only.

    Returns dicts with: symbol, qty, side, notional_db, source.
    """
    # Imported lazily so tests can mock app.db.models.bots without affecting
    # module import time.
    from sqlalchemy import text as _text
    from app.db.models.bots import BotAllocation, BotPosition

    out: List[Dict[str, Any]] = []

    rows = (
        db.query(BotPosition, BotAllocation)
        .join(BotAllocation, BotPosition.allocation_id == BotAllocation.id)
        .filter(BotAllocation.user_id == user_id)
        .filter(BotPosition.closed_at.is_(None))
        .all()
    )
    for pos, alloc in rows:
        out.append({
            "position_id": pos.id,
            "allocation_id": alloc.id,
            "symbol": str(pos.symbol).upper(),
            "qty": float(pos.qty or 0),
            "side": str(pos.side or "long"),
            "avg_cost_cents": float(pos.avg_cost_cents or 0),
            "notional_db": float(pos.qty or 0) * float(pos.avg_cost_cents or 0) / 100.0,
            "source": "bot_positions",
        })

    # portfolio_rank_holdings: filter to symbols the broker actually FILLED.
    # The initial version of this union included every target-basket name,
    # which turned 220+ dry-run/rejected target names into fake db_only rows
    # in the reconciler. Fix: only include holdings whose most-recent
    # rebalance_log has that symbol in broker_results.orders_placed with a
    # non-null order_id.
    try:
        import json as _json
        filled_syms: set[str] = set()
        log_rows = db.execute(_text("""
            SELECT bot_id, adds, created_at
              FROM portfolio_rank_rebalance_log
             ORDER BY created_at DESC
             LIMIT 200
        """)).fetchall()
        seen_bots: set[int] = set()
        for r in log_rows:
            bid = int(r[0])
            if bid in seen_bots:
                continue  # only most-recent log per bot
            seen_bots.add(bid)
            try:
                adds_data = _json.loads(r[1] or "null")
            except Exception:
                continue
            if not isinstance(adds_data, dict):
                continue
            br = adds_data.get("broker_results") or {}
            for placed in br.get("orders_placed", []):
                sym = str(placed.get("symbol") or "").upper()
                if sym and placed.get("order_id"):
                    filled_syms.add(sym)

        if filled_syms:
            pr_rows = db.execute(_text("""
                SELECT h.symbol, h.side, h.target_weight, h.entry_price_cents,
                       b.starting_capital_cents, b.name
                  FROM portfolio_rank_holdings h
                  JOIN portfolio_rank_bots b ON b.id = h.bot_id
                 WHERE b.enabled = 1
            """)).fetchall()
            for r in pr_rows:
                sym = str(r[0] or "").upper()
                if sym not in filled_syms:
                    continue
                side = str(r[1] or "long")
                weight = abs(float(r[2] or 0))
                entry_px_c = int(r[3] or 0)
                starting_c = int(r[4] or 0)
                dollar_target = (starting_c / 100.0) * weight
                entry_px = entry_px_c / 100.0
                qty = (dollar_target / entry_px) if entry_px > 0 else 0.0
                out.append({
                    "position_id": None,
                    "allocation_id": None,
                    "symbol": sym,
                    "qty": round(qty, 6),
                    "side": side,
                    "avg_cost_cents": float(entry_px_c),
                    "notional_db": dollar_target,
                    "source": f"portfolio_rank_holdings/{r[5]}",
                })
    except Exception as _pr_exc:  # pragma: no cover
        logger.warning(
            "[reconcile] portfolio_rank fetch failed (proceeding without PR positions): %s",
            _pr_exc,
        )

    return out


def _aggregate_by_symbol(rows: List[Dict[str, Any]], notional_key: str) -> Dict[str, Dict[str, float]]:
    """Sum qty and notional per symbol. Handles bots with multiple lots on the
    same symbol (each lot is its own bot_positions row)."""
    agg: Dict[str, Dict[str, float]] = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in agg:
            agg[sym] = {"qty": 0.0, "notional": 0.0}
        agg[sym]["qty"] += float(r.get("qty", 0))
        agg[sym]["notional"] += float(r.get(notional_key, 0))
    return agg


def _classify_severity(
    qty_mismatched: List[Dict[str, Any]],
    broker_only: List[Dict[str, Any]],
    db_only: List[Dict[str, Any]],
) -> str:
    """Return ok | warn | alert based on total dollar divergence."""
    if not qty_mismatched and not broker_only and not db_only:
        return "ok"
    total_divergence = 0.0
    for r in qty_mismatched:
        total_divergence += abs(float(r.get("notional_broker", 0)) - float(r.get("notional_db", 0)))
    for r in broker_only:
        total_divergence += abs(float(r.get("notional_broker", 0)))
    for r in db_only:
        total_divergence += abs(float(r.get("notional_db", 0)))
    return "warn" if total_divergence < WARN_DIVERGENCE_USD else "alert"


def reconcile_positions(
    db,
    user_id: int = 1,
    broker_fetcher: Optional[Callable[[], List[BrokerPosition]]] = None,
) -> Dict[str, Any]:
    """Diff Alpaca paper positions vs open bot_positions for the given user.

    Args:
        db: SQLAlchemy Session.
        user_id: which user's bot_positions to inspect. Default 1 (Brock).
        broker_fetcher: optional callable that returns the broker position
            list. Defaults to the live Alpaca client. Injected by tests.

    Returns:
        dict with the report shape described in module docstring.
    """
    if broker_fetcher is None:
        broker_fetcher = _default_alpaca_fetcher

    as_of = datetime.now(timezone.utc).isoformat()

    # ── 1. Fetch broker positions ─────────────────────────────────────────────
    try:
        broker_rows = broker_fetcher()
    except Exception as exc:
        logger.exception("[reconcile] broker fetch failed")
        return {
            "as_of": as_of,
            "user_id": user_id,
            "broker_positions_count": 0,
            "db_positions_count": 0,
            "matched": [],
            "broker_only": [],
            "db_only": [],
            "qty_mismatched": [],
            "divergence_severity": "error",
            "error": str(exc)[:500],
        }

    # ── 2. Fetch DB positions ─────────────────────────────────────────────────
    db_rows = _fetch_db_positions(db, user_id)

    # ── 3. Aggregate by symbol ────────────────────────────────────────────────
    broker_agg = _aggregate_by_symbol(
        [{"symbol": str(r["symbol"]).upper(),
          "qty": float(r.get("qty", 0)),
          "notional_broker": float(r.get("market_value", 0))}
         for r in broker_rows],
        notional_key="notional_broker",
    )
    db_agg = _aggregate_by_symbol(db_rows, notional_key="notional_db")

    broker_symbols = set(broker_agg.keys())
    db_symbols = set(db_agg.keys())

    # ── 4. Bucket: matched / broker_only / db_only / qty_mismatched ───────────
    matched: List[Dict[str, Any]] = []
    qty_mismatched: List[Dict[str, Any]] = []
    QTY_TOLERANCE = 1e-6  # crypto can be fractional; allow tiny float noise

    for sym in sorted(broker_symbols & db_symbols):
        qb = broker_agg[sym]["qty"]
        qd = db_agg[sym]["qty"]
        nb = broker_agg[sym]["notional"]
        nd = db_agg[sym]["notional"]
        entry = {
            "symbol": sym,
            "qty_broker": qb,
            "qty_db": qd,
            "notional_broker": nb,
            "notional_db": nd,
        }
        if abs(qb - qd) <= QTY_TOLERANCE:
            matched.append(entry)
        else:
            qty_mismatched.append(entry)

    broker_only = [
        {
            "symbol": sym,
            "qty_broker": broker_agg[sym]["qty"],
            "notional_broker": broker_agg[sym]["notional"],
        }
        for sym in sorted(broker_symbols - db_symbols)
    ]
    db_only = [
        {
            "symbol": sym,
            "qty_db": db_agg[sym]["qty"],
            "notional_db": db_agg[sym]["notional"],
        }
        for sym in sorted(db_symbols - broker_symbols)
    ]

    severity = _classify_severity(qty_mismatched, broker_only, db_only)

    return {
        "as_of": as_of,
        "user_id": user_id,
        "broker_positions_count": len(broker_rows),
        "db_positions_count": len(db_rows),
        "matched": matched,
        "broker_only": broker_only,
        "db_only": db_only,
        "qty_mismatched": qty_mismatched,
        "divergence_severity": severity,
    }


def format_report_for_discord(report: Dict[str, Any]) -> str:
    """Compact text summary suitable for a Discord embed description."""
    sev = report.get("divergence_severity", "unknown")
    if sev == "error":
        return f"Reconciliation FAILED: {report.get('error', 'unknown error')}"
    lines = [
        f"Severity: {sev.upper()}",
        f"Broker positions: {report.get('broker_positions_count', 0)}",
        f"DB positions:     {report.get('db_positions_count', 0)}",
        f"Matched:          {len(report.get('matched', []))}",
        f"Broker-only:      {len(report.get('broker_only', []))}",
        f"DB-only:          {len(report.get('db_only', []))}",
        f"Qty mismatched:   {len(report.get('qty_mismatched', []))}",
    ]
    # Show first few mismatches for quick triage
    samples: List[str] = []
    for r in (report.get("broker_only") or [])[:3]:
        samples.append(f"  broker_only {r['symbol']}: qty={r.get('qty_broker')} mv=${r.get('notional_broker', 0):.2f}")
    for r in (report.get("db_only") or [])[:3]:
        samples.append(f"  db_only {r['symbol']}: qty={r.get('qty_db')} cost=${r.get('notional_db', 0):.2f}")
    for r in (report.get("qty_mismatched") or [])[:3]:
        samples.append(
            f"  qty_mismatch {r['symbol']}: broker={r.get('qty_broker')} db={r.get('qty_db')}"
        )
    if samples:
        lines.append("Sample diffs:")
        lines.extend(samples)
    return "\n".join(lines)
