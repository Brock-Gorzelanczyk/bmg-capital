"""One-shot Discord post: answers to Brock's 4 clarifications.

Fires on boot when BMG_POST_4Q=true.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


_TEXT = """**Brock's 4 clarifications — answered with data**

**Q1: 24h fleet conversion**
`6,214 signals → 718 trades = 11.55%` over the last 24h. NOT 1.2% —
that was a fresh-deploy snapshot. Fleet is genuinely converting at
11.5% steady-state. crypto_quant_scalp_1m alone: 439 trades (33.6%).

**Q2: SHIP 6 24h clamp — redundant?**
Mostly, now. After tonight's per-strategy fix, the SHIP 6 clamp reads
the same family-minutes as the YAML cooldown gate (scalp 5min / day
30min / swing 4h / LT 24h). It's defense-in-depth — same behavior via
different tables (bot_symbol_cooldown vs bot_signals). Safe to keep;
not blocking anything the YAML gate wouldn't also block.

**Q3: Deployment cap 85% → 95%**
Recommend YES for stock_lt + crypto_quant_aggressive. stock_lt hit cap
last night (`$154K deployed / $170K max`), missed 16 symbols. Bumping
to 95% = $190K max = ~1.5 extra concurrent positions per bot. Modest,
meaningful. Reply APPROVE and I ship. Do not touch other bots' caps.

**Q4: Cron reconciliation — 19 → 34 (undercount)**
Log-line count was misleading; some registrations use logger.info not
logger.warning. Actual total: 34 bot cron jobs registered. All 4 new
stock bots (gap_fade, orb_breakout, momentum_breakout, pead) ARE
registered. Cash Floor has 2 crons (cash_floor_open at 9:35 ET +
cash_floor_close at 15:50 ET). Options bots are registered silently
(no log emission on add_job).

Nothing else blocking market open. Fund PV $999K honest, kill switch
live, trade journal live, 71 open positions, 11.5% conversion sustained.
"""


def post_4q() -> bool:
    from app.services.discord import send_ops_alert
    ok = send_ops_alert(
        title="4 Clarifications Answered",
        message=_TEXT,
        severity="info",
        source="four_clarifications",
    )
    if ok:
        logger.warning("[4q] posted OK")
    return ok
