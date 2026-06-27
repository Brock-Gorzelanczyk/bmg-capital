#!/usr/bin/env python3
"""Standalone concentration / exposure report for user_id=1.

Prints three sections:
  - SINGLE-NAME TOP 10 (symbols by open-position notional, with % of user
    starting capital)
  - BY SECTOR (notional + % of user starting capital, ETFs grouped)
  - CLUSTER WATCH (any sector with >= CLUSTER_MAX_POSITIONS positions —
    flagged as CLUSTER WARNING)

Run from repo root:
    python scripts/check_concentration.py

Or from backend (so `app.*` imports resolve):
    cd backend && .venv/bin/python ../scripts/check_concentration.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict


def _add_backend_to_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.join(os.path.dirname(here), "backend")
    if os.path.isdir(backend) and backend not in sys.path:
        sys.path.insert(0, backend)


def main(user_id: int = 1) -> int:
    _add_backend_to_path()

    try:
        from app.db.session import SessionLocal
    except Exception as exc:
        print(f"ERROR: could not import app.db.session: {exc}", file=sys.stderr)
        return 2

    from strategy_lab.core.concentration_gate import (
        user_total_capital,
        _user_allocation_ids,
    )
    from strategy_lab.core.sector_map import get_sector

    db = SessionLocal()
    try:
        total_capital = user_total_capital(db, user_id)
        if total_capital <= 0:
            print(f"user_id={user_id} has no starting capital. Aborting.")
            return 1

        alloc_ids = _user_allocation_ids(db, user_id)
        if not alloc_ids:
            print(f"user_id={user_id} has no allocations.")
            return 1

        from sqlalchemy import text as sql_text

        binds = {f"a{i}": v for i, v in enumerate(alloc_ids)}
        in_clause = ",".join(f":a{i}" for i in range(len(alloc_ids)))
        rows = db.execute(sql_text(
            f"SELECT symbol, qty, avg_cost_cents "
            f"  FROM bot_positions "
            f" WHERE allocation_id IN ({in_clause}) "
            f"   AND closed_at IS NULL"
        ), binds).fetchall()

        by_symbol: dict = defaultdict(float)
        for r in rows:
            sym = r[0]
            notional = float(r[1] or 0) * float(r[2] or 0) / 100.0
            by_symbol[sym] += notional

        by_sector: dict = defaultdict(float)
        positions_per_sector: dict = defaultdict(int)
        for sym, notional in by_symbol.items():
            sec = get_sector(sym) or "unknown"
            by_sector[sec] += notional
            positions_per_sector[sec] += 1

        cluster_max = int(os.getenv("CLUSTER_MAX_POSITIONS", "3"))

        print(f"=== CONCENTRATION REPORT — user_id={user_id} ===")
        print(f"Total starting capital: ${total_capital:,.0f}")
        print(f"Open positions: {len(by_symbol)} symbols across {len(by_sector)} sectors")
        print()

        print("--- SINGLE-NAME TOP 10 ---")
        top = sorted(by_symbol.items(), key=lambda x: x[1], reverse=True)[:10]
        if not top:
            print("  (no open positions)")
        for sym, n in top:
            pct = n / total_capital * 100
            print(f"  {sym:<10} ${n:>12,.0f}  {pct:>6.2f}%")
        print()

        print("--- BY SECTOR ---")
        sec_sorted = sorted(by_sector.items(), key=lambda x: x[1], reverse=True)
        for sec, n in sec_sorted:
            pct = n / total_capital * 100
            print(f"  {sec:<18} ${n:>12,.0f}  {pct:>6.2f}%  ({positions_per_sector[sec]} pos)")
        print()

        print("--- CLUSTER WATCH ---")
        flagged = [(s, c) for s, c in positions_per_sector.items() if c >= cluster_max]
        if not flagged:
            print(f"  (no sectors with >= {cluster_max} positions)")
        else:
            for sec, c in sorted(flagged, key=lambda x: x[1], reverse=True):
                pct = by_sector[sec] / total_capital * 100
                print(f"  CLUSTER WARNING: {sec} has {c} positions, "
                      f"${by_sector[sec]:,.0f} ({pct:.2f}%)")
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    _uid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    raise SystemExit(main(_uid))
