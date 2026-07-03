"""One-shot Discord post: or-fallback audit results per Brock's ask.

Fires on boot when BMG_POST_OR_AUDIT=true. Then unset the env var so it
doesn't double-post on subsequent boots.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


_AUDIT_TEXT = """**or-fallback capital audit — 2026-07-03 01:00 CT**

Grepped entire backend for capital/allocation fields pulled with `or` fallback.
Same root-cause class as the $180K phantom on /strategy header (`0 or X` returns X).

**FIXED THIS PASS (7 sites)**
```
runner.py:608          cap_cents = alloc.starting_capital or within_portfolio or 0
runner.py:695          _log_capital = ... or ... or 5_000_000
runner.py:1358         cap_cents (gross exposure gate)
runner.py:1764         capital_usd (options _execute_signal)
runner.py:2129         equity (equity resolve)
runner.py:2225         capital_usd (equity _execute_signal)
runner.py:2231         capital_usd (deployment sizer)
admin.py:763           admin capital summary
per_bot_vol_target.py:102   equity curve seed
```
All converted to `is not None` so 0 is respected.

**PREVIOUSLY FIXED**
```
canonical.py:248       starting_capital_cents (drove the $180K phantom)
```

**SAFE — `or 0` where 0 is the correct default** (~45 sites)
```
dashboard.py, leaderboard.py, portfolio.py, performance.py,
performance_service.py, portfolio.py, allocation.py, voice_ai.py,
compute_bot_stats.py, daily_journal.py, canonical.py:636/696/701/938+
```
These sum or filter using `starting_capital_cents or 0` — if capital
is 0, we correctly exclude that bot. No inflation risk.

**SEMANTICALLY CORRECT — inception fallback**
```
canonical.py:720, 729   inception_capital or starting_capital or 0
```
For halted bots, inception (original seed, e.g. $70k for scalper) is
the right all-time-return-% denominator; starting_capital = 0 is not.
The `or` here is intentional. No fix needed.

**RESULT**
Fund PV sum verified at $1,000,000 exact against invariant.
No more halted-bot phantom values leaking into totals.
"""


def post_audit() -> bool:
    from app.services.discord import send_ops_alert
    ok = send_ops_alert(
        title="Capital Read Audit (or-fallback)",
        message=_AUDIT_TEXT,
        severity="info",
        source="or_fallback_audit",
    )
    if ok:
        logger.warning("[or-audit] posted OK to ops channel")
    else:
        logger.warning("[or-audit] post FAILED (see ops-alert logs)")
    return ok
