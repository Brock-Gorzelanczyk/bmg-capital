"""Brain Graph — knowledge-graph payload for the JARVIS-style brain view.

Returns a force-graph node/edge payload summarizing the last N days of trading
activity: sessions, strategies, symbols, signals, trades, and lessons.

Every query is wrapped so one bad row can't 500 the endpoint — soft-fail with
a logger.warning and continue.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_GRAPH_CACHE: dict[int, tuple[float, dict]] = {}
_GRAPH_TTL = 300  # 5 min
_ET_OFFSET = timedelta(hours=-4)  # fixed (no DST), matches existing project style


def _et(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc) + _ET_OFFSET


def _session_label(ts: datetime) -> str:
    try:
        h = _et(ts).hour
    except Exception:
        return "OVERNIGHT"
    if 9 <= h < 12: return "NY_AM"
    if 12 <= h < 16: return "NY_PM"
    if 3 <= h < 9: return "LONDON"
    if 16 <= h < 20: return "ASIA"
    return "OVERNIGHT"


def _session_date(ts: datetime) -> str:
    try:
        return _et(ts).date().isoformat()
    except Exception:
        return "unknown"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pnl_color(pnl: float) -> str:
    if pnl > 0: return "#22c55e"
    if pnl < 0: return "#ef4444"
    return "#9ca3af"


def _status_color(status: str | None) -> str:
    if status == "live": return "#22c55e"
    if status == "testing": return "#f59e0b"
    return "#9ca3af"


def _asset_color(symbol: str, has_option: bool) -> str:
    if has_option: return "#a855f7"
    if "/" in (symbol or ""): return "#fb923c"
    return "#3b82f6"


def build_graph(db: Session, days: int = 30) -> dict:
    """Build a force-graph payload of the last N days of trading activity."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # --- Queries (each soft-fails to []) ---
    signals: list = []
    try:
        from app.db.models.bots import BotSignal
        from sqlalchemy import or_
        signals = (
            db.query(BotSignal)
            .filter(BotSignal.ts >= cutoff)
            .filter(or_(BotSignal.is_test.is_(None), BotSignal.is_test.is_(False)))
            .all()
        )
    except Exception as exc:
        logger.warning("[brain_graph] bot_signals query failed: %s", exc)

    signal_ids = [s.id for s in signals]

    trades: list = []
    try:
        from app.db.models.bots import BotTrade
        if signal_ids:
            trades = db.query(BotTrade).filter(BotTrade.signal_id.in_(signal_ids)).all()
    except Exception as exc:
        logger.warning("[brain_graph] bot_trades query failed: %s", exc)

    gates_by_signal: dict[int, str] = {}
    try:
        from app.db.models.signal_gates import SignalGate
        if signal_ids:
            for g in db.query(SignalGate).filter(SignalGate.signal_id.in_(signal_ids)).all():
                try: gates_by_signal[g.signal_id] = g.final_decision
                except Exception: pass
    except Exception as exc:
        logger.warning("[brain_graph] signal_gates query failed (skipping): %s", exc)

    hyp_status: dict[str, str] = {}
    try:
        from app.db.models.hypotheses import Hypothesis
        for h in db.query(Hypothesis).all():
            try: hyp_status[h.strategy_id] = h.status
            except Exception: pass
    except Exception as exc:
        logger.warning("[brain_graph] hypotheses query failed (skipping): %s", exc)

    lessons: list = []
    try:
        from app.db.models.hypotheses import Lesson
        lessons = db.query(Lesson).all()
    except Exception as exc:
        logger.warning("[brain_graph] lessons query failed: %s", exc)

    avg_cost: dict[int, float] = {}
    try:
        from app.db.models.bots import BotPosition
        pos_ids = {t.position_id for t in trades if getattr(t, "position_id", None)}
        if pos_ids:
            for p in db.query(BotPosition).filter(BotPosition.id.in_(pos_ids)).all():
                try: avg_cost[p.id] = float(p.avg_cost_cents or 0) / 100.0
                except Exception: pass
    except Exception as exc:
        logger.warning("[brain_graph] bot_positions query failed: %s", exc)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_node(n: dict) -> None:
        nid = n.get("id")
        if not nid or nid in seen: return
        seen.add(nid); nodes.append(n)

    # --- First pass over trades: P&L, session bucket, symbol stats ---
    trade_pnl: dict[int, float] = {}
    trade_session: dict[int, str] = {}
    session_pnl: dict[str, float] = {}
    session_n: dict[str, int] = {}
    session_meta: dict[str, dict] = {}
    sym_has_option: dict[str, bool] = {}
    sym_count: dict[str, int] = {}

    for t in trades:
        try:
            tid = t.id
            sym = t.symbol or "UNKNOWN"
            sym_count[sym] = sym_count.get(sym, 0) + 1
            sym_has_option[sym] = sym_has_option.get(sym, False) or bool(getattr(t, "option_type", None))

            pnl = 0.0
            if (t.side or "").lower() == "sell" and t.position_id in avg_cost:
                fill = float(t.fill_price_cents or 0) / 100.0
                pnl = (fill - avg_cost[t.position_id]) * float(t.qty or 0)
            trade_pnl[tid] = pnl

            sd, sl = _session_date(t.ts), _session_label(t.ts)
            sid = f"session_{sd}_{sl}"
            trade_session[tid] = sid
            session_pnl[sid] = session_pnl.get(sid, 0.0) + pnl
            session_n[sid] = session_n.get(sid, 0) + 1
            session_meta.setdefault(sid, {"date": sd, "label": sl})
        except Exception as exc:
            logger.warning("[brain_graph] trade pre-pass failed: %s", exc)

    # --- SESSION nodes ---
    for sid, m in session_meta.items():
        try:
            n = session_n.get(sid, 0)
            pnl = session_pnl.get(sid, 0.0)
            add_node({
                "id": sid, "type": "SESSION",
                "label": f"{m['label']} {m['date']}",
                "size": _clamp(float(n), 4, 30),
                "color": _pnl_color(pnl) if n > 0 else "#9ca3af",
                "meta": {"date": m["date"], "label": m["label"], "trades": n, "pnl": round(pnl, 2)},
            })
        except Exception as exc:
            logger.warning("[brain_graph] session node failed: %s", exc)

    # --- STRATEGY nodes ---
    strat_count: dict[str, int] = {}
    for s in signals:
        try: strat_count[s.strategy or "unknown"] = strat_count.get(s.strategy or "unknown", 0) + 1
        except Exception: pass

    for strat, c in strat_count.items():
        try:
            st = hyp_status.get(strat)
            add_node({
                "id": f"strategy_{strat}", "type": "STRATEGY", "label": strat,
                "size": _clamp(5 + math.log1p(c) * 6, 5, 40),
                "color": _status_color(st),
                "meta": {"strategy": strat, "signal_count": c, "hypothesis_status": st},
            })
        except Exception as exc:
            logger.warning("[brain_graph] strategy node failed: %s", exc)

    # --- SYMBOL nodes ---
    for sym, c in sym_count.items():
        try:
            has_opt = sym_has_option.get(sym, False)
            ac = "options" if has_opt else ("crypto" if "/" in sym else "stocks")
            add_node({
                "id": f"symbol_{sym}", "type": "SYMBOL", "label": sym,
                "size": _clamp(float(c), 4, 25),
                "color": _asset_color(sym, has_opt),
                "meta": {"symbol": sym, "asset_class": ac, "trade_count": c},
            })
        except Exception as exc:
            logger.warning("[brain_graph] symbol node failed: %s", exc)

    # --- SIGNAL nodes + SIGNAL→STRATEGY edges ---
    for s in signals:
        try:
            sid = s.id
            executed = gates_by_signal.get(sid) == "executed" or getattr(s, "executed_at", None) is not None
            conf = float(s.confidence or 0)
            strat = s.strategy or "unknown"
            nid = f"signal_{sid}"
            add_node({
                "id": nid, "type": "SIGNAL",
                "label": f"{s.symbol} {s.side}",
                "size": _clamp(4 + (conf * 100.0) / 20.0, 4, 9),
                "color": "#22c55e" if executed else "#9ca3af",
                "meta": {"strategy": strat, "symbol": s.symbol, "side": s.side,
                         "confidence": conf, "executed": executed},
            })
            edges.append({"source": nid, "target": f"strategy_{strat}", "type": "SIGNAL_STRATEGY"})
        except Exception as exc:
            logger.warning("[brain_graph] signal node failed: %s", exc)

    # --- TRADE nodes + edges ---
    for t in trades:
        try:
            tid = t.id
            pnl = trade_pnl.get(tid, 0.0)
            color = "#22c55e" if pnl > 0 else ("#ef4444" if pnl < 0 else "#eab308")
            qty = float(t.qty or 0)
            fill = float(t.fill_price_cents or 0) / 100.0
            notional = abs(qty * fill)
            nid = f"trade_{tid}"
            add_node({
                "id": nid, "type": "TRADE",
                "label": f"{t.side} {t.symbol}",
                "size": _clamp(4 + math.log1p(notional) / 2.0, 4, 10),
                "color": color,
                "meta": {"symbol": t.symbol, "side": t.side, "qty": qty,
                         "fill_price": fill, "pnl": round(pnl, 2),
                         "notional": round(notional, 2)},
            })
            ss = trade_session.get(tid)
            if ss: edges.append({"source": ss, "target": nid, "type": "SESSION_TRADE"})
            if getattr(t, "signal_id", None):
                edges.append({"source": nid, "target": f"signal_{t.signal_id}", "type": "TRADE_SIGNAL"})
            if t.symbol:
                edges.append({"source": nid, "target": f"symbol_{t.symbol}", "type": "TRADE_SYMBOL"})
        except Exception as exc:
            logger.warning("[brain_graph] trade node failed: %s", exc)

    # --- LESSON nodes (no edges yet — lesson→trade FK to be wired in Phase 5) ---
    for l in lessons:
        try:
            add_node({
                "id": f"lesson_{l.id}", "type": "LESSON",
                "label": (l.lesson_text or "")[:60],
                "size": 6, "color": "#8b5cf6",
                "meta": {"hypothesis_id": getattr(l, "hypothesis_id", None),
                         "context": (getattr(l, "context", "") or "")[:120]},
            })
        except Exception as exc:
            logger.warning("[brain_graph] lesson node failed: %s", exc)

    valid_edges = [e for e in edges if e["source"] in seen and e["target"] in seen]
    return {
        "nodes": nodes,
        "edges": valid_edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(valid_edges),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def get_cached_graph(db: Session, days: int = 30) -> dict:
    now = time.time()
    entry = _GRAPH_CACHE.get(days)
    if entry and now - entry[0] < _GRAPH_TTL:
        return entry[1]
    payload = build_graph(db, days)
    _GRAPH_CACHE[days] = (now, payload)
    return payload
