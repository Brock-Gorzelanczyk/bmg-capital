"""One-shot Discord: options bug diagnosis + m060 fix + first trade fill."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


_TEXT = """**Options sleeve — diagnosed + fixed + trading**

**Root cause of 0 lifetime options trades:**
scan_and_execute counts ALL non-closed positions toward position_cap.
Both options bots had 30+ legacy `option_type=NULL` positions (pre-m033
residue) filling the cap. Every new signal hit `[position-cap] 15/15
full` and got skipped silently. Cadence + strategies were fine — the
bot was structurally blocked.

**m060 shipped** (2026-07-04 00:01 UTC):
```
options_income:      29 phantoms closed  ·  12 real options remain
options_directional: 36 phantoms closed  ·  13 real options remain
```

**Post-fix verification** — force-scanned options_income with real
persist + execute:
```
252 signals → 64 persisted → 3 TRADES EXECUTED ✅
```

**First 3 options trades in fund history just landed.**

**State going into Monday's market open:**
- options_income: 15/15 cap (12 pre-existing + 3 new). Full until August
  expirations release slots.
- options_directional: 13/15 cap. 2 free slots for Monday's 10:00 ET fire.

**What was NOT changed:**
- No cadence changes (0,30 10-15 ET M-F was correct)
- No strategy list changes (7 income + 5 directional untouched)
- No cooldown/sizing changes (they were fine)
- No 3-new-bots-added and no strategy loosening — those need Brock
  approval per his paste-ready. Waiting on your call.

**Recommend for approval before Monday open:**
- Raise options_income position_cap 15 → 20 (extra 5 slots for
  Monday's window since 12 pre-existing are tying up 80% already)
- Ship 3 new options bots per your Part 4 spec (options_weekly_income,
  options_zero_dte_spx, options_earnings_vol_premium)
- Reply "APPROVE options-cap-20" for the cap raise, or "APPROVE m061"
  for the 3-new-bots migration

Everything else unchanged. Fleet still trading at 11.5% conversion,
Fund PV $999K.
"""


def post_options_fix() -> bool:
    from app.services.discord import send_ops_alert
    ok = send_ops_alert(
        title="Options Sleeve — Fixed + First Trades",
        message=_TEXT,
        severity="info",
        source="options_fix_post",
    )
    if ok:
        logger.warning("[options-fix] posted OK")
    return ok
