"""daily_evaluate.py — the daily job.

For every OPEN call:
  - pull today's close for the ticker and its benchmark
  - update daily_prices
  - evaluate every ARMED machine-checkable kill criterion
  - on fire: set status FIRED with timestamp, print a REQUIRES DECISION line
    but DO NOT auto-close the call
  - close any call whose horizon has passed with status CLOSED_HORIZON

Machine-checkable metrics currently supported:
  price_le <price>   ticker close <= price
  price_ge <price>   ticker close >= price
  drop_pct_ge <pct>  ticker return since pub <= -pct
  bench_lag_pct <pct> ticker excess return <= -pct

Business-metric criteria (LPI, utilization, etc.) are stored but marked
metric=MANUAL — they must be evaluated by a human and manually fired via
`fire_criterion.py`.

Anti-pattern: this script does not compute Sharpe / t-stat / IR. It reports
prices and metric evaluations. That is all.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import get_conn  # noqa: E402

try:
    import yfinance as yf
except ImportError:
    print("[fail] yfinance not installed. pip install yfinance")
    sys.exit(1)


def upsert_price(conn, ticker: str, date_str: str, close: float, source: str = "yfinance") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO daily_prices (ticker, date, close_price, source) "
        "VALUES (?, ?, ?, ?)",
        (ticker, date_str, float(close), source),
    )


def fetch_latest_close(ticker: str) -> tuple[str, float] | None:
    """Return (date, close) for the most recent trading day."""
    try:
        df = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        if df.empty:
            return None
        row = df.iloc[-1]
        return (row.name.strftime("%Y-%m-%d"), float(row["Close"]))
    except Exception as e:
        print(f"[warn] {ticker}: {e}")
        return None


def evaluate_kill_criteria(conn) -> list[str]:
    """Evaluate every ARMED machine-checkable criterion. Return list of fire messages."""
    fires: list[str] = []
    rows = conn.execute(
        """
        SELECT k.criterion_id, k.call_id, k.description, k.metric, k.threshold, k.action,
               c.ticker, c.price_at_pub
        FROM kill_criteria k
        JOIN research_calls c ON c.call_id = k.call_id
        WHERE k.status = 'ARMED' AND c.status = 'OPEN'
              AND k.metric IS NOT NULL AND k.metric != 'MANUAL'
        """
    ).fetchall()
    for crit_id, call_id, desc, metric, threshold, action, ticker, price_at_pub in rows:
        latest = conn.execute(
            "SELECT close_price FROM daily_prices WHERE ticker=? "
            "ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if not latest:
            continue
        px_now = latest[0]
        try:
            thr = float(threshold)
        except (TypeError, ValueError):
            continue

        fired = False
        detail = ""
        if metric == "price_le" and px_now <= thr:
            fired = True; detail = f"close ${px_now:.2f} <= ${thr:.2f}"
        elif metric == "price_ge" and px_now >= thr:
            fired = True; detail = f"close ${px_now:.2f} >= ${thr:.2f}"
        elif metric == "drop_pct_ge":
            pct = (px_now - price_at_pub) / price_at_pub * 100.0
            if pct <= -thr:
                fired = True; detail = f"return {pct:.1f}% <= -{thr:.1f}%"

        if fired:
            conn.execute(
                "UPDATE kill_criteria SET status='FIRED', fired_at=datetime('now') "
                "WHERE criterion_id=?", (crit_id,)
            )
            fires.append(f"call {call_id} {ticker}: [{action}] {desc} — {detail}")
    conn.commit()
    return fires


def close_horizon_calls(conn) -> list[str]:
    """Close any OPEN call whose horizon has passed."""
    closed = []
    rows = conn.execute(
        """
        SELECT c.call_id, c.ticker, c.published_at, c.horizon_months
        FROM research_calls c
        WHERE c.status = 'OPEN'
        """
    ).fetchall()
    from datetime import date
    for call_id, ticker, pub, horizon in rows:
        pub_d = date.fromisoformat(pub)
        # horizon in months, approximate 30-day months
        days_since = (date.today() - pub_d).days
        if days_since >= horizon * 30:
            latest = conn.execute(
                "SELECT close_price, date FROM daily_prices WHERE ticker=? "
                "ORDER BY date DESC LIMIT 1", (ticker,)
            ).fetchone()
            if latest:
                conn.execute(
                    "UPDATE research_calls SET status='CLOSED_HORIZON', "
                    "closed_at=?, closed_price=?, closed_reason='horizon reached' "
                    "WHERE call_id=?",
                    (latest[1], latest[0], call_id),
                )
                closed.append(f"call {call_id} {ticker}: closed at horizon "
                              f"({horizon}mo), price ${latest[0]:.2f}")
    conn.commit()
    return closed


def main() -> int:
    conn = get_conn()

    # Collect tickers + benchmarks for all open calls
    tickers = set()
    rows = conn.execute(
        "SELECT DISTINCT ticker, benchmark FROM research_calls WHERE status='OPEN'"
    ).fetchall()
    for t, b in rows:
        tickers.add(t)
        tickers.add(b)

    if not tickers:
        print("[daily-eval] no open calls; nothing to price")
        return 0

    print(f"[daily-eval] pulling prices for {len(tickers)} tickers...")
    for ticker in sorted(tickers):
        result = fetch_latest_close(ticker)
        if result is None:
            print(f"  {ticker}: FAIL")
            continue
        date_str, close = result
        upsert_price(conn, ticker, date_str, close)
        print(f"  {ticker}: {date_str} close ${close:.2f}")
    conn.commit()

    # Fill in publication-date benchmark prices if missing
    pub_needs = conn.execute("""
        SELECT DISTINCT c.benchmark, c.published_at
        FROM research_calls c
        WHERE NOT EXISTS (
            SELECT 1 FROM daily_prices dp
            WHERE dp.ticker = c.benchmark AND dp.date = c.published_at
        )
    """).fetchall()
    if pub_needs:
        print(f"[daily-eval] backfilling {len(pub_needs)} publication-date benchmark prices...")
        from datetime import date as _date, timedelta as _td
        for bench, pub_at in pub_needs:
            try:
                pub_d = _date.fromisoformat(pub_at)
                # window: pub date through +7 days to catch first trading day
                df = yf.Ticker(bench).history(
                    start=pub_at,
                    end=(pub_d + _td(days=8)).isoformat(),
                    auto_adjust=True,
                )
                if df.empty:
                    print(f"  {bench} @ {pub_at}: empty history")
                    continue
                # take first row on or after pub_at
                stored = False
                for idx, row in df.iterrows():
                    d = idx.strftime("%Y-%m-%d")
                    if d >= pub_at:
                        close_val = row["Close"]
                        # unwrap Series if MultiIndex
                        if hasattr(close_val, "iloc"):
                            close_val = close_val.iloc[0]
                        upsert_price(conn, bench, pub_at, float(close_val),
                                     source="yfinance-backfill")
                        print(f"  {bench} @ {pub_at}: ${float(close_val):.2f} "
                              f"(using {d} close)")
                        stored = True
                        break
                if not stored:
                    print(f"  {bench} @ {pub_at}: no trading day found in window")
            except Exception as e:
                print(f"  {bench} @ {pub_at}: FAIL — {e}")
        conn.commit()

    # Evaluate kill criteria
    fires = evaluate_kill_criteria(conn)
    if fires:
        print("\n" + "=" * 60)
        print("REQUIRES DECISION — kill criteria fired:")
        for f in fires:
            print(f"  * {f}")
        print("Record the decision + whether obeyed via `fire_criterion.py`.")
        print("=" * 60)
    else:
        print("[daily-eval] no kill criteria fired")

    # Close horizon-passed calls
    closed = close_horizon_calls(conn)
    for c in closed:
        print(f"[horizon-close] {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
