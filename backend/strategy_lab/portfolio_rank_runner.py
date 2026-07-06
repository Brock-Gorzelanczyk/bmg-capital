"""Portfolio-rank runtime.

Sits parallel to the signal-trigger runtime (`scan_and_execute.py`).
Loads a `portfolio_rank_bots` row, computes the factor for its
universe, produces a target basket (top decile long, optionally
bottom decile short), then rebalances `portfolio_rank_holdings` to
match. Rebalance is a diff: adds and removes only, no churn on
constant names.

Phase 1 runs the plumbing without hitting the broker. Holdings are
marked with target and actual weight; entry price is stored so future
mark-to-market has a cost basis. Real order placement to Alpaca is
Phase 2, when the first non-dummy bot ships.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_bot(db: Session, bot_id: int) -> Optional[dict]:
    row = db.execute(text("""
        SELECT id, name, description, factor_definition, universe,
               rebalance_schedule, long_decile, short_decile,
               position_sizing, starting_capital_cents, enabled,
               paper_citation, ssrn_id
        FROM portfolio_rank_bots WHERE id = :bid
    """), {"bid": bot_id}).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "name": row[1],
        "description": row[2],
        "factor_definition": json.loads(row[3] or "{}"),
        "universe": json.loads(row[4] or "{}"),
        "rebalance_schedule": row[5],
        "long_decile": int(row[6] or 10),
        "short_decile": int(row[7] or 0),
        "position_sizing": row[8],
        "starting_capital_cents": int(row[9] or 0),
        "enabled": bool(row[10]),
        "paper_citation": row[11],
        "ssrn_id": row[12],
    }


def _target_basket(
    ranking: dict[str, float],
    long_decile: int,
    short_decile: int,
    position_sizing: str,
) -> dict[str, dict[str, float]]:
    """Given a ranking, return {symbol: {"side": "long"|"short", "weight": w}}.

    Only equal_weight is implemented in Phase 1. value_weight requires
    market-cap data — added when the first real anomaly bot ships.
    """
    if not ranking:
        return {}
    n = len(ranking)
    long_n = max(1, math.ceil(n * long_decile / 100)) if long_decile > 0 else 0
    short_n = max(1, math.ceil(n * short_decile / 100)) if short_decile > 0 else 0

    sorted_desc = sorted(ranking.items(), key=lambda kv: -kv[1])
    long_syms = [s for s, _ in sorted_desc[:long_n]]
    short_syms = [s for s, _ in sorted_desc[-short_n:]] if short_n else []

    basket: dict[str, dict[str, float]] = {}
    if position_sizing != "equal_weight":
        logger.warning(
            "[portfolio-rank] sizing=%s not implemented; falling back to equal_weight",
            position_sizing,
        )
    if long_syms:
        w = round(1.0 / len(long_syms), 6)
        for s in long_syms:
            basket[s] = {"side": "long", "weight": w}
    if short_syms:
        w = round(-1.0 / len(short_syms), 6)
        for s in short_syms:
            basket[s] = {"side": "short", "weight": w}
    return basket


def _current_holdings(db: Session, bot_id: int) -> dict[str, dict[str, Any]]:
    rows = db.execute(text(
        "SELECT symbol, side, target_weight, actual_weight, entry_price_cents "
        "FROM portfolio_rank_holdings WHERE bot_id = :bid"
    ), {"bid": bot_id}).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r[0]] = {
            "side": r[1],
            "target_weight": float(r[2] or 0),
            "actual_weight": float(r[3] or 0),
            "entry_price_cents": int(r[4] or 0) if r[4] is not None else None,
        }
    return out


def _entry_price_cents(db: Session, symbol: str) -> Optional[int]:
    """Best-effort last close in cents. Returns None if unavailable.

    Phase 1 does not place real orders, so this cost basis is only for
    P&L attribution when Phase 2 wires the broker. Uses the canonical
    live-price cache when possible.
    """
    try:
        from app.core.canonical import _cached_live_prices
        prices = _cached_live_prices([symbol])
        px = prices.get(symbol)
        if px and px > 0:
            return int(round(float(px) * 100))
    except Exception:
        pass
    return None


def rebalance(
    db: Session,
    bot_id: int,
    triggered_by: str = "manual",
) -> dict[str, Any]:
    """Run one rebalance cycle for the named bot.

    Returns a dict with counts + a snippet of adds / removes. Never
    raises; errors are logged to portfolio_rank_rebalance_log.
    """
    t0 = time.monotonic()
    bot = _load_bot(db, bot_id)
    if not bot:
        return {"error": f"bot {bot_id} not found"}
    if not bot["enabled"]:
        return {"error": f"bot {bot['name']} disabled"}

    from strategy_lab.universes import get_universe
    from strategy_lab.factors import compute_factor

    error: Optional[str] = None
    ranking: dict[str, float] = {}
    basket: dict[str, dict[str, float]] = {}
    try:
        uni_type = str(bot["universe"].get("type", ""))
        if uni_type == "custom":
            symbols = list(bot["universe"].get("symbols", []))
        else:
            symbols = get_universe(uni_type)
        if not symbols:
            raise ValueError(f"empty universe: {uni_type}")

        factor_type = str(bot["factor_definition"].get("type", ""))
        factor_params = {k: v for k, v in bot["factor_definition"].items()
                         if k != "type"}
        ranking = compute_factor(factor_type, symbols, db, factor_params)
        basket = _target_basket(
            ranking, bot["long_decile"], bot["short_decile"],
            bot["position_sizing"],
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error("[portfolio-rank] %s rebalance failed: %s",
                     bot["name"], error, exc_info=True)

    adds: list[dict[str, Any]] = []
    removes: list[str] = []
    if error is None:
        current = _current_holdings(db, bot_id)
        target_syms = set(basket.keys())
        current_syms = set(current.keys())

        # Removes: in current but not in target.
        for sym in sorted(current_syms - target_syms):
            db.execute(text(
                "DELETE FROM portfolio_rank_holdings "
                "WHERE bot_id = :bid AND symbol = :sym"
            ), {"bid": bot_id, "sym": sym})
            removes.append(sym)

        # Upserts: in target. Insert new rows or update target_weight
        # for existing ones. Phase 1 sets actual_weight = target_weight
        # since we are not placing real orders.
        for sym, meta in basket.items():
            side = meta["side"]
            weight = float(meta["weight"])
            existing = current.get(sym)
            if existing:
                db.execute(text("""
                    UPDATE portfolio_rank_holdings
                    SET target_weight = :tw, actual_weight = :aw,
                        side = :side, last_marked_at = :ts
                    WHERE bot_id = :bid AND symbol = :sym
                """), {
                    "tw": weight, "aw": weight, "side": side,
                    "ts": _now_iso(), "bid": bot_id, "sym": sym,
                })
            else:
                px_c = _entry_price_cents(db, sym)
                db.execute(text("""
                    INSERT INTO portfolio_rank_holdings
                      (bot_id, symbol, target_weight, actual_weight,
                       side, entry_price_cents, current_price_cents,
                       entry_ts, last_marked_at, current_pnl_cents)
                    VALUES
                      (:bid, :sym, :tw, :aw, :side, :ec, :ec, :ts, :ts, 0)
                """), {
                    "bid": bot_id, "sym": sym, "tw": weight,
                    "aw": weight, "side": side, "ec": px_c,
                    "ts": _now_iso(),
                })
                adds.append({"symbol": sym, "side": side,
                             "target_weight": weight,
                             "entry_price_cents": px_c})

    latency_ms = int((time.monotonic() - t0) * 1000)
    db.execute(text("""
        INSERT INTO portfolio_rank_rebalance_log
          (bot_id, triggered_by, ranking_output, target_basket,
           adds, removes, latency_ms, error, created_at)
        VALUES
          (:bid, :tb, :ro, :tar, :ad, :rm, :lat, :err, :ts)
    """), {
        "bid": bot_id,
        "tb": triggered_by,
        "ro": json.dumps({k: round(v, 4) for k, v in
                          list(ranking.items())[:60]}),
        "tar": json.dumps(basket),
        "ad": json.dumps(adds),
        "rm": json.dumps(removes),
        "lat": latency_ms,
        "err": error,
        "ts": _now_iso(),
    })

    if error is None:
        db.execute(text("""
            UPDATE portfolio_rank_bots
            SET last_rebalanced_at = :ts
            WHERE id = :bid
        """), {"ts": _now_iso(), "bid": bot_id})

    db.commit()

    return {
        "bot_id": bot_id,
        "bot_name": bot["name"],
        "triggered_by": triggered_by,
        "universe_size": len(ranking),
        "target_basket_size": len(basket),
        "adds": len(adds),
        "removes": len(removes),
        "latency_ms": latency_ms,
        "error": error,
    }
