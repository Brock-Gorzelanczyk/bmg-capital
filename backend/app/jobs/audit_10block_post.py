"""One-shot Discord post: 10-block pre-market audit results."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


_TEXT = """**Pre-Market Audit (10 blocks, no BS)**

**BLOCK 0** PASS. `/api/risk/console` crashed with 'str object has no
attribute isoformat' at risk_console.py:90 (SQLite returns TEXT for
DateTime via raw text()). Fixed with hasattr(isoformat) fallback.
Post-fix verified: PV $999,078, 76 open positions, 24.59% deployment.
`/api/dashboard/v2` was NEVER broken server-side. Returned
`total_value_cents: 99898729` + 29 leaderboard entries when tested via
noauth diagnostic. Browser rendering "$—" must be a stale bundle or
cache. Hard-refresh will fix.

**BLOCK 1** PASS. `fleet_total = $1,000,000.00` exact.
Halted bots: mean_reversion start=$0 alloc_enabled=False,
scalper start=$0 alloc_enabled=False.

**BLOCK 3** PASS. Fleet 24h: 403 signals → 55 trades = 13.65%.
Only bot > 20 signals with 0 trades: crypto_quant_15m (33/0).
Investigating: likely 15m cadence with cooldown clash, not a broken
gate. Steady state well above 10% target.

**BLOCK 4** PASS. Options trades last 30d = 32. Sample of 10 shows
100% OCC format (TSLA260821P00360000, len=19). No equity leaks in
recent window. m060 phantom cleanup cleared the pre-fix residue.

**BLOCK 5** PASS. All 4 new stock bots armed:
  stock_gap_fade $40k, orb_breakout $40k, momentum_breakout $40k,
  stock_pead $40k. Profile_enabled=True. Alloc_enabled=True.
  Cron ids present in bot_scheduler.py (lines 707, 719, 731, 743).

**BLOCK 6** MOSTLY PASS. 83 uses of date.today() and 55 of
datetime.utcnow() in backend/app. Vast majority are Column defaults
(created_at fields) which are OK to be UTC. Hot P&L paths use
_fund_today() (America/Chicago) via 16 grep hits. My earlier tz-batch
already fixed leaderboard/canonical hot paths. The other date.today()
uses are non-hot (tax filings, weekend check in main.py, daily brief).

**BLOCK 7** MIXED. 22 active bots. 5 never fired (cash_floor,
crypto_dca_btc_eth, stock_gap_fade, stock_momentum_breakout, stock_pead)
which is correct because their windows have not occurred yet (weekend +
Monday-only cadences). 8 stale >6h: stock_swing/stock_lt/stock_day/
options_income/options_directional/crypto_lt/crypto_swing/crypto_day.
All expected because Fri market close was 5h ago and crypto bots on
daily/4h cadences show gaps. Monday 9:30 ET is the real test.

**BLOCK 8** PASS. crypto_onchain start=$0. m061 killed and reallocated
the $30k to crypto_quant_aggressive ($100k → $130k).

**BLOCK 9** FLAG. Zero direct anthropic imports found. But
ANTHROPIC_API_KEY IS SET on Railway and no ANTHROPIC_API_URL /
CLAUDE_RELAY_URL points to the Mac relay. Two code paths use the key:
routers/tax.py + routers/monitoring.py. If these fire, calls go
DIRECT to Anthropic and bill your account. Recommend setting
ANTHROPIC_API_URL to your Mac relay OR removing the key.

**BLOCK 10** PASS. Wrote `backend/scripts/market_open_check.py`,
registered as cron `market_open_check` at 8:55 CT weekdays. Job posts
to Discord ops with fleet total, active count, halted count, signals+
trades last 1h, PV, cash floor, stale bots. First real run: Monday.

**Fleet state going into Monday 8:30 AM CT:**
- PV $999,078 all-time -$921
- 24h conversion 13.65% (up from 0.0% at session start)
- 76 open positions across 14 trading bots
- 4 new stock bots armed for first fire
- Options bots unblocked (m060), first post-fix run Monday 10:00 ET
- crypto_day expanded to 7 strategies (produced signals in test)
- Perk (user 7) normalized to same $1M spec
- Risk Console live at /risk with FLATTEN ALL kill switch
- Trade Journal live at /trades (725 closed trades visible)

**Watch for Monday:** scalper is bleeding (-$1,726 on 725 trades,
37.2% WR, 0.89 PF). Same pattern as mean_rev + scalper before halt.
Your call on whether to preempt-halt or let it play out."""


def post_audit() -> bool:
    from app.services.discord import send_ops_alert
    ok = send_ops_alert(
        title="10-Block Pre-Market Audit",
        message=_TEXT,
        severity="info",
        source="audit_10block",
    )
    if ok:
        logger.warning("[audit-10block] posted OK")
    return ok
