"""Factor: hedge-fund positioning follow (13F).

Source: Frazzini & Lamont (2008) "Dumb Money: Mutual Fund Flows and the
Cross-Section of Stock Returns," JFE 88(2). SSRN https://ssrn.com/abstract=419980.
Follow-up: Cohen-Frazzini-Malloy (2007) "The Small World of Investing"
and Sias-Turtle-Zykaj (2016). Griffin-Xu (2023) recent replication.

Signal:
    score = Δ(aggregate_shares_held_by_top_hedge_funds) / shares_outstanding

Cross-sectional rank across the universe: top decile = names hedge funds
are accumulating; bottom decile = names hedge funds are distributing.

Rebalance: quarterly, 45-day lag from quarter-end so 13F-HR filings
have all landed at EDGAR before we rank.

Params:
    top_n_funds  count of hedge funds to include (default 100 largest)
    min_holdings minimum non-zero holding rows to require (default 30)

Data source: SEC EDGAR 13F-HR filings. Table: `smart_money_13f_holdings`
populated by app.jobs.edgar_13f_ingest (separate scheduled job). This
factor reads from that cache — degrades gracefully to empty scores if
the ingest job hasn't run yet.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    top_n_funds = int(params.get("top_n_funds", 100))
    min_holdings = int(params.get("min_holdings", 30))

    # Detect whether the ingest table exists yet. Portfolios inheriting this
    # factor before the EDGAR job ships should score empty (no PR
    # execution) rather than raise.
    try:
        _probe = db.execute(text(
            "SELECT 1 FROM smart_money_13f_holdings LIMIT 1"
        )).fetchone()
    except Exception as exc:
        logger.warning(
            "[factor:smart_money_13f] table smart_money_13f_holdings not "
            "available (ingest job not shipped yet?) — returning empty scores: %s",
            exc,
        )
        return {}

    if _probe is None:
        logger.warning(
            "[factor:smart_money_13f] holdings table empty — waiting for first "
            "EDGAR ingest run",
        )
        return {}

    # Rank stocks by change in aggregate held shares (this-quarter minus
    # prior-quarter), for the top_n_funds hedge funds ranked by total AUM.
    # smart_money_13f_holdings schema (expected):
    #   fund_cik TEXT, quarter DATE, symbol TEXT, shares_held BIGINT,
    #   fund_aum_cents BIGINT
    scores: dict[str, float] = {}
    try:
        rows = db.execute(text("""
            WITH top_funds AS (
                SELECT fund_cik
                  FROM smart_money_13f_holdings
                 WHERE quarter = (SELECT MAX(quarter) FROM smart_money_13f_holdings)
                 GROUP BY fund_cik
                 ORDER BY MAX(fund_aum_cents) DESC
                 LIMIT :top_n
            ),
            current_q AS (
                SELECT h.symbol, SUM(h.shares_held) AS shares_current
                  FROM smart_money_13f_holdings h
                  JOIN top_funds tf ON tf.fund_cik = h.fund_cik
                 WHERE h.quarter = (SELECT MAX(quarter) FROM smart_money_13f_holdings)
                 GROUP BY h.symbol
            ),
            prior_q AS (
                SELECT h.symbol, SUM(h.shares_held) AS shares_prior
                  FROM smart_money_13f_holdings h
                  JOIN top_funds tf ON tf.fund_cik = h.fund_cik
                 WHERE h.quarter = (
                     SELECT MAX(quarter) FROM smart_money_13f_holdings
                     WHERE quarter < (SELECT MAX(quarter) FROM smart_money_13f_holdings)
                 )
                 GROUP BY h.symbol
            )
            SELECT COALESCE(c.symbol, p.symbol) AS sym,
                   COALESCE(c.shares_current, 0) - COALESCE(p.shares_prior, 0) AS delta
              FROM current_q c
              FULL OUTER JOIN prior_q p ON c.symbol = p.symbol
        """), {"top_n": top_n_funds}).fetchall()
        for r in rows:
            sym = str(r[0] or "").upper()
            delta = float(r[1] or 0)
            if not sym:
                continue
            if sym not in [s.upper() for s in symbols]:
                continue
            scores[sym] = delta
    except Exception as exc:
        logger.warning(
            "[factor:smart_money_13f] ranking query failed: %s — returning empty",
            exc,
        )
        return {}

    if len(scores) < min_holdings:
        logger.warning(
            "[factor:smart_money_13f] only %d holdings found (need %d) — returning empty",
            len(scores), min_holdings,
        )
        return {}

    logger.warning(
        "[factor:smart_money_13f] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
